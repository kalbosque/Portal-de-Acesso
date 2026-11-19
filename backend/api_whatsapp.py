import asyncio
import os
import json
import time
import base64
import re
import uuid
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional
from urllib.parse import urlparse, urlunparse
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Body, UploadFile, File, Form
from fastapi.responses import RedirectResponse, Response, FileResponse
from sqlalchemy import text, func
from sqlmodel import Session, select, desc

from models import Chamado, ChamadoInteracao, Usuario, ContatoWhatsApp
from database import engine
from atendimento_tenant_context import tenant_id_for_instance
from auth_utils import get_signed_cookie, normalize_permissions
from websocket_manager import manager
from atendimento_tenant_context import is_enabled as atendimento_multiempresa_enabled, resolve_context, tenant_id_for_instance

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

# Contas autorizadas especificamente para conectar aparelhos pelo Tauri.
# Esta lista é independente do perfil administrativo do Portal.
TAURI_ALLOWED_USERS = {"admin", "ti@atual-rnc.com.br"}


@router.get("/media/{filename:path}")
def serve_whatsapp_media(filename: str, request: Request):
    """Serve anexos da conversa com suporte a Content-Type correto e Range requests (streaming de audio/video)."""
    _require_atendimento_access(request)
    safe_name = os.path.basename(str(filename or "").strip())
    if not safe_name or safe_name != str(filename or "").strip().split("/")[-1]:
        raise HTTPException(status_code=404, detail="Mídia não encontrada")
    media_path = os.path.join(_BASE_DIR, "public_html", "uploads", "whatsapp_media", safe_name)
    if not os.path.isfile(media_path):
        raise HTTPException(status_code=404, detail="Mídia não encontrada")

    ext = safe_name.split(".")[-1].lower() if "." in safe_name else ""
    mime_map = {
        "ogg": "audio/ogg",
        "oga": "audio/ogg",
        "opus": "audio/ogg",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "m4a": "audio/mp4",
        "mp4": "video/mp4",
        "webm": "video/webm",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }
    media_type = mime_map.get(ext) or "application/octet-stream"

    return FileResponse(
        media_path,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=86400",
        }
    )

_whatsapp_columns_ready = False
_connected_map_cache = {"expires_at": 0.0, "value": {}}
_group_name_cache = {}
_GROUP_NAME_CACHE_TTL = 600
DISPLAY_TIMEZONE = ZoneInfo("America/Porto_Velho")
_agenda_pending_slots: dict[str, tuple[str, str, float]] = {}


def _get_instance_presence(instance: dict) -> tuple[str, set]:
    """Consulta a presença de uma instância sem bloquear as demais."""
    name = str(instance.get("instanceName") or "")
    if not name:
        return name, set()
    try:
        base_url, wa_token, resolved = get_evolution_api_endpoints(name)
        if not base_url:
            return name, set()
        headers = {"apikey": wa_token} if wa_token else {}
        response = requests.get(
            f"{base_url}/instance/connectionState/{resolved}",
            headers=headers,
            timeout=1.5,
        )
        if response.status_code == 200:
            return name, set(_extract_connected_numbers(response.json() or {}))
    except Exception:
        pass
    return name, set()


def _display_datetime(value: datetime) -> datetime:
    """Converte timestamps UTC armazenados para o horário de Rondônia."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(DISPLAY_TIMEZONE)


def _whatsapp_message_datetime(value) -> datetime:
    """Converte timestamps da Evolution para UTC, usando agora como fallback."""
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        try:
            timestamp = float(raw)
            if timestamp > 100_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, timezone.utc)
        except (ValueError, OverflowError, OSError):
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_contact_key(num: str) -> str:
    """Retorna chave canônica para deduplicação considerando 8º/9º dígito móvel brasileiro."""
    if num and num.startswith("55") and len(num) == 12 and num[4] in "789":
        return f"{num[:4]}9{num[4:]}"
    return num or ""


def _normalize_contact_number(value: str) -> Optional[str]:
    """Padroniza telefones brasileiros com código do país quando possível, rejeitando IDs alfanuméricos."""
    raw = str(value or "").strip()
    if not raw:
        return None
    raw_lower = raw.lower()
    if any(tag in raw_lower for tag in ("@lid", "@g.us", "@broadcast")):
        return None

    user_part = raw.split("@")[0].split(":")[0].strip()
    # Se a parte do identificador contém letras (como IDs CUID do Prisma: cmulmkckp...), NÃO é telefone!
    if re.search(r"[a-zA-Z]", user_part):
        return None

    digits = re.sub(r"\D", "", user_part)
    if not digits or set(digits) == {"0"}:
        return None

    # Telefone brasileiro com DDD (10 ou 11 dígitos, ex: 6999817823 -> 556999817823)
    if len(digits) in (10, 11):
        return f"55{digits}"

    # Telefone brasileiro já com DDI 55 (12 ou 13 dígitos)
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits

    # Telefone internacional E.164 válido (10 a 15 dígitos)
    if 10 <= len(digits) <= 15:
        return digits

    return None


def _real_contact_number(item: dict) -> Optional[str]:
    """Obtém somente telefone real, nunca o identificador interno @lid ou cuid de banco."""
    if not isinstance(item, dict):
        return None

    # Se o contato como um todo possui JID interno do WhatsApp (@lid, grupo ou broadcast), rejeita
    remote_jid = str(item.get("remoteJid") or item.get("jid") or "").strip().lower()
    if any(tag in remote_jid for tag in ("@lid", "@g.us", "@broadcast")):
        return None

    # Verifica campos específicos de telefone
    for key in ("number", "phoneNumber", "phone", "remoteJid", "jid"):
        raw = str(item.get(key) or "").strip()
        if not raw:
            continue
        number = _normalize_contact_number(raw)
        if number:
            return number

    # Somente testa o 'id' se não contiver letras (evita os CUIDs do Evolution API)
    raw_id = str(item.get("id") or "").strip()
    if raw_id and not re.search(r"[a-zA-Z]", raw_id.split("@")[0]):
        number = _normalize_contact_number(raw_id)
        if number:
            return number

    return None


_PROFILE_PIC_CACHE = {}  # {key: (url, timestamp, ttl)}
_PROFILE_PIC_BYTES_CACHE = {}  # {key: (bytes_content, media_type, timestamp)}

def _fetch_profile_picture_url(base_url: str, token: str, instance: str, number: str) -> Optional[str]:
    """Busca a foto quando findContacts nÃ£o a fornece diretamente, com cache em memÃ³ria confiavel."""
    raw_number = str(number or "").strip()
    is_group = raw_number.lower().endswith("@g.us")
    normalized = raw_number if is_group else _normalize_contact_number(raw_number)
    if not base_url or not normalized:
        if not base_url or is_group or "@lid" not in raw_number.lower():
            return None
        normalized = raw_number

    cache_key = f"{instance}:{normalized}"
    now = time.time()
    if cache_key in _PROFILE_PIC_CACHE:
        cached_entry = _PROFILE_PIC_CACHE[cache_key]
        cached_url = cached_entry[0]
        cached_at = cached_entry[1]
        ttl = cached_entry[2] if len(cached_entry) > 2 else 600
        if now - cached_at < ttl:
            return cached_url

    try:
        if is_group:
            group_response = requests.get(
                f"{base_url}/group/findGroupInfos/{instance}",
                headers={"apikey": token or ""},
                params={"groupJid": normalized},
                timeout=4,
            )
            if group_response.ok:
                group_payload = group_response.json()
                candidates = [group_payload] if isinstance(group_payload, dict) else []
                for item in candidates:
                    picture = item.get("pictureUrl") or item.get("profilePictureUrl") or item.get("profilePicUrl") or item.get("picture")
                    if picture:
                        _PROFILE_PIC_CACHE[cache_key] = (picture, now, 86400)
                        return picture
                _PROFILE_PIC_CACHE[cache_key] = (None, now, 1800)
                return None
            elif group_response.status_code == 404:
                _PROFILE_PIC_CACHE[cache_key] = (None, now, 1800)
            return None

        if "@lid" in raw_number.lower():
            contacts_response = requests.post(
                f"{base_url}/chat/findContacts/{instance}",
                headers={"apikey": token or "", "Content-Type": "application/json"},
                json={"where": {}, "take": 500, "skip": 0, "orderBy": {}},
                timeout=4,
            )
            contacts_payload = contacts_response.json() if contacts_response.ok else []
            if isinstance(contacts_payload, dict):
                contacts_payload = contacts_payload.get("contacts") or contacts_payload.get("data") or contacts_payload.get("results") or []
            if isinstance(contacts_payload, list):
                lid = raw_number.split("@")[0].split(":")[0]
                match = next((item for item in contacts_payload if isinstance(item, dict) and lid == str(item.get("id") or item.get("remoteJid") or item.get("jid") or "").split("@")[0].split(":")[0]), None)
                if match:
                    picture = match.get("profilePictureUrl") or match.get("profilePicUrl") or match.get("profile_picture")
                    if picture:
                        _PROFILE_PIC_CACHE[cache_key] = (picture, now, 86400)
                        return picture
                    normalized = _real_contact_number(match)
            if not normalized or "@lid" in str(normalized).lower():
                _PROFILE_PIC_CACHE[cache_key] = (None, now, 1800)
                return None

        response = requests.post(
            f"{base_url}/chat/fetchProfilePictureUrl/{instance}",
            headers={"apikey": token or "", "Content-Type": "application/json"},
            json={"number": normalized},
            timeout=4,
        )
        if response.ok:
            payload = response.json()
            if isinstance(payload, dict):
                pic = payload.get("profilePictureUrl") or payload.get("profilePicUrl") or payload.get("picture")
                if pic:
                    _PROFILE_PIC_CACHE[cache_key] = (pic, now, 86400)
                    return pic
            _PROFILE_PIC_CACHE[cache_key] = (None, now, 3600)
            return None
        elif response.status_code == 404:
            _PROFILE_PIC_CACHE[cache_key] = (None, now, 3600)
            return None
        else:
            return None
    except Exception:
        return None

# Caminho absoluto relativo ao diretório do script — garante leitura do config correto
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_BASE_DIR, "public_html", "includes", "config.json")

# ─── Helpers para Configuração e Integração com Evolution API ────────────────

def get_whatsapp_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            print(f"[api_whatsapp] Erro ao ler config.json: {e}")
    return {}


def user_can_access_instance(request: Request, instance: Optional[str]) -> bool:
    """Aplica a restrição por número; lista vazia significa acesso geral."""
    if get_signed_cookie(request, "user_role") == "admin":
        return True
    if not instance:
        return True
    if atendimento_multiempresa_enabled():
        try:
            context = resolve_context(request)
            instance_tenant_id = tenant_id_for_instance(instance)
            if context.tenant_id is None or instance_tenant_id != context.tenant_id:
                return False
        except HTTPException:
            return False
    access = get_whatsapp_config().get("WHATSAPP_INSTANCE_ACCESS", {}) or {}
    allowed = access.get(str(instance))
    if not allowed:
        return True
    current = get_signed_cookie(request, "user_name", "")
    return current in {str(name) for name in allowed}


def _can_edit_identity(request: Request) -> bool:
    role = get_signed_cookie(request, "user_role")
    if atendimento_multiempresa_enabled() and role == "cliente_atendimento":
        try:
            context = resolve_context(request)
            if context.tenant_id is not None:
                with Session(engine) as session:
                    row = session.exec(text("""
                        SELECT papel FROM usuarios_empresas_atendimento
                        WHERE empresa_atendimento_id = :tenant_id AND usuario_id = :user_id AND ativo = TRUE
                    """).bindparams(tenant_id=context.tenant_id, user_id=context.user_id)).first()
                return bool(row and row[0] == "tenant_admin")
        except HTTPException:
            return False
    if role in ("admin", "operator", "gestor", "gerente", "supervisor", "recepcao", "recepção", "recepcionista"):
        return True
    try:
        permissions = normalize_permissions(json.loads(get_signed_cookie(request, "user_perms", "[]") or "[]"))
        return "Atendimento" in permissions or "Suporte" in permissions
    except Exception:
        return False


@router.post("/identity")
async def update_attendance_identity(
    request: Request,
    nome: str = Form(""),
    logo: Optional[UploadFile] = File(None),
):
    if not _can_edit_identity(request):
        raise HTTPException(status_code=403, detail="Sem permissão para alterar a identificação da Central.")
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS foto_perfil_url VARCHAR(500)"))
    except Exception as exc:
        print(f"[IDENTIDADE] Migração de foto ignorada: {exc}")
    user_id = get_signed_cookie(request, "user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Sessão expirada.")
    tenant_context = resolve_context(request) if atendimento_multiempresa_enabled() else None
    if tenant_context and tenant_context.tenant_id is not None:
        with Session(engine) as session:
            company = session.exec(text("SELECT id, nome, logo_url FROM empresas_atendimento WHERE id = :tenant_id").bindparams(tenant_id=tenant_context.tenant_id)).first()
            if not company:
                raise HTTPException(status_code=404, detail="Empresa não encontrada")
            if nome.strip():
                session.exec(text("UPDATE empresas_atendimento SET nome = :nome WHERE id = :tenant_id").bindparams(nome=nome.strip()[:180], tenant_id=tenant_context.tenant_id))
            if logo and logo.filename:
                allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/svg+xml": ".svg"}
                ext = allowed.get(logo.content_type or "") or os.path.splitext(logo.filename)[1].lower()
                if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
                    raise HTTPException(status_code=400, detail="Use uma imagem JPG, PNG, WEBP, GIF ou SVG.")
                content = await logo.read()
                if len(content) > 5 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="A imagem deve ter no máximo 5 MB.")
                folder = os.path.join(_BASE_DIR, "public_html", "uploads")
                os.makedirs(folder, exist_ok=True)
                filename = f"empresa-{tenant_context.tenant_id}{ext}"
                with open(os.path.join(folder, filename), "wb") as output:
                    output.write(content)
                session.exec(text("UPDATE empresas_atendimento SET logo_url = :logo_url WHERE id = :tenant_id").bindparams(logo_url=f"uploads/{filename}?v={int(time.time())}", tenant_id=tenant_context.tenant_id))
            session.commit()
            company = session.exec(text("SELECT nome, logo_url FROM empresas_atendimento WHERE id = :tenant_id").bindparams(tenant_id=tenant_context.tenant_id)).first()
            return {"success": True, "nome": company[0], "logo_url": company[1] or ""}

    with Session(engine) as session:
        user = session.get(Usuario, int(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        if nome.strip():
            user.nome = nome.strip()[:120]
    if logo and logo.filename:
        allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/svg+xml": ".svg"}
        ext = allowed.get(logo.content_type or "") or os.path.splitext(logo.filename)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
            raise HTTPException(status_code=400, detail="Use uma imagem JPG, PNG, WEBP, GIF ou SVG.")
        content = await logo.read()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="A imagem deve ter no máximo 5 MB.")
        folder = os.path.join(_BASE_DIR, "public_html", "uploads")
        os.makedirs(folder, exist_ok=True)
        filename = f"perfil-{user.id}{ext}"
        with open(os.path.join(folder, filename), "wb") as output:
            output.write(content)
        user.foto_perfil_url = f"uploads/{filename}?v={int(time.time())}"
        session.add(user)
        session.commit()
        return {"success": True, "nome": user.nome or user.username, "logo_url": user.foto_perfil_url or ""}


@router.post("/identity/login-logo")
async def update_attendance_login_logo(
    request: Request,
    logo: Optional[UploadFile] = File(None),
):
    """Atualiza somente a logo exibida na tela inicial de login da Central."""
    if not _can_edit_identity(request):
        raise HTTPException(status_code=403, detail="Sem permissão para alterar a logo da tela de login.")
    if not logo or not logo.filename:
        raise HTTPException(status_code=400, detail="Selecione uma imagem para a tela de login.")

    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/svg+xml": ".svg"}
    ext = allowed.get(logo.content_type or "") or os.path.splitext(logo.filename)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
        raise HTTPException(status_code=400, detail="Use uma imagem JPG, PNG, WEBP, GIF ou SVG.")
    content = await logo.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="A imagem deve ter no máximo 5 MB.")

    folder = os.path.join(_BASE_DIR, "public_html", "uploads")
    os.makedirs(folder, exist_ok=True)
    filename = f"atendimento-login-logo{ext}"
    with open(os.path.join(folder, filename), "wb") as output:
        output.write(content)

    config = get_whatsapp_config()
    config["APP_ATENDIMENTO_LOGIN_LOGO_URL"] = f"uploads/{filename}?v={int(time.time())}"
    with open(CONFIG_FILE, "w", encoding="utf-8") as output:
        json.dump(config, output, indent=4, ensure_ascii=False)
        output.write("\n")
    return {"success": True, "logo_url": config["APP_ATENDIMENTO_LOGIN_LOGO_URL"]}


@router.get("/identity/me")
def get_attendance_identity(request: Request):
    user_id = get_signed_cookie(request, "user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Sessão expirada.")
    if atendimento_multiempresa_enabled():
        context = resolve_context(request)
        if context.tenant_id is not None:
            with Session(engine) as session:
                company = session.exec(text("SELECT nome, logo_url FROM empresas_atendimento WHERE id = :tenant_id").bindparams(tenant_id=context.tenant_id)).first()
            if not company:
                raise HTTPException(status_code=404, detail="Empresa não encontrada")
            return {"success": True, "nome": company[0], "foto_url": company[1] or ""}
    with Session(engine) as session:
        user = session.get(Usuario, int(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        return {"success": True, "nome": user.nome or user.username, "foto_url": user.foto_perfil_url or ""}


def get_whatsapp_webhook_target(config: dict) -> str:
    # IMPORTANTE: O webhook DEVE usar a URL interna do Docker (http://web:8000)
    # para garantir comunicação direta entre containers, sem depender da rede
    # externa do Windows, firewall, ou IP do host. As configurações de
    # WHATSAPP_WEBHOOK_TARGET e URL_ATENDIMENTO contêm IPs externos
    # (ex: 192.168.1.230:3001) que causam falhas intermitentes na entrega
    # de mensagens em tempo real.
    return "http://web:8000/api/whatsapp/webhook"


def _ensure_whatsapp_columns():
    global _whatsapp_columns_ready
    if _whatsapp_columns_ready:
        return
    statements = [
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_cliente VARCHAR(80)",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_instance VARCHAR(120)",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_typing_until TIMESTAMP NULL",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_typing_media BOOLEAN DEFAULT FALSE",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS responde_a_id INTEGER NULL",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS responde_a_usuario VARCHAR(255) NULL",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS responde_a_texto TEXT NULL",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS whatsapp_message_id VARCHAR(160) NULL",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS whatsapp_remote_jid VARCHAR(180) NULL",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS whatsapp_participant VARCHAR(180) NULL",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS whatsapp_status VARCHAR(20) DEFAULT 'sent'",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS reacao VARCHAR(32) NULL",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS reacao_quantidade INTEGER DEFAULT 0",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS reacao_detalhes TEXT NULL",
        "ALTER TABLE contatos_whatsapp ADD COLUMN IF NOT EXISTS status_interno VARCHAR(40) DEFAULT 'Normal'",
        """
        CREATE TABLE IF NOT EXISTS whatsapp_message_sync_state (
            instance_name VARCHAR(120) PRIMARY KEY,
            last_synced_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    _whatsapp_columns_ready = True


def get_default_whatsapp_instance(config: dict) -> Optional[str]:
    if not config:
        return None
    if config.get("WHATSAPP_DEFAULT_INSTANCE"):
        return config.get("WHATSAPP_DEFAULT_INSTANCE")

    instances = config.get("WHATSAPP_INSTANCES", [])
    if isinstance(instances, list) and instances:
        first = instances[0]
        if isinstance(first, dict):
            return first.get("instanceName")
        if isinstance(first, str):
            return first
    return None


def get_whatsapp_instances():
    config = get_whatsapp_config()
    raw_instances = config.get("WHATSAPP_INSTANCES", [])
    if not isinstance(raw_instances, list):
        raw_instances = []

    normalized = []
    for item in raw_instances:
        if isinstance(item, dict):
            instance_name = str(item.get("instanceName") or "").strip()
            label = str(item.get("label") or instance_name).strip()
            if instance_name:
                normalized.append({"instanceName": instance_name, "label": label})
        elif isinstance(item, str):
            instance_name = item.strip()
            if instance_name:
                normalized.append({"instanceName": instance_name, "label": instance_name})

    if "WHATSAPP_INSTANCES" not in config and not normalized:
        wa_url = config.get("WHATSAPP_WEBHOOK_URL", "")
        instance = None
        if "/message/sendText/" in wa_url:
            parts = wa_url.split("/message/sendText/")
            if len(parts) > 1 and parts[1]:
                instance = parts[1].split("?")[0]
        
        if instance:
            normalized.append({"instanceName": instance, "label": instance})

    default_instance = config.get("WHATSAPP_DEFAULT_INSTANCE") or (normalized[0]["instanceName"] if normalized else None)
    return normalized, default_instance


def resolve_configured_instance(instance: Optional[str] = None) -> Optional[str]:
    """Usa a instância padrão para atendimentos antigos cujo aparelho foi removido."""
    instances, default_instance = get_whatsapp_instances()
    valid = {item["instanceName"] for item in instances}
    if instance and instance in valid:
        return instance
    if instance:
        return str(instance).strip()
    return default_instance


def save_whatsapp_config(config: dict):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def _extract_connected_numbers(obj):
    """Percorre recursivamente o JSON retornado pela Evolution API e tenta
    extrair strings que pareçam números de telefone ou JIDs do WhatsApp.
    Retorna uma lista única de números no formato limpo (sem sufixos)."""
    found = set()
    def _walk(x):
        if x is None:
            return
        if isinstance(x, str):
            s = x.strip()
            # JID comum: 5511999999999@s.whatsapp.net ou com sufixos :12
            if "@" in s:
                left = s.split("@")[0]
                # remove eventual :XX
                left = left.split(":")[0]
                if len(left) >= 6 and any(ch.isdigit() for ch in left):
                    found.add(left)
            else:
                # número apenas dígitos (com ou sem +)
                digits = ''.join(ch for ch in s if ch.isdigit())
                if len(digits) >= 6:
                    found.add(digits)
            return
        if isinstance(x, dict):
            for v in x.values():
                _walk(v)
            return
        if isinstance(x, (list, tuple)):
            for item in x:
                _walk(item)
            return

    try:
        _walk(obj)
    except Exception:
        pass
    return sorted(found)


_instance_state_cache = {}  # {instance: (is_connected, expire_time)}
_instance_numbers_cache = {}  # {instance: (numbers, expire_time)}

def _instance_is_connected(instance: Optional[str]) -> bool:
    """Confirma o estado real da instância antes de aceitar mensagens do webhook.
    Usa cache curto de 15 segundos para evitar sobrecarregar a Evolution API
    e impedir que mensagens sejam descartadas por timeouts transitórios.
    """
    if not instance:
        return False
    now = time.time()
    cached = _instance_state_cache.get(instance)
    if cached and cached[1] > now:
        return cached[0]

    try:
        base_url, wa_token, resolved = get_evolution_api_endpoints(instance)
        if not base_url:
            return True
        headers = {"apikey": wa_token} if wa_token else {}
        response = requests.get(
            f"{base_url}/instance/connectionState/{resolved}",
            headers=headers,
            timeout=5,
        )
        if response.status_code == 200:
            data = response.json() or {}
            state = data.get("instance", {}).get("state") or data.get("state")
            is_conn = str(state or "").lower() in {"open", "connected"}
            _instance_state_cache[instance] = (is_conn, now + 15)
            return is_conn
        # Se status code != 200, usa o último estado em cache se houver
        if cached:
            return cached[0]
        return True
    except Exception as exc:
        print(f"[Webhook] Nao foi possivel confirmar estado da instancia '{instance}': {exc}")
        # Em caso de timeout/oscilação momentânea durante o webhook, não descarta a mensagem recebida
        return cached[0] if cached else True


def get_evolution_api_endpoints(instance_name: Optional[str] = None):
    config = get_whatsapp_config()
    wa_url = config.get("WHATSAPP_WEBHOOK_URL", "")
    wa_token = config.get("WHATSAPP_WEBHOOK_TOKEN", "")
    
    if not wa_url:
        return None, None, None
        
    instance = None
    base_url = wa_url.rstrip("/")
    
    # Se configurou a URL de envio direto, extrai a URL base e a instância
    if "/message/sendText/" in base_url:
        parts = base_url.split("/message/sendText/")
        base_url = parts[0]
        if len(parts) > 1 and parts[1]:
            instance = parts[1].split("?")[0]

    configured_instances, configured_default = get_whatsapp_instances()
    valid_map = {str(item.get("instanceName") or "").strip().lower(): item.get("instanceName") for item in configured_instances if item.get("instanceName")}
    valid_instances = {item.get("instanceName") for item in configured_instances if item.get("instanceName")}
    if instance_name and str(instance_name).strip().lower() in valid_map:
        instance = valid_map[str(instance_name).strip().lower()]
    elif instance_name and instance_name in valid_instances:
        instance = instance_name
    elif instance_name:
        try:
            with Session(engine) as session:
                tenant_instance = session.exec(text("""
                    SELECT instance_name
                    FROM instancias_whatsapp_tenant
                    WHERE LOWER(TRIM(instance_name)) = :instance_name AND ativa = TRUE
                    LIMIT 1
                """).bindparams(instance_name=str(instance_name).strip().lower())).first()
            if tenant_instance:
                instance = str(tenant_instance[0])
            else:
                instance = None
        except Exception:
            instance = None
    elif False and instance_name and configured_default:
        # Chamados antigos podem guardar o nome de uma instância removida.
        # Usa a instância atual para buscar fotos, grupos e contatos.
        instance = None
    elif not instance:
        instance = configured_default or get_default_whatsapp_instance(config)
            
    return base_url, wa_token, instance


_instance_uuid_map_cache = {"expires_at": 0.0, "map": {}}

def resolve_instance_name(raw_instance: Optional[str]) -> Optional[str]:
    """Resolve UUID de instância da Evolution API (v2) para o nome cadastrado na Central (ex: portal-de-acesso)."""
    if not raw_instance:
        return None
    raw_str = str(raw_instance).strip()
    configured_instances, _ = get_whatsapp_instances()
    valid_names = {str(item.get("instanceName")): str(item.get("instanceName")) for item in configured_instances if item.get("instanceName")}
    if raw_str in valid_names:
        return valid_names[raw_str]
    for name in valid_names:
        if name.lower() == raw_str.lower():
            return name
    
    # Se raw_str parece um UUID, consulta instâncias na Evolution API com cache de 5 minutos
    now = time.time()
    if _instance_uuid_map_cache["expires_at"] > now and raw_str in _instance_uuid_map_cache["map"]:
        return _instance_uuid_map_cache["map"][raw_str]

    try:
        base_url, wa_token, _ = get_evolution_api_endpoints()
        if base_url:
            headers = {"apikey": wa_token} if wa_token else {}
            resp = requests.get(f"{base_url}/instance/fetchInstances", headers=headers, timeout=3)
            if resp.status_code == 200:
                new_map = {}
                for inst_obj in resp.json() or []:
                    if isinstance(inst_obj, dict):
                        inst_id = str(inst_obj.get("id") or "").strip()
                        inst_name = str(inst_obj.get("name") or "").strip()
                        if inst_id and inst_name:
                            new_map[inst_id] = inst_name
                _instance_uuid_map_cache["map"] = new_map
                _instance_uuid_map_cache["expires_at"] = now + 300
                if raw_str in new_map:
                    return new_map[raw_str]
    except Exception as exc:
        print(f"[WhatsApp] Erro ao resolver UUID da instância: {exc}")

    return raw_str


def get_whatsapp_group_name(group_jid: str, instance_name: Optional[str] = None) -> Optional[str]:
    """Busca o nome atual de um grupo na Evolution API."""
    if not group_jid or not str(group_jid).lower().endswith("@g.us"):
        return None
    cache_key = (str(instance_name or ""), str(group_jid))
    cached = _group_name_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    try:
        base_url, wa_token, resolved = get_evolution_api_endpoints(instance_name)
        if not base_url or not resolved:
            return None
        response = requests.get(
            f"{base_url}/group/findGroupInfos/{resolved}",
            headers={"apikey": wa_token or ""},
            params={"groupJid": str(group_jid)},
            timeout=3,
        )
        if response.status_code != 200:
            return None
        result = response.json()
        objects = [result]
        if isinstance(result, dict):
            objects.extend(value for value in result.values() if isinstance(value, dict))
        for item in objects:
            for field in ("subject", "groupName", "name"):
                name = str(item.get(field) or "").strip()
                if name:
                    _group_name_cache[cache_key] = (time.time() + _GROUP_NAME_CACHE_TTL, name)
                    return name
    except Exception as exc:
        print(f"[WhatsApp] Não foi possível obter nome do grupo {group_jid}: {exc}")
    return None


def send_whatsapp_text(number: str, text: str, instance: Optional[str] = None) -> bool:
    instance = resolve_configured_instance(instance)
    base_url, wa_token, instance = get_evolution_api_endpoints(instance)
    if not base_url or not instance:
        print("[WhatsApp API] URL da API não configurada.")
        return False

    url = f"{base_url}/message/sendText/{instance}"
    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    payload = {"number": number, "text": text, "delay": 1200}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=8)
        if resp.status_code in [200, 201]:
            print(f"[WhatsApp API] Mensagem enviada para {number}")
            return True
        print(f"[WhatsApp API] Erro ao enviar: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"[WhatsApp API] Erro ao conectar com Evolution API: {e}")
    return False


def send_whatsapp_agenda_menu(number: str, welcome_text: str, instance: Optional[str] = None) -> bool:
    """Envia o menu da agenda como lista clicável, com fallback para texto."""
    resolved_instance = resolve_configured_instance(instance)
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(resolved_instance)
    if not base_url or not resolved_instance:
        return send_whatsapp_text(number, welcome_text, instance)

    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    payload = {
        "number": number,
        "title": "Menu de atendimento",
        "description": welcome_text,
        "buttonText": "Ver opções",
        "footerText": "Escolha uma opção para continuar",
        "sections": [{
            "title": "Opções",
            "rows": [
                {"title": "Agendar um horário", "description": "Escolha um dia e horário", "rowId": "1"},
                {"title": "Ver serviços e valores", "description": "Confira os serviços disponíveis", "rowId": "2"},
                {"title": "Consultar meu agendamento", "description": "Veja seus agendamentos ativos", "rowId": "3"},
                {"title": "Endereço e horários", "description": "Consulte localização e funcionamento", "rowId": "4"},
                {"title": "Falar com a recepção", "description": "Solicite atendimento humano", "rowId": "5"},
            ],
        }],
        "delay": 1200,
    }
    try:
        response = requests.post(f"{base_url}/message/sendList/{resolved_instance}", json=payload, headers=headers, timeout=8)
        if response.status_code in (200, 201):
            return True
        print(f"[AgendamentoBot] Lista interativa indisponível ({response.status_code}): {response.text[:500]}; usando texto.")
    except Exception as exc:
        print(f"[AgendamentoBot] Falha na lista interativa; usando texto: {exc}")
    return send_whatsapp_text(number, welcome_text, instance)


def send_whatsapp_agenda_slots(number: str, intro: str, days: list[dict], instance: Optional[str] = None) -> bool:
    """Envia os horários como opções selecionáveis e mantém fallback em texto."""
    resolved_instance = resolve_configured_instance(instance)
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(resolved_instance)
    if not base_url or not resolved_instance:
        return send_whatsapp_text(number, intro, instance)

    rows = []
    for day in days:
        for slot in day.get("slots", []):
            rows.append({
                "title": f"{day.get('label', day.get('data', ''))} — {slot}",
                "description": "Toque para selecionar este horário",
                "rowId": f"agenda_slot|{day.get('data')}|{slot}",
            })
    rows = rows[:10]
    if not rows:
        return send_whatsapp_text(number, intro, instance)

    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    payload = {
        "number": number,
        "title": "Escolha um horário",
        "description": intro,
        "buttonText": "Ver horários",
        "footerText": "Toque em um horário para selecionar",
        "sections": [{"title": "Horários disponíveis", "rows": rows}],
        "delay": 1200,
    }
    try:
        response = requests.post(
            f"{base_url}/message/sendList/{resolved_instance}",
            json=payload,
            headers=headers,
            timeout=8,
        )
        if response.status_code in (200, 201):
            return True
        print(f"[AgendamentoBot] Lista de horários indisponível ({response.status_code}): {response.text[:500]}; usando texto.")
    except Exception as exc:
        print(f"[AgendamentoBot] Falha na lista de horários; usando texto: {exc}")
    return send_whatsapp_text(number, intro, instance)


def _instance_connected_numbers(instance: Optional[str]) -> set[str]:
    """Obtém os números da própria instância para bloquear auto-mensagens.

    Algumas versões da Evolution omitem key.fromMe em mensagens enviadas pelo
    próprio aparelho. Nesse caso o remoteJid continua sendo o número conectado.
    """
    if not instance:
        return set()
    now = time.time()
    cached = _instance_numbers_cache.get(instance)
    if cached and cached[1] > now:
        return cached[0]
    numbers = set()
    try:
        base_url, wa_token, resolved = get_evolution_api_endpoints(instance)
        if not base_url:
            return numbers
        headers = {"apikey": wa_token} if wa_token else {}
        response = requests.get(
            f"{base_url}/instance/connectionState/{resolved}",
            headers=headers,
            timeout=3,
        )
        if response.status_code == 200:
            numbers.update(_extract_connected_numbers(response.json() or {}))
        if not numbers:
            response = requests.get(
                f"{base_url}/instance/fetchInstances",
                headers=headers,
                timeout=3,
            )
            if response.status_code == 200:
                for item in response.json() or []:
                    if isinstance(item, dict) and str(item.get("name") or "") == str(resolved):
                        numbers.update(_extract_connected_numbers({
                            "ownerJid": item.get("ownerJid"),
                            "number": item.get("number"),
                        }))
                        break
    except Exception as exc:
        print(f"[Webhook] Não foi possível consultar o número da instância '{instance}': {exc}")
    _instance_numbers_cache[instance] = (numbers, now + 30)
    return numbers


def _extract_sent_whatsapp_key(result: dict) -> dict:
    pending = [result]
    visited = set()
    while pending:
        current = pending.pop(0)
        if not isinstance(current, dict) or id(current) in visited:
            continue
        visited.add(id(current))
        key = current.get("key")
        if isinstance(key, dict) and key.get("id"):
            return key
        for field in ("data", "message", "result", "response"):
            nested = current.get(field)
            if isinstance(nested, dict):
                pending.append(nested)
            elif isinstance(nested, list):
                pending.extend(item for item in nested if isinstance(item, dict))
    return {}


def send_whatsapp_text_for_interaction(interaction_id: int, number: str, text: str, instance: Optional[str] = None, quoted: Optional[dict] = None) -> bool:
    instance = resolve_configured_instance(instance)
    """Envia a mensagem e salva o ID retornado pelo WhatsApp na interação local."""
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(instance)
    if not base_url or not resolved_instance:
        return False
    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    payload = {"number": number, "text": text, "delay": 1200}
    if quoted and quoted.get("id") and quoted.get("remoteJid"):
        payload["quoted"] = {"key": {
            "remoteJid": str(quoted["remoteJid"]),
            "fromMe": bool(quoted.get("fromMe", False)),
            "id": str(quoted["id"]),
        }}
    try:
        response = requests.post(
            f"{base_url}/message/sendText/{resolved_instance}",
            json=payload,
            headers=headers,
            timeout=8,
        )
        if response.status_code not in (200, 201):
            print(f"[WhatsApp API] Erro ao enviar mensagem vinculada: {response.status_code} - {response.text[:300]}")
            return False
        result = response.json() if response.content else {}
        key = _extract_sent_whatsapp_key(result)
        message_id = key.get("id") or result.get("messageId") or result.get("message_id")
        remote_jid = key.get("remoteJid") or (str(number) if "@" in str(number) else f"{number}@s.whatsapp.net")
        if message_id:
            with Session(engine) as session:
                interaction = session.get(ChamadoInteracao, interaction_id)
                if interaction:
                    interaction.whatsapp_message_id = str(message_id)
                    interaction.whatsapp_remote_jid = str(remote_jid)
                    session.add(interaction)
                    session.commit()
        print(f"[WhatsApp API] Mensagem vinculada enviada: {message_id or 'sem id'}")
        return True
    except Exception as exc:
        print(f"[WhatsApp API] Erro ao enviar mensagem vinculada: {exc}")
        return False


def edit_whatsapp_message(number: str, message_id: str, text: str, instance: Optional[str] = None, remote_jid: Optional[str] = None) -> bool:
    """Edita uma mensagem enviada pelo sistema na Evolution API."""
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(instance)
    if not base_url or not message_id or not text:
        return False
    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    target_jid = remote_jid or (str(number) if "@" in str(number) else f"{number}@s.whatsapp.net")
    payload = {"chat": target_jid, "messageId": str(message_id), "message": text}
    try:
        response = requests.post(f"{base_url}/message/edit", json=payload, headers=headers, timeout=8)
        if response.status_code in (200, 201):
            return True
        print(f"[WhatsApp API] Erro ao editar mensagem: {response.status_code} - {response.text[:300]}")
    except Exception as exc:
        print(f"[WhatsApp API] Erro ao editar mensagem: {exc}")
    return False


def send_whatsapp_reaction(number: str, message_id: str, reaction: str, instance: Optional[str] = None, remote_jid: Optional[str] = None, from_me: bool = False, participant: Optional[str] = None) -> tuple[bool, str]:
    instance = resolve_configured_instance(instance)
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(instance)
    if not base_url or not resolved_instance or not message_id:
        return False, "Evolution API nao configurada"
    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    target_jid = str(remote_jid or number or "")
    if "@" not in target_jid:
        target_jid = f"{target_jid}@s.whatsapp.net"
    key = {"remoteJid": target_jid, "fromMe": bool(from_me), "id": message_id}
    if participant:
        key["participant"] = str(participant)
    # O endpoint sendReaction da Evolution exige exatamente as propriedades
    # `key` e `reaction`. Os nomes reactionKey/reactionMessage geram HTTP 400.
    payload = {"key": key, "reaction": reaction}
    last_error = ""
    for attempt in range(2):
        try:
            # Reações em grupos podem ficar penduradas na Baileys quando o
            # participant é um @lid. O endpoint da API não precisa bloquear a
            # requisição por 15 segundos em cada combinação tentada abaixo.
            response = requests.post(f"{base_url}/message/sendReaction/{resolved_instance}", json=payload, headers=headers, timeout=8)
            if response.status_code in (200, 201):
                return True, ""
            last_error = f"Evolution API ({response.status_code}): {response.text[:300]}"
            print(f"[WhatsApp API] Erro ao enviar reacao (tentativa {attempt+1}): {last_error}")
        except requests.exceptions.Timeout:
            last_error = "Timeout ao conectar com a Evolution API"
            print(f"[WhatsApp API] Timeout ao enviar reação (tentativa {attempt+1})")
        except Exception as exc:
            last_error = f"Falha de comunicacao com a Evolution API: {exc}"
            print(f"[WhatsApp API] Erro ao enviar reação (tentativa {attempt+1}): {exc}")
        if attempt == 0:
            import time
            time.sleep(0.5)
    return False, last_error or "Falha de comunicacao com a Evolution API"


@router.post("/message/reaction")
def react_to_whatsapp_message(payload: dict = Body(...), request: Request = None):
    _require_atendimento_access(request)
    _ensure_whatsapp_columns()
    ticket_id = payload.get("ticket_id")
    message_id = str(payload.get("message_id") or "").strip()
    reaction = str(payload.get("reaction") or "").strip()
    # A Evolution API rejeita o variation selector usado por emojis como ❤️.
    # Mantemos o emoji, removendo apenas esse marcador invisível antes do envio.
    reaction = reaction.replace("\ufe0f", "")
    if not ticket_id or not message_id or not reaction:
        raise HTTPException(status_code=400, detail="Dados da reação incompletos")
    if len(reaction) > 16:
        raise HTTPException(status_code=400, detail="Reação inválida")
    try:
        local_message_id = int(message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Mensagem inválida")
    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado or not chamado.whatsapp_cliente:
            raise HTTPException(status_code=404, detail="Atendimento não encontrado")
        interaction = session.exec(select(ChamadoInteracao).where(ChamadoInteracao.id == local_message_id, ChamadoInteracao.chamado_id == ticket_id)).first()
        if not interaction or not interaction.whatsapp_message_id:
            raise HTTPException(status_code=400, detail="Esta mensagem não pode receber reação")
        # Mensagens recebidas usam fromMe=false; mensagens enviadas pelo
        # atendente usam fromMe=true. Há registros antigos sem essa marcação,
        # então tentamos as duas formas e os JIDs disponíveis no chamado.
        is_group_target = str(chamado.whatsapp_cliente or "").lower().endswith("@g.us")
        targets = []
        for candidate in (interaction.whatsapp_remote_jid, chamado.whatsapp_cliente):
            candidate = str(candidate or '').strip()
            # Em grupo, o remoteJid da chave da reação precisa ser o JID do
            # grupo. Nunca enviar a reação para o JID do participante.
            if is_group_target and not candidate.lower().endswith('@g.us'):
                continue
            if candidate and candidate not in targets:
                targets.append(candidate)
        ok = False
        reaction_error = ""
        is_group_target = is_group_target or any(
            str(target).lower().endswith("@g.us") for target in targets
        )
        participant_candidates = []
        if is_group_target and interaction.whatsapp_participant:
            participant_text = str(interaction.whatsapp_participant).strip()
            # Ignorar JIDs @lid — o WhatsApp/Baileys nao consegue resolver esse
            # formato e causa timeout indefinido na Evolution API.
            # Preserve @lid: em grupos ele pode ser o identificador exigido
            # pela Evolution para localizar o remetente original.
            if participant_text:
                participant_candidates.append(participant_text)
                if not participant_text.lower().endswith("@lid") and "@" not in participant_text and participant_text.isdigit():
                    participant_candidates.append(f"{participant_text}@s.whatsapp.net")
        if is_group_target:
            for candidate in (
                interaction.whatsapp_participant,
                getattr(interaction, "whatsapp_sender_phone", None),
            ):
                candidate = str(candidate or "").strip()
                if candidate and "@lid" not in candidate.lower() and candidate not in participant_candidates:
                    participant_candidates.append(candidate if "@" in candidate else f"{candidate}@s.whatsapp.net")
        # Fallback para mensagens históricas sem participante.
        participant_candidates.append(None)
        for target in targets:
            # Para mensagem recebida em grupo, a combinação correta é
            # fromMe=false + participant real. Só usa as alternativas antigas
            # quando não temos essa informação (mensagens históricas).
            combinations = []
            if is_group_target and participant_candidates and participant_candidates[0] is not None:
                combinations.append((False, participant_candidates[0]))
                combinations.append((False, None))
            else:
                combinations.extend((from_me, participant) for from_me in (False, True) for participant in participant_candidates)
            for from_me, participant in combinations:
                sent, error = send_whatsapp_reaction(
                    chamado.whatsapp_cliente,
                    interaction.whatsapp_message_id,
                    reaction,
                    chamado.whatsapp_instance,
                    target,
                    from_me,
                    participant,
                )
                reaction_error = error or reaction_error
                if sent:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            if reaction_error:
                raise HTTPException(status_code=502, detail=reaction_error)
            raise HTTPException(status_code=502, detail="Não foi possível enviar a reação ao WhatsApp")
        reaction_name = get_signed_cookie(request, "user_name", "Atendente") or "Atendente"
        reaction_people = [{"name": reaction_name, "emoji": reaction}]
        try:
            reaction_people = json.loads(interaction.reacao_detalhes or "[]")
            if not isinstance(reaction_people, list): reaction_people = []
        except Exception:
            reaction_people = []
        if interaction.reacao == reaction:
            if not any(str(item.get("name")) == reaction_name for item in reaction_people if isinstance(item, dict)):
                reaction_people.append({"name": reaction_name, "emoji": reaction})
            interaction.reacao_quantidade = max(len(reaction_people), (interaction.reacao_quantidade or 1))
        else:
            interaction.reacao = reaction
            interaction.reacao_quantidade = 1
            reaction_people = [{"name": reaction_name, "emoji": reaction}]
        interaction.reacao_detalhes = json.dumps(reaction_people, ensure_ascii=False)
        session.add(interaction)
        session.commit()
        return {"success": True, "reaction": reaction}


def send_whatsapp_media(number: str, media_base64: str, media_type: str, mime_type: str, filename: str = "arquivo", caption: str = "", instance: Optional[str] = None, interaction_id: Optional[int] = None) -> bool:
    """Envia imagem, áudio, vídeo ou documento pela Evolution API."""
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(instance)
    if not base_url or not resolved_instance:
        return False
    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    is_gif_playback = False
    if filename.lower().startswith("gif-") and filename.lower().endswith(".mp4"):
        # Frontend enviou versão MP4 do GIF para ativar a animação nativa do WhatsApp
        is_gif_playback = True
        media_type = "video"
        mime_type = "video/mp4"
    elif media_type == "gif" or mime_type.lower() == "image/gif" or filename.lower().endswith(".gif"):
        # Se enviarmos um binário .gif mas declararmos mime="video/mp4", o WhatsApp rejeita
        # silenciosamente porque a assinatura do arquivo não bate com o cabeçalho.
        # A forma segura de entregar sem conversão (ffmpeg) é enviá-lo como imagem/gif.
        media_type = "image"
        mime_type = "image/gif"
        if not filename.lower().endswith(".gif"):
            filename = os.path.splitext(filename)[0] + ".gif"

    payload = {
        "number": number,
        "mediatype": media_type,
        "mimetype": mime_type,
        "caption": caption or "",
        "media": media_base64,
        "fileName": filename,
    }
    if is_gif_playback:
        payload["options"] = {"gifPlayback": True}
    try:
        response = requests.post(
            f"{base_url}/message/sendMedia/{resolved_instance}",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if response.status_code in (200, 201):
            if interaction_id:
                result = response.json() if response.content else {}
                key = _extract_sent_whatsapp_key(result)
                message_id = key.get("id") or result.get("messageId") or result.get("message_id")
                if message_id:
                    remote_jid = key.get("remoteJid") or (str(number) if "@" in str(number) else f"{number}@s.whatsapp.net")
                    with Session(engine) as session:
                        interaction = session.get(ChamadoInteracao, interaction_id)
                        if interaction:
                            interaction.whatsapp_message_id = str(message_id)
                            interaction.whatsapp_remote_jid = str(remote_jid)
                            session.add(interaction)
                            session.commit()
                print(f"[WhatsApp API] Mídia vinculada enviada: {message_id or 'sem id'}")
            return True
        print(f"[WhatsApp API] Erro ao enviar mídia: {response.status_code} - {response.text[:300]}")
    except Exception as exc:
        print(f"[WhatsApp API] Erro ao enviar mídia: {exc}")
    return False


def _is_probably_thumbnail(candidate: str, media_kind: str = "") -> bool:
    if not isinstance(candidate, str):
        return False
    if candidate.startswith("http"):
        return "/thumbnail" in candidate.lower() or "/thumb" in candidate.lower() or "?size=" in candidate.lower()
    # Áudios curtos ou arquivos pequenos legítimos têm poucos KB em base64 e NÃO são thumbnails!
    if media_kind in ("audio", "document", "sticker"):
        return len(candidate) < 16
    if candidate.startswith("data:"):
        return len(candidate) < 20000
    return len(candidate) < 20000


def _find_base64(value, media_kind: str = ""):
    if isinstance(value, dict):
        # Se vier explicitamente o campo 'base64' (como na resposta do getBase64FromMediaMessage)
        if "base64" in value and isinstance(value["base64"], str) and len(value["base64"]) >= 16:
            return value["base64"]

        priority_keys = ("base64", "data", "fileBase64", "imageData", "binaryData", "url", "directPath", "mediaUrl", "imageUrl")
        fallback_keys = ("preview", "thumbnail", "jpegThumbnail")

        for key in priority_keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and (candidate.startswith("data:") or candidate.startswith("http") or len(candidate) >= 16):
                if not _is_probably_thumbnail(candidate, media_kind):
                    return candidate

        for key in fallback_keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and (candidate.startswith("data:") or candidate.startswith("http") or len(candidate) >= 16):
                if not _is_probably_thumbnail(candidate, media_kind):
                    return candidate

        for child in value.values():
            found = _find_base64(child, media_kind)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_base64(child, media_kind)
            if found:
                return found
    return None


def _download_media_from_url(url: str):
    try:
        response = requests.get(url, timeout=20)
        if response.ok:
            return response.content
    except Exception as exc:
        print(f"[Webhook] Falha ao baixar mídia por URL: {exc}")
    return None


def _save_incoming_media(message_obj: dict, message_key: dict, instance: str, media_kind: str, caption: str = ""):
    """Salva mídia recebida e retorna um marcador renderizável no frontend."""
    media_node = message_obj.get(f"{media_kind}Message", {}) or {}
    if not media_node and media_kind == "gif":
        media_node = message_obj.get("videoMessage", {}) or message_obj.get("imageMessage", {}) or {}
    raw_media = _find_base64(media_node, media_kind) or _find_base64(message_obj, media_kind)
    direct_url = None
    if raw_media and raw_media.startswith(("http://", "https://")):
        direct_url = raw_media
        raw_media = None
    if not raw_media and isinstance(media_node, dict):
        for key in ("url", "directPath", "mediaUrl", "imageUrl"):
            candidate = media_node.get(key)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                direct_url = candidate
                break
    if not raw_media and message_key.get("id"):
        base_url, wa_token, resolved = get_evolution_api_endpoints(instance)
        if base_url:
            try:
                payload = {
                    "message": {
                        "key": message_key,
                        "message": message_obj
                    }
                }
                # No Evolution API v2, getBase64FromMediaMessage é o endpoint padrão e mais confiável
                response = requests.post(
                    f"{base_url}/chat/getBase64FromMediaMessage/{resolved}",
                    headers={"apikey": wa_token, "Content-Type": "application/json"},
                    json=payload,
                    timeout=20,
                )
                if response.ok:
                    res_json = response.json() if response.content else {}
                    if isinstance(res_json, dict) and res_json.get("base64"):
                        raw_media = res_json["base64"]
                    else:
                        raw_media = _find_base64(res_json, media_kind)

                # Fallback para downloadMediaMessage caso getBase64 não resolva
                if not raw_media:
                    response_down = requests.post(
                        f"{base_url}/chat/downloadMediaMessage/{resolved}",
                        headers={"apikey": wa_token, "Content-Type": "application/json"},
                        json=payload,
                        timeout=15,
                    )
                    if response_down.ok:
                        try:
                            json_payload = response_down.json()
                            raw_media = _find_base64(json_payload, media_kind)
                        except Exception:
                            content_type = response_down.headers.get("content-type", "image/jpeg")
                            if response_down.content:
                                raw_media = f"data:{content_type};base64,{base64.b64encode(response_down.content).decode('utf-8')}"
            except Exception as exc:
                print(f"[Webhook] Falha ao obter mídia {media_kind}: {exc}")

    if not raw_media and media_kind == "document":
        original_filename = os.path.basename(str(media_node.get("fileName") or media_node.get("filename") or "Documento").strip())
        try:
            file_size = int(media_node.get("fileLength") or media_node.get("fileSize") or media_node.get("size") or 0)
        except (TypeError, ValueError):
            file_size = 0
        return json.dumps({
            "__wa_media__": True,
            "type": "document",
            "mime": media_node.get("mimetype") or "application/octet-stream",
            "filename": original_filename,
            "size": file_size,
            "caption": caption,
        }, ensure_ascii=False)
    if not raw_media:
        return f"[Mídia não disponível: {media_kind}]"

    try:
        default_mime = {
            "audio": "audio/ogg",
            "video": "video/mp4",
            "gif": "image/gif",
            "sticker": "image/webp",
            "document": "application/octet-stream",
        }.get(media_kind, "image/jpeg")
        mime = media_node.get("mimetype") or default_mime
        original_filename = os.path.basename(str(media_node.get("fileName") or media_node.get("filename") or "").strip())
        extension = os.path.splitext(original_filename)[1].lstrip(".")
        if not extension:
            if media_kind == "audio":
                extension = "ogg"
            elif media_kind in ("video", "gif") and "video" in mime:
                extension = "mp4"
            elif "pdf" in mime:
                extension = "pdf"
            elif "gif" in mime:
                extension = "gif"
            elif "webp" in mime:
                extension = "webp"
            else:
                extension = "jpg" if media_kind != "document" else "bin"
        if raw_media.startswith("data:"):
            header, raw_media = raw_media.split(",", 1)
            mime = header.split(";")[0].replace("data:", "") or mime
            if not original_filename:
                extension = mime.split("/")[-1].replace("jpeg", "jpg")
        raw_media = re.sub(r"\s+", "", raw_media)
        binary = base64.b64decode(raw_media)
        media_dir = os.path.join(_BASE_DIR, "public_html", "uploads", "whatsapp_media")
        os.makedirs(media_dir, exist_ok=True)
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(message_key.get("id") or int(time.time())))
        stored_filename = f"{safe_id}.{extension}"
        with open(os.path.join(media_dir, stored_filename), "wb") as output:
            output.write(binary)
        return json.dumps({"__wa_media__": True, "type": media_kind, "url": f"/uploads/whatsapp_media/{stored_filename}", "mime": mime, "filename": original_filename or stored_filename, "size": len(binary), "caption": caption}, ensure_ascii=False)
    except Exception as exc:
        print(f"[Webhook] Falha ao salvar mídia {media_kind}: {exc}")
        return f"[Mídia recebida: {media_kind}]"


def _get_user(request: Request):
    name = get_signed_cookie(request, "user_name", "Desconhecido")
    role = get_signed_cookie(request, "user_role", "operator")
    return name, role


def _can_manage_atendimento(request: Request, role: str = "") -> bool:
    """Perfis de coordenação podem visualizar e distribuir a fila."""
    normalized = (role or get_signed_cookie(request, "user_role", "operator") or "").strip().lower()
    if normalized in {"admin", "gestor", "gerente", "supervisor", "recepcao", "recepção", "recepcionista"}:
        return True
    try:
        raw_perms = get_signed_cookie(request, "user_perms", "[]") or "[]"
        perms = normalize_permissions(json.loads(raw_perms))
        return "Transferir Atendimento" in perms or "Gerenciar Atendimento" in perms
    except Exception:
        return False


def _is_reception_role(role: str = "") -> bool:
    normalized = (role or "").strip().lower()
    return normalized in {"recepcao", "recepção", "recepcionista"}


def _require_atendimento_access(request: Request):
    """Protege as operações do módulo sem bloquear o webhook da Evolution API."""
    user_id = get_signed_cookie(request, "user_id")
    user_role = get_signed_cookie(request, "user_role")
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if user_role == "admin":
        return
    if _is_reception_role(user_role):
        return

    try:
        raw_perms = get_signed_cookie(request, "user_perms", "[]") or "[]"
        perms = normalize_permissions(json.loads(raw_perms))
    except Exception:
        perms = []

    if "Atendimento" not in perms and "Suporte" not in perms:
        raise HTTPException(status_code=403, detail="Acesso negado: permissão 'Atendimento' ou 'Suporte' necessária")


def _require_atendimento_access(request: Request):
    """Permite a Central somente ao admin principal e contas da Central."""
    user_id = get_signed_cookie(request, "user_id")
    role = get_signed_cookie(request, "user_role")
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if role == "admin":
        return
    if role != "cliente_atendimento":
        raise HTTPException(status_code=403, detail="Este usuário não possui acesso à Central de Atendimento")
    resolve_context(request)


def _require_admin(request: Request):
    user_id = get_signed_cookie(request, "user_id")
    user_role = get_signed_cookie(request, "user_role")
    if user_id:
        try:
            with Session(engine) as session:
                user = session.get(Usuario, int(user_id))
            user_role = user.role if user else user_role
        except (TypeError, ValueError):
            pass
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso exclusivo para administradores")


def is_tauri_admin(request: Request) -> bool:
    """Retorna se a sessão atual é uma das contas autorizadas no Tauri."""
    is_tauri = request.cookies.get("central_atendimento_tauri") == "1" or request.query_params.get("desktop") == "1"
    if not is_tauri:
        return False
    user_id = get_signed_cookie(request, "user_id")
    if not user_id:
        return False
    try:
        with Session(engine) as session:
            user = session.get(Usuario, int(user_id))
        if not user:
            return False
        identities = {str(user.username or "").strip().lower(), str(user.email or "").strip().lower()}
        if identities & {item.lower() for item in TAURI_ALLOWED_USERS}:
            return True

        # Administrador da empresa também pode vincular o aparelho da própria empresa.
        if get_signed_cookie(request, "user_role") == "cliente_atendimento":
            try:
                context = resolve_context(request)
                if context.tenant_id is None:
                    return False
                with Session(engine) as session:
                    row = session.exec(text("""
                        SELECT 1
                        FROM usuarios_empresas_atendimento
                        WHERE empresa_atendimento_id = :tenant_id
                          AND usuario_id = :user_id
                          AND papel = 'tenant_admin'
                          AND ativo = TRUE
                    """).bindparams(tenant_id=context.tenant_id, user_id=int(user_id))).first()
                return bool(row)
            except (HTTPException, TypeError, ValueError):
                return False
        return False
    except (TypeError, ValueError):
        return False


def _require_tauri_admin(request: Request):
    if not is_tauri_admin(request):
        raise HTTPException(status_code=403, detail="Usuário não autorizado para conectar aparelhos no Tauri")


@router.get("/instances")
def list_whatsapp_instances(request: Request):
    _require_atendimento_access(request)
    instances, default_instance = get_whatsapp_instances()
    if atendimento_multiempresa_enabled() and get_signed_cookie(request, "user_role") != "admin":
        context = resolve_context(request)
        with Session(engine) as session:
            rows = session.exec(text("""
                SELECT instance_name, label, padrao
                FROM instancias_whatsapp_tenant
                WHERE empresa_atendimento_id = :tenant_id AND ativa = TRUE
                ORDER BY padrao DESC, label, instance_name
            """).bindparams(tenant_id=context.tenant_id)).all()
        instances = [{"instanceName": str(row[0]), "label": str(row[1] or row[0])} for row in rows]
        default_row = next((row for row in rows if bool(row[2])), None)
        default_instance = str(default_row[0]) if default_row else (instances[0]["instanceName"] if instances else None)

    # Para cada instância, tenta consultar o estado atual na Evolution API
    detailed = []
    connected_count = 0
    for inst in instances:
        inst_name = inst.get("instanceName")
        label = inst.get("label")
        state = "unknown"
        connected_numbers = []
        try:
            base_url, wa_token, resolved = get_evolution_api_endpoints(inst_name)
            if base_url:
                headers = {}
                if wa_token:
                    headers["apikey"] = wa_token
                try:
                    resp = requests.get(f"{base_url}/instance/connectionState/{resolved}", headers=headers, timeout=3)
                    if resp.status_code == 200:
                        data = resp.json()
                        state = data.get("instance", {}).get("state") or data.get("state", "disconnected")
                        # Tenta extrair números conectados da resposta
                        connected_numbers = _extract_connected_numbers(data)
                    elif resp.status_code in [404, 400]:
                        state = "not_created"
                    else:
                        state = "error"
                except Exception:
                    state = "error"
                if not connected_numbers:
                    try:
                        instances_resp = requests.get(f"{base_url}/instance/fetchInstances", headers=headers, timeout=3)
                        if instances_resp.status_code == 200:
                            for remote_instance in instances_resp.json() or []:
                                if not isinstance(remote_instance, dict):
                                    continue
                                if str(remote_instance.get("name") or "") != str(resolved):
                                    continue
                                connected_numbers = _extract_connected_numbers({
                                    "ownerJid": remote_instance.get("ownerJid"),
                                    "number": remote_instance.get("number"),
                                })
                                break
                    except Exception:
                        pass
        except Exception:
            state = "error"

        if isinstance(state, str) and state.lower() in ("open", "connected", "connected"):
            connected_count += 1

        detailed.append({
            "instanceName": inst_name,
            "label": label,
            "state": state,
            "connected_numbers": connected_numbers,
            "connected_count": len(connected_numbers)
        })

    return {
        "instances": detailed,
        "default_instance": default_instance,
        "auto_create_tickets": bool(get_whatsapp_config().get("WHATSAPP_AUTO_CREATE_TICKETS", True)),
        "show_groups": bool(get_whatsapp_config().get("WHATSAPP_SHOW_GROUPS", False)),
        "chat_background_color": get_whatsapp_config().get("WHATSAPP_CHAT_BACKGROUND_COLOR", "#0b141a"),
        "chat_background_image": get_whatsapp_config().get("WHATSAPP_CHAT_BACKGROUND_IMAGE", ""),
        "total": len(detailed),
        "connected": connected_count,
        "instance_access": get_whatsapp_config().get("WHATSAPP_INSTANCE_ACCESS", {}) or {},
        "instance_colors": get_whatsapp_config().get("WHATSAPP_INSTANCE_COLORS", {}) or {}
    }


@router.post("/instances/access")
def save_whatsapp_instance_access(request: Request, payload: dict = Body(...)):
    _require_admin(request)
    config = get_whatsapp_config()
    valid = {item["instanceName"] for item in get_whatsapp_instances()[0]}
    raw_access = payload.get("access", {}) or {}
    access = {}
    for instance, users in raw_access.items():
        if str(instance) in valid and isinstance(users, list):
            clean = sorted({str(user).strip() for user in users if str(user).strip()})
            if clean:
                access[str(instance)] = clean
    config["WHATSAPP_INSTANCE_ACCESS"] = access
    save_whatsapp_config(config)
    return {"success": True, "access": access}


@router.post("/instances/colors")
def save_whatsapp_instance_colors(request: Request, payload: dict = Body(...)):
    _require_admin(request)
    config = get_whatsapp_config()
    valid = {item["instanceName"] for item in get_whatsapp_instances()[0]}
    raw_colors = payload.get("colors", {}) or {}
    colors = {}
    for instance, color in raw_colors.items():
        value = str(color or "").strip()
        if str(instance) in valid and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            colors[str(instance)] = value
    config["WHATSAPP_INSTANCE_COLORS"] = colors
    save_whatsapp_config(config)
    return {"success": True, "colors": colors}


@router.post("/instances/save")
def save_whatsapp_instances(request: Request, payload: dict = Body(...)):
    if get_signed_cookie(request, "user_role") == "admin":
        _require_admin(request)
    else:
        _require_tauri_admin(request)

    raw_instances = payload.get("instances", [])
    default_instance = str(payload.get("default_instance", "") or "").strip()
    print(f"[WhatsApp] Salvando instâncias: {raw_instances} default={default_instance}")

    instances = []
    for item in raw_instances:
        if isinstance(item, dict):
            instance_name = str(item.get("instanceName") or "").strip()
            label = str(item.get("label") or instance_name).strip()
            if instance_name:
                instances.append({"instanceName": instance_name, "label": label})
        elif isinstance(item, str):
            instance_name = item.strip()
            if instance_name:
                instances.append({"instanceName": instance_name, "label": instance_name})

    if default_instance and not any(i["instanceName"] == default_instance for i in instances):
        default_instance = ""

    if get_signed_cookie(request, "user_role") != "admin":
        context = resolve_context(request)
        if context.tenant_id is None:
            raise HTTPException(status_code=403, detail="Empresa não determinada para esta conexão.")
        with Session(engine) as session:
            for item in instances:
                existing = session.exec(text("""
                    SELECT id FROM instancias_whatsapp_tenant
                    WHERE empresa_atendimento_id = :tenant_id
                      AND LOWER(TRIM(instance_name)) = :instance_name
                """).bindparams(
                    tenant_id=context.tenant_id,
                    instance_name=item["instanceName"].lower(),
                )).first()
                if existing:
                    session.exec(text("""
                        UPDATE instancias_whatsapp_tenant
                        SET label = :label, ativa = TRUE
                        WHERE id = :id
                    """).bindparams(label=item["label"], id=existing[0]))
                else:
                    session.exec(text("""
                        INSERT INTO instancias_whatsapp_tenant
                            (empresa_atendimento_id, instance_name, label, padrao, ativa)
                        VALUES (:tenant_id, :instance_name, :label, :is_default, TRUE)
                    """).bindparams(
                        tenant_id=context.tenant_id,
                        instance_name=item["instanceName"],
                        label=item["label"],
                        is_default=item["instanceName"] == default_instance,
                    ))
            keep_names = {item["instanceName"].lower() for item in instances}
            tenant_rows = session.exec(text("""
                SELECT id, instance_name
                FROM instancias_whatsapp_tenant
                WHERE empresa_atendimento_id = :tenant_id AND ativa = TRUE
            """).bindparams(tenant_id=context.tenant_id)).all()
            for row in tenant_rows:
                if str(row[1]).lower() not in keep_names:
                    session.exec(text("""
                        UPDATE instancias_whatsapp_tenant
                        SET ativa = FALSE, padrao = FALSE
                        WHERE id = :id
                    """).bindparams(id=row[0]))
            session.exec(text("""
                UPDATE instancias_whatsapp_tenant
                SET padrao = (instance_name = :default_instance)
                WHERE empresa_atendimento_id = :tenant_id AND ativa = TRUE
            """).bindparams(tenant_id=context.tenant_id, default_instance=default_instance))
            session.commit()
        return {"success": True, "instances": instances, "default_instance": default_instance}

    config = get_whatsapp_config()
    config["WHATSAPP_INSTANCES"] = instances
    if default_instance:
        config["WHATSAPP_DEFAULT_INSTANCE"] = default_instance
    elif instances:
        config["WHATSAPP_DEFAULT_INSTANCE"] = instances[0]["instanceName"]
    else:
        config.pop("WHATSAPP_DEFAULT_INSTANCE", None)
    save_whatsapp_config(config)
    if "auto_create_tickets" in payload:
        config["WHATSAPP_AUTO_CREATE_TICKETS"] = bool(payload.get("auto_create_tickets"))
        save_whatsapp_config(config)
    return {"success": True, "instances": instances, "default_instance": config.get("WHATSAPP_DEFAULT_INSTANCE"), "auto_create_tickets": bool(config.get("WHATSAPP_AUTO_CREATE_TICKETS", True)), "show_groups": bool(config.get("WHATSAPP_SHOW_GROUPS", False))}


@router.post("/settings/auto-tickets")
def save_auto_ticket_setting(request: Request, payload: dict = Body(...)):
    _require_admin(request)
    config = get_whatsapp_config()
    config["WHATSAPP_AUTO_CREATE_TICKETS"] = bool(payload.get("enabled", True))
    save_whatsapp_config(config)
    return {"success": True, "enabled": config["WHATSAPP_AUTO_CREATE_TICKETS"]}


@router.post("/settings/groups")
def save_groups_setting(request: Request, payload: dict = Body(...)):
    _require_admin(request)
    config = get_whatsapp_config()
    config["WHATSAPP_SHOW_GROUPS"] = bool(payload.get("enabled", False))
    save_whatsapp_config(config)
    return {"success": True, "enabled": config["WHATSAPP_SHOW_GROUPS"]}


@router.post("/settings/chat-background")
def save_chat_background_setting(request: Request, payload: dict = Body(...)):
    _require_admin(request)
    color = str(payload.get("color") or "#0b141a").strip()
    image = str(payload.get("image") or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise HTTPException(status_code=400, detail="Cor de fundo inválida")
    if image and not image.lower().startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="A imagem deve usar uma URL http ou https")
    config = get_whatsapp_config()
    config["WHATSAPP_CHAT_BACKGROUND_COLOR"] = color
    config["WHATSAPP_CHAT_BACKGROUND_IMAGE"] = image
    save_whatsapp_config(config)
    return {"success": True, "color": color, "image": image}


@router.post("/settings/chat-background/upload")
async def upload_chat_background(request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Selecione uma imagem")
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Use uma imagem JPG, PNG, WEBP ou GIF")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="A imagem está vazia")
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="A imagem deve ter no máximo 8 MB")

    extension = os.path.splitext(file.filename)[1].lower() or ".img"
    upload_dir = os.path.join(_BASE_DIR, "public_html", "uploads", "chat_background")
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"chat-bg-{uuid.uuid4().hex}{extension}"
    stored_path = os.path.join(upload_dir, stored_name)
    with open(stored_path, "wb") as output:
        output.write(content)

    config = get_whatsapp_config()
    config["WHATSAPP_CHAT_BACKGROUND_IMAGE"] = f"/uploads/chat_background/{stored_name}"
    save_whatsapp_config(config)
    return {"success": True, "image": config["WHATSAPP_CHAT_BACKGROUND_IMAGE"]}


@router.post("/schema/upgrade")
def upgrade_whatsapp_schema(request: Request):
    _require_admin(request)
    from sqlalchemy import text

    statements = [
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_cliente VARCHAR(80)",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_instance VARCHAR(120)"
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    return {"success": True, "applied": len(statements)}


# ─── Templates / Respostas Rápidas (salvas em config.json) ─────────────────

@router.get("/templates")
def list_templates(request: Request):
    _require_atendimento_access(request)
    user_name, user_role = _get_user(request)
    config = get_whatsapp_config()
    templates = config.get("WHATSAPP_TEMPLATES", [])
    # retorna todos, mas marca propriedade `editable` para controle no frontend
    out = []
    for t in templates:
        out.append({
            "id": t.get("id"),
            "title": t.get("title"),
            "body": t.get("body"),
            "owner": t.get("owner"),
            "editable": (user_role == "admin" or t.get("owner") == user_name)
        })
    return out


@router.post("/templates")
def create_template(request: Request, payload: dict = Body(...)):
    _require_atendimento_access(request)
    user_name, user_role = _get_user(request)
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", "")).strip()
    if not title or not body:
        raise HTTPException(status_code=400, detail="title and body are required")

    config = get_whatsapp_config()
    templates = config.get("WHATSAPP_TEMPLATES", [])
    # assign incremental id
    next_id = 1
    if templates:
        try:
            next_id = max(int(t.get("id", 0)) for t in templates) + 1
        except Exception:
            next_id = len(templates) + 1

    newt = {"id": next_id, "title": title, "body": body, "owner": user_name}
    templates.append(newt)
    config["WHATSAPP_TEMPLATES"] = templates
    save_whatsapp_config(config)
    return {"success": True, "template": newt}


@router.put("/templates/{template_id}")
def update_template(template_id: int, request: Request, payload: dict = Body(...)):
    _require_atendimento_access(request)
    user_name, user_role = _get_user(request)
    config = get_whatsapp_config()
    templates = config.get("WHATSAPP_TEMPLATES", [])
    found = None
    for t in templates:
        if int(t.get("id")) == int(template_id):
            found = t
            break
    if not found:
        raise HTTPException(status_code=404, detail="Template not found")
    if user_role != "admin" and found.get("owner") != user_name:
        raise HTTPException(status_code=403, detail="Not allowed to edit this template")

    title = payload.get("title")
    body = payload.get("body")
    if title is not None:
        found["title"] = str(title)
    if body is not None:
        found["body"] = str(body)

    config["WHATSAPP_TEMPLATES"] = templates
    save_whatsapp_config(config)
    return {"success": True, "template": found}


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, request: Request):
    _require_atendimento_access(request)
    user_name, user_role = _get_user(request)
    config = get_whatsapp_config()
    templates = config.get("WHATSAPP_TEMPLATES", [])
    newlist = []
    deleted = None
    for t in templates:
        if int(t.get("id")) == int(template_id):
            deleted = t
            continue
        newlist.append(t)

    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    if user_role != "admin" and deleted.get("owner") != user_name:
        raise HTTPException(status_code=403, detail="Not allowed to delete this template")

    config["WHATSAPP_TEMPLATES"] = newlist
    save_whatsapp_config(config)
    return {"success": True}


@router.get("/contact")
def get_contact_details(ticket_id: Optional[int] = None, request: Request = None):
    """Retorna detalhes do contato e últimas interações para exibir no painel lateral.
    Pode receber `ticket_id` (preferível) ou `phone` em versão futura.
    """
    _require_atendimento_access(request)
    _ensure_whatsapp_columns()
    if not ticket_id:
        raise HTTPException(status_code=400, detail="ticket_id é obrigatório")

    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        profile_picture = None
        if chamado and chamado.whatsapp_cliente:
            try:
                base_url, wa_token, resolved = get_evolution_api_endpoints(chamado.whatsapp_instance)
                if base_url:
                    # Somente consulta findContacts se for um identificador interno @lid ainda não resolvido
                    if "@lid" in str(chamado.whatsapp_cliente).lower():
                        response = requests.post(
                            f"{base_url}/chat/findContacts/{resolved}",
                            headers={"apikey": wa_token or "", "Content-Type": "application/json"},
                            json={"where": {}, "take": 500, "skip": 0, "orderBy": {}},
                            timeout=3,
                        )
                        payload = response.json() if response.ok else []
                        contacts = payload if isinstance(payload, list) else (payload.get("contacts") or []) if isinstance(payload, dict) else []
                        lid = str(chamado.whatsapp_cliente).split("@")[0]
                        match = next((item for item in contacts if isinstance(item, dict) and str(item.get("id") or item.get("remoteJid") or "").split("@")[0] == lid), None)
                        if match:
                            profile_picture = match.get("profilePictureUrl") or match.get("profilePicUrl") or match.get("profile_picture")
                            real_number = _real_contact_number(match)
                            if real_number and real_number != chamado.whatsapp_cliente:
                                chamado.whatsapp_cliente = real_number
                                session.add(chamado)
                                session.commit()
                    if not profile_picture:
                        profile_picture = _fetch_profile_picture_url(base_url, wa_token, resolved, chamado.whatsapp_cliente)
            except Exception:
                pass
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")

        contato = None
        if chamado.whatsapp_cliente:
            contato = session.exec(
                select(ContatoWhatsApp).where(ContatoWhatsApp.numero == chamado.whatsapp_cliente)
            ).first()

        # Busca últimas interações
        interacoes_stmt = select(ChamadoInteracao).where(ChamadoInteracao.chamado_id == chamado.id).order_by(desc(ChamadoInteracao.data_hora)).limit(20)
        interacoes = session.exec(interacoes_stmt).all()

        last_messages = []
        for it in reversed(interacoes):
            last_messages.append({
                "id": it.id,
                "usuario": it.usuario,
                "mensagem": it.mensagem,
                "data_hora": _display_datetime(it.data_hora).strftime("%d/%m/%Y %H:%M:%S")
            })

        previous_tickets = []
        if chamado.whatsapp_cliente:
            previous_stmt = select(Chamado).where(
                Chamado.whatsapp_cliente == chamado.whatsapp_cliente,
                Chamado.id != chamado.id,
            ).order_by(desc(Chamado.data_abertura)).limit(8)
            previous = session.exec(previous_stmt).all()
            previous_tickets = [
                {
                    "id": item.id,
                    "titulo": item.titulo,
                    "status": item.status,
            "data_abertura": _display_datetime(item.data_abertura).strftime("%d/%m/%Y %H:%M"),
                }
                for item in previous
            ]

        return {
            "ticket_id": chamado.id,
            "usuario": chamado.usuario,
            "phone": chamado.whatsapp_cliente,
            "instance": chamado.whatsapp_instance,
            "status": chamado.status,
            "prioridade": chamado.prioridade,
            "categoria": chamado.categoria,
            "data_abertura": _display_datetime(chamado.data_abertura).strftime("%d/%m/%Y %H:%M:%S"),
            "assigned_user": chamado.assigned_user,
            "profile_picture": profile_picture,
            "nota_interna": chamado.nota_tecnica or "",
            "status_interno": (contato.status_interno if contato and contato.status_interno else "Normal"),
            "last_messages": last_messages,
            "previous_tickets": previous_tickets
        }


@router.get("/contact/profile-picture")
def get_contact_profile_picture(number: str, request: Request, instance: Optional[str] = None):
    """Entrega a foto pelo backend com cache de bytes e headers HTTP 24h para navegação ultra-rápida."""
    _require_atendimento_access(request)
    normalized = _normalize_contact_number(number) or str(number or "").strip()
    resolved_inst = resolve_instance_name(instance) or instance or ""
    bytes_cache_key = f"{resolved_inst}:{normalized}"
    now = time.time()

    # Se já temos os bytes da foto em memória, entrega instantaneamente (0.1ms)
    if bytes_cache_key in _PROFILE_PIC_BYTES_CACHE:
        cached_content, cached_type, cached_time = _PROFILE_PIC_BYTES_CACHE[bytes_cache_key]
        if now - cached_time < 86400:  # 24 horas
            return Response(
                content=cached_content,
                media_type=cached_type,
                headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"},
            )

    base_url, wa_token, resolved = get_evolution_api_endpoints(instance)
    picture_url = _fetch_profile_picture_url(base_url, wa_token, resolved, number)
    if not picture_url:
        raise HTTPException(
            status_code=404,
            detail="Foto não disponível",
            headers={"Cache-Control": "public, max-age=300"},
        )
    try:
        picture_response = requests.get(picture_url, timeout=5)
        if not picture_response.ok or not picture_response.content:
            raise HTTPException(
                status_code=404,
                detail="Foto não disponível",
                headers={"Cache-Control": "public, max-age=300"},
            )
        media_type = picture_response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
        if not media_type.startswith("image/"):
            media_type = "image/jpeg"

        # Guarda no cache LRU em memória (limite de 1000 fotos para evitar gasto excessivo de RAM)
        if len(_PROFILE_PIC_BYTES_CACHE) > 1000:
            oldest_keys = sorted(_PROFILE_PIC_BYTES_CACHE.keys(), key=lambda k: _PROFILE_PIC_BYTES_CACHE[k][2])[:200]
            for k in oldest_keys:
                _PROFILE_PIC_BYTES_CACHE.pop(k, None)
        _PROFILE_PIC_BYTES_CACHE[bytes_cache_key] = (picture_response.content, media_type, now)

        return Response(
            content=picture_response.content,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail="Foto não disponível",
            headers={"Cache-Control": "public, max-age=60"},
        )


@router.post("/contact/note")
def update_contact_note(payload: dict = Body(...), request: Request = None):
    _require_atendimento_access(request)
    ticket_id = payload.get("ticket_id")
    note = payload.get("note", "")
    if not ticket_id:
        raise HTTPException(status_code=400, detail="ticket_id é obrigatório")

    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")

        # Reutilizamos `nota_tecnica` como campo de nota interna para agora
        chamado.nota_tecnica = note
        session.commit()
        return {"success": True, "ticket_id": ticket_id}


@router.post("/contact/status")
def update_contact_status(payload: dict = Body(...), request: Request = None):
    _require_atendimento_access(request)
    _ensure_whatsapp_columns()
    ticket_id = payload.get("ticket_id")
    status = str(payload.get("status") or "Normal").strip()
    allowed_statuses = {"Normal", "Aguardando retorno", "Em atendimento", "VIP", "Bloqueado", "Prioridade"}
    if status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Status interno inválido")
    if not ticket_id:
        raise HTTPException(status_code=400, detail="ticket_id é obrigatório")

    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")
        if not chamado.whatsapp_cliente:
            raise HTTPException(status_code=400, detail="Este chamado não possui contato WhatsApp")

        contato = session.exec(
            select(ContatoWhatsApp).where(ContatoWhatsApp.numero == chamado.whatsapp_cliente)
        ).first()
        if not contato:
            contato = ContatoWhatsApp(
                nome=chamado.usuario or "Cliente",
                numero=chamado.whatsapp_cliente,
                whatsapp_instance=chamado.whatsapp_instance,
                empresa_atendimento_id=chamado.empresa_atendimento_id,
            )
        contato.status_interno = status
        session.add(contato)
        session.commit()
        return {"success": True, "status_interno": status}


@router.post("/ticket/update")
def update_whatsapp_ticket(payload: dict = Body(...), request: Request = None):
    """Atualiza campos operacionais do chamado na Central de Atendimento."""
    _require_atendimento_access(request)
    ticket_id = payload.get("ticket_id") or payload.get("id")
    if not ticket_id:
        raise HTTPException(status_code=400, detail="ticket_id é obrigatório")

    allowed_priorities = {"Baixa", "Media", "Alta"}
    allowed_categories = {"WhatsApp", "Impressora", "Rede/Internet", "Computador/Hardware", "Outros"}

    with Session(engine) as session:
        chamado = session.get(Chamado, int(ticket_id))
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")
        if chamado.origem != "WhatsApp":
            raise HTTPException(status_code=400, detail="Chamado não pertence ao WhatsApp")

        if "prioridade" in payload:
            prioridade = str(payload.get("prioridade") or "").strip()
            if prioridade not in allowed_priorities:
                raise HTTPException(status_code=400, detail="Prioridade inválida")
            chamado.prioridade = prioridade

        if "categoria" in payload:
            categoria = str(payload.get("categoria") or "").strip()
            if categoria not in allowed_categories:
                raise HTTPException(status_code=400, detail="Categoria inválida")
            chamado.categoria = categoria

        session.add(chamado)
        session.commit()
        session.refresh(chamado)

        return {
            "success": True,
            "ticket_id": chamado.id,
            "prioridade": chamado.prioridade,
            "categoria": chamado.categoria,
        }


# ─── Endpoints de Estado e QR Code ───────────────────────────────────────────

@router.get("/status")
def get_whatsapp_status(request: Request, instance: Optional[str] = None):
    _require_atendimento_access(request)
    base_url, wa_token, instance = get_evolution_api_endpoints(instance)
    if not base_url:
        return {"status": "unconfigured", "message": "Evolution API não configurada em Configurações."}

    _enable_media_webhook(base_url, wa_token, instance)
        
    url = f"{base_url}/instance/connectionState/{instance}"
    headers = {}
    if wa_token:
        headers["apikey"] = wa_token
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Evolution API pode retornar {"instance": {"state": "open"}} ou {"state": "open"}
            state = data.get("instance", {}).get("state") or data.get("state", "disconnected")
            return {"status": "configured", "state": state}
        elif resp.status_code in [404, 400]:
            # Instância não existe — cria automaticamente
            _create_instance(base_url, wa_token, instance)
            return {"status": "configured", "state": "disconnected"}
        else:
            return {"status": "error", "message": f"Evolution API respondeu status {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"status": "error", "message": f"Falha de conexão com a API: {str(e)}"}


def _create_instance(base_url: str, wa_token: str, instance: str):
    """Cria a instância na Evolution API se ela não existir e configura o webhook de retorno."""
    create_url = f"{base_url}/instance/create"
    config = get_whatsapp_config()
    webhook_url = get_whatsapp_webhook_target(config)
    payload = {
        "instanceName": instance,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
        # Webhook para receber mensagens de volta no nosso sistema
        "webhook": {
            "url": webhook_url,
            "byEvents": False,
            "base64": True,
            "events": [
                "MESSAGES_UPSERT",
                "MESSAGES_UPDATE",
                "CONNECTION_UPDATE",
                "PRESENCE_UPDATE"
            ]
        }
    }
    print(f"[WhatsApp] Usando webhook target: {webhook_url}")
    # Só inclui o token se não for vazio
    if wa_token:
        payload["token"] = wa_token

    c_headers = {"Content-Type": "application/json"}
    if wa_token:
        c_headers["apikey"] = wa_token

    try:
        resp = requests.post(create_url, json=payload, headers=c_headers, timeout=8)
        print(f"[WhatsApp] Instância '{instance}' criada: {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        print(f"[WhatsApp] Aviso ao criar instância: {e}")



def _enable_media_webhook(base_url: str, wa_token: str, instance: str):
    """Atualiza instâncias existentes para incluir mídia no webhook."""
    config = get_whatsapp_config()
    try:
        response = requests.post(
            f"{base_url}/webhook/set/{instance}",
            headers={"apikey": wa_token, "Content-Type": "application/json"},
            json={"webhook": {
                "enabled": True,
                "url": get_whatsapp_webhook_target(config),
                "byEvents": False,
                "base64": True,
                "events": ["MESSAGES_UPSERT", "MESSAGES_UPDATE", "CONNECTION_UPDATE", "PRESENCE_UPDATE"],
            }},
            timeout=8,
        )
        print(f"[WhatsApp] Webhook de mídia '{instance}': {response.status_code}")
    except Exception as exc:
        print(f"[WhatsApp] Aviso ao atualizar webhook de mídia: {exc}")


@router.get("/qrcode")
def get_whatsapp_qrcode(request: Request, instance: Optional[str] = None):
    """
    Garante que a instância existe e busca o QR Code para autenticação.
    Caso a instância não exista, cria-a antes de buscar o QR.
    """
    _require_tauri_admin(request)
    base_url, wa_token, instance = get_evolution_api_endpoints(instance)
    if not base_url:
        raise HTTPException(status_code=400, detail="Evolution API não configurada.")

    _enable_media_webhook(base_url, wa_token, instance)

    headers = {}
    if wa_token:
        headers["apikey"] = wa_token

    # 1. Verifica se a instância existe — se não, cria
    state_url = f"{base_url}/instance/connectionState/{instance}"
    try:
        state_resp = requests.get(state_url, headers=headers, timeout=5)
        if state_resp.status_code in [404, 400]:
            print(f"[WhatsApp] Instância '{instance}' não existe. Criando...")
            _create_instance(base_url, wa_token, instance)
            # Aguarda um instante para a instância inicializar
            time.sleep(1)
    except Exception as e:
        print(f"[WhatsApp] Aviso ao verificar instância: {e}")

    # 2. Busca o QR Code via /instance/connect/{instance}
    url = f"{base_url}/instance/connect/{instance}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            # Evolution API retorna {"code": "...", "base64": "data:image/png;base64,..."}
            data = resp.json()
            if not data.get("base64") and not data.get("code"):
                raise HTTPException(status_code=502, detail="Evolution API retornou resposta vazia para o QR Code. A instância pode já estar conectada.")
            return data
        elif resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Instância não encontrada na Evolution API. Verifique a URL configurada.")
        else:
            raise HTTPException(status_code=resp.status_code, detail=f"Erro Evolution: {resp.text[:300]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha de rede com Evolution API: {str(e)}")


@router.post("/disconnect")
def disconnect_whatsapp(request: Request, instance: Optional[str] = None):
    _require_atendimento_access(request)
    _, user_role = _get_user(request)
    tenant_context = None
    if user_role == "admin":
        _require_admin(request)
    else:
        _require_tauri_admin(request)
        tenant_context = resolve_context(request)
        
    base_url, wa_token, instance = get_evolution_api_endpoints(instance)
    if not base_url:
        raise HTTPException(status_code=400, detail="Evolution API não configurada.")
        
    if tenant_context is not None:
        with Session(engine) as session:
            owned = session.exec(text("""
                SELECT id FROM instancias_whatsapp_tenant
                WHERE empresa_atendimento_id = :tenant_id
                  AND LOWER(TRIM(instance_name)) = :instance_name
                  AND ativa = TRUE
            """).bindparams(
                tenant_id=tenant_context.tenant_id,
                instance_name=str(instance).lower(),
            )).first()
        if not owned:
            raise HTTPException(status_code=404, detail="Aparelho nÃ£o pertence Ã  empresa atual.")

    url = f"{base_url}/instance/logout/{instance}"
    headers = {}
    if wa_token:
        headers["apikey"] = wa_token
        
    try:
        print(f"[WhatsApp] Iniciando sequência de logout para instância '{instance}' (base: {base_url})")

        attempts = []

        # Primary attempt - path with instance in URL
        attempts.append({"method": "POST", "url": f"{base_url}/instance/logout/{instance}", "kwargs": {}})
        # Alternate: POST to /instance/logout with payloads
        attempts.append({"method": "POST", "url": f"{base_url}/instance/logout", "kwargs": {"json": {"instanceName": instance}}})
        attempts.append({"method": "POST", "url": f"{base_url}/instance/logout", "kwargs": {"json": {"instance": instance}}})
        attempts.append({"method": "POST", "url": f"{base_url}/instance/logout", "kwargs": {"json": {"name": instance}}})
        attempts.append({"method": "POST", "url": f"{base_url}/instance/logout", "kwargs": {"data": {"instanceName": instance}}})
        attempts.append({"method": "POST", "url": f"{base_url}/instance/logout", "kwargs": {"params": {"instanceName": instance}}})
        # Alternate path variants
        attempts.append({"method": "POST", "url": f"{base_url}/instance/{instance}/logout", "kwargs": {}})
        # Try GET path variants
        attempts.append({"method": "GET", "url": f"{base_url}/instance/logout/{instance}", "kwargs": {}})
        attempts.append({"method": "GET", "url": f"{base_url}/instance/{instance}/logout", "kwargs": {}})
        attempts.append({"method": "GET", "url": f"{base_url}/instance/logout", "kwargs": {"params": {"instanceName": instance}}})
        attempts.append({"method": "DELETE", "url": f"{base_url}/instance/logout/{instance}", "kwargs": {}})
        attempts.append({"method": "DELETE", "url": f"{base_url}/instance/{instance}/logout", "kwargs": {}})
        attempts.append({"method": "DELETE", "url": f"{base_url}/instance/delete/{instance}", "kwargs": {}})

        errors = []
        for a in attempts:
            m = a["method"]
            u = a["url"]
            k = a.get("kwargs", {})
            try:
                print(f"[WhatsApp] Tentando {m} {u} payload={k.get('json') or k.get('data')}")
                resp = requests.request(m, u, headers=headers, timeout=6, **k)
                status = resp.status_code
                text = resp.text or resp.reason or ""
                print(f"[WhatsApp] Resposta {status} para {u}: {text[:200]}")
                if status in (200, 204) or status == 404:
                    print(f"[WhatsApp] Logout bem-sucedido (ou já inexistente) via {u}")
                    # A Evolution pode manter a instÃ¢ncia registrada mesmo
                    # apÃ³s o logout (DEL_INSTANCE=false). Remova-a tambÃ©m
                    # para nÃ£o acumular conexÃµes antigas.
                    try:
                        delete_resp = requests.delete(
                            f"{base_url}/instance/delete/{instance}",
                            headers=headers,
                            timeout=8,
                        )
                        print(f"[WhatsApp] InstÃ¢ncia '{instance}' removida: {delete_resp.status_code}")
                    except requests.RequestException as delete_exc:
                        print(f"[WhatsApp] Aviso ao remover instÃ¢ncia '{instance}': {delete_exc}")
                    if tenant_context is not None:
                        with Session(engine) as session:
                            session.exec(text("""
                                UPDATE instancias_whatsapp_tenant
                                SET ativa = FALSE, padrao = FALSE
                                WHERE empresa_atendimento_id = :tenant_id
                                  AND LOWER(TRIM(instance_name)) = :instance_name
                            """).bindparams(
                                tenant_id=tenant_context.tenant_id,
                                instance_name=str(instance).lower(),
                            ))
                            session.commit()
                    else:
                        config = get_whatsapp_config()
                        instances = config.get("WHATSAPP_INSTANCES", [])
                        if not isinstance(instances, list):
                            instances = []
                        new_instances = [i for i in instances if (i.get("instanceName") if isinstance(i, dict) else i) != instance]
                        config["WHATSAPP_INSTANCES"] = new_instances
                        if config.get("WHATSAPP_DEFAULT_INSTANCE") == instance:
                            config["WHATSAPP_DEFAULT_INSTANCE"] = new_instances[0].get("instanceName") if new_instances else None
                        save_whatsapp_config(config)
                    _connected_map_cache["expires_at"] = 0
                    
                    return {"success": True}
                else:
                    errors.append(f"{m} {u} => {status}: {text}")
                    # continue trying other variants
            except requests.exceptions.RequestException as re:
                errors.append(f"{m} {u} => EXCEPTION: {str(re)}")
                print(f"[WhatsApp] Exceção ao tentar {m} {u}: {re}")
                continue

        # Se chegou aqui, todas as tentativas falharam
        summary = " | ".join(errors) if errors else "Nenhuma tentativa realizada"
        print(f"[WhatsApp] Todas tentativas de logout falharam: {summary}")
        raise HTTPException(status_code=502, detail=f"Falha ao desconectar instância. Tentativas: {summary}")

    except requests.exceptions.RequestException as e:
        print(f"[WhatsApp] Erro de conexão ao desconectar instância '{instance}': {e}")
        raise HTTPException(status_code=500, detail=f"Falha de conexão: {str(e)}")
    except Exception as e:
        # Se já for uma HTTPException, não encapsular — repassa ao cliente
        from fastapi import HTTPException as FastAPIHTTPException
        if isinstance(e, FastAPIHTTPException):
            print(f"[WhatsApp] HTTPException repassada: {e.detail}")
            raise e
        print(f"[WhatsApp] Erro inesperado ao desconectar instância '{instance}': {e}")
        raise HTTPException(status_code=500, detail=f"Falha inesperada: {str(e)}")


# ─── Listagem de Chats (com regras de permissão) ───────────────────────────

@router.get("/chats")
def get_whatsapp_chats(request: Request):
    _require_atendimento_access(request)
    _ensure_whatsapp_columns()
    user_name, user_role = _get_user(request)
    show_groups = bool(get_whatsapp_config().get("WHATSAPP_SHOW_GROUPS", False))
    
    # Tenta obter números conectados por instância (para indicar presença)
    now = time.time()
    if _connected_map_cache["expires_at"] > now:
        connected_map = _connected_map_cache["value"]
    else:
        connected_map = {}
        try:
            instances, _ = get_whatsapp_instances()
            # As consultas eram sequenciais: com quatro instâncias, uma API
            # lenta podia atrasar a abertura por até 12 segundos. Agora cada
            # instância tem seu próprio timeout e é consultada em paralelo.
            if instances:
                workers = min(8, len(instances))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    for name, numbers in executor.map(_get_instance_presence, instances):
                        if name:
                            connected_map[name] = numbers
        except Exception:
            connected_map = {}
        _connected_map_cache["value"] = connected_map
        _connected_map_cache["expires_at"] = now + 10

    with Session(engine) as session:
        # Query base para chamados vindos do WhatsApp
        stmt = select(Chamado).where(Chamado.origem == "WhatsApp")
        
        # Filtro de visibilidade baseado em privilégio
        if _is_reception_role(user_role):
            # A recepção trabalha exclusivamente com a fila inicial de triagem.
            stmt = stmt.where(Chamado.assigned_user == None, Chamado.status != "Resolvido")
        elif not _can_manage_atendimento(request, user_role):
            # Operador: Vê chamados não atribuídos OU atribuídos a ele mesmo
            stmt = stmt.where(
                (Chamado.assigned_user == user_name) | 
                ((Chamado.assigned_user == None) & (Chamado.status != "Resolvido"))
            )
            
        stmt = stmt.order_by(desc(Chamado.data_abertura))
        chamados = session.exec(stmt).all()

        # Logos das empresas vinculadas às instâncias WhatsApp. Mantém a
        # identidade correta no cabeçalho mesmo quando o contato/grupo possui
        # uma foto própria.
        company_logos = {}
        try:
            company_rows = session.exec(text("SELECT id, logo_url FROM empresas_atendimento WHERE logo_url IS NOT NULL AND logo_url <> ''")).all()
            company_logos = {int(row[0]): str(row[1]) for row in company_rows if row[0] and row[1]}
        except Exception:
            company_logos = {}

        # Busca a última interação de todos os chamados em uma única consulta.
        # Uma consulta por conversa deixava esta rota cada vez mais lenta.
        latest_by_ticket = {}
        chamado_ids = [item.id for item in chamados if item.id is not None]
        if chamado_ids:
            latest_ids = session.exec(
                select(func.max(ChamadoInteracao.id))
                .where(ChamadoInteracao.chamado_id.in_(chamado_ids))
                .group_by(ChamadoInteracao.chamado_id)
            ).all()
            interactions = session.exec(
                select(ChamadoInteracao).where(ChamadoInteracao.id.in_(latest_ids))
            ).all() if latest_ids else []
            for interaction in interactions:
                latest_by_ticket.setdefault(interaction.chamado_id, interaction)
        

        # --- Setores por operador e por instância (para exibir no card) ---
        setor_by_user = {}   # {username: "Setor"}
        setor_by_instance = {}  # {instance_name: "Setor"}
        try:
            # Mapeia cada usuário ao primeiro setor vinculado
            user_sector_rows = session.exec(text("""
                SELECT u.nome, s.nome
                FROM usuarios_setores_atendimento usa
                JOIN usuarios u ON u.id = usa.usuario_id
                JOIN setores_atendimento s ON s.id = usa.setor_id
                ORDER BY s.nome
            """)).all()
            for uname, sname in user_sector_rows:
                if uname and uname not in setor_by_user:
                    setor_by_user[uname] = sname

            # Mapeia cada instância ao primeiro setor vinculado
            inst_sector_rows = session.exec(text("""
                SELECT i.instance_name, s.nome
                FROM instancias_setores_atendimento isa
                JOIN instancias_whatsapp_tenant i ON i.id = isa.instancia_id
                JOIN setores_atendimento s ON s.id = isa.setor_id
                ORDER BY s.nome
            """)).all()
            for iname, sname in inst_sector_rows:
                if iname and iname not in setor_by_instance:
                    setor_by_instance[iname] = sname
        except Exception:
            pass

        resultado = []
        instance_colors = get_whatsapp_config().get("WHATSAPP_INSTANCE_COLORS", {}) or {}
        configured_instances, _ = get_whatsapp_instances()
        instance_label_map = {item["instanceName"]: item.get("label") or item["instanceName"] for item in configured_instances}
        instance_number_map = {}
        for inst_name, nums in connected_map.items():
            if nums:
                instance_number_map[inst_name] = next(iter(nums))
        for c in chamados:
            if not user_can_access_instance(request, c.whatsapp_instance):
                continue
            # Busca a última mensagem do chamado
            last_msg = latest_by_ticket.get(c.id)
            if last_msg and not str(c.whatsapp_cliente or "").lower().endswith("@g.us"):
                interaction_jid = str(last_msg.whatsapp_remote_jid or "")
                if interaction_jid.lower().endswith("@g.us"):
                    c.whatsapp_cliente = interaction_jid
                    session.add(c)
                    session.commit()
            if not str(c.whatsapp_cliente or "").lower().endswith("@g.us"):
                group_interaction = session.exec(
                    select(ChamadoInteracao).where(
                        ChamadoInteracao.chamado_id == c.id,
                        ChamadoInteracao.whatsapp_remote_jid.like("%@g.us"),
                    ).order_by(desc(ChamadoInteracao.data_hora)).limit(1)
                ).first()
                if group_interaction:
                    c.whatsapp_cliente = group_interaction.whatsapp_remote_jid
                    session.add(c)
                    session.commit()
            if not show_groups and str(c.whatsapp_cliente or "").lower().endswith("@g.us"):
                continue

            is_group_chat = str(c.whatsapp_cliente or "").lower().endswith("@g.us")
            if is_group_chat and (
                not c.usuario or c.usuario.strip() in ("Grupo WhatsApp", c.whatsapp_cliente) or c.usuario.strip().startswith("Grupo WhatsApp ·")
            ):
                group_name = get_whatsapp_group_name(c.whatsapp_cliente, c.whatsapp_instance)
                if group_name:
                    c.usuario = group_name
                    session.add(c)
                    session.commit()
            if is_group_chat and (not c.usuario or c.usuario.strip() == c.whatsapp_cliente):
                c.usuario = f"Grupo WhatsApp · {str(c.whatsapp_cliente).split('@')[0]}"
                session.add(c)
                session.commit()
            
            # determina presença: se o chamado tem `whatsapp_instance`, checa lá, senão checa em todas
            is_connected = False
            try:
                if c.whatsapp_instance:
                    nums = connected_map.get(c.whatsapp_instance, set())
                    is_connected = str(c.whatsapp_cliente) in nums or str(c.whatsapp_cliente).lstrip('+') in nums
                else:
                    # verifica em todas as instâncias
                    for nums in connected_map.values():
                        if str(c.whatsapp_cliente) in nums or str(c.whatsapp_cliente).lstrip('+') in nums:
                            is_connected = True
                            break
            except Exception:
                is_connected = False

            ultima_atividade = last_msg.data_hora if last_msg else c.data_abertura
            inst_label = instance_label_map.get(c.whatsapp_instance) or c.whatsapp_instance or "Principal"
            inst_owner = instance_number_map.get(c.whatsapp_instance) or ""
            resultado.append({
                "id": c.id,
                "usuario": c.usuario or (f"Grupo WhatsApp · {str(c.whatsapp_cliente).split('@')[0]}" if is_group_chat else "Contato sem nome"),
                "is_group": is_group_chat,
                "whatsapp_instance": c.whatsapp_instance,
                "whatsapp_instance_label": inst_label,
                "instance_owner_number": inst_owner,
                "empresa_logo": company_logos.get(c.empresa_atendimento_id) or get_whatsapp_config().get("APP_LOGO_URL", ""),
                "instance_color": instance_colors.get(c.whatsapp_instance, "#00a884"),
                "visivel_suporte": bool(c.visivel_suporte),
                "connected": is_connected,
                "whatsapp_cliente": c.whatsapp_cliente,
                "group_name": c.usuario if is_group_chat else None,
                "categoria": c.categoria,
                "status": c.status,
                "prioridade": c.prioridade,
                "setor": setor_by_user.get(c.assigned_user) or setor_by_instance.get(c.whatsapp_instance) or None,
                "assigned_user": c.assigned_user,
                # A fila Ã© compartilhada: todos os perfis autorizados precisam
                # enxergar o contador de mensagens pendentes.
                "unread_admin": c.unread_admin or 0,
                "data_abertura": _display_datetime(c.data_abertura).strftime("%d/%m/%Y %H:%M"),
                "ultima_mensagem": last_msg.mensagem if last_msg else c.descricao,
                "data_ultima_mensagem": _display_datetime(ultima_atividade).strftime("%d/%m %H:%M"),
                "data_ultima_mensagem_iso": ultima_atividade.isoformat(),
            })
            
        return resultado


def _get_local_whatsapp_contacts(instance: Optional[str] = None):
    """Retorna contatos locais quando a sincronização externa não estiver disponível."""
    with Session(engine) as session:
        local = session.exec(select(ContatoWhatsApp).order_by(ContatoWhatsApp.nome)).all()
    result = []
    for item in local:
        if instance and item.whatsapp_instance and item.whatsapp_instance != instance:
            continue
        number = _real_contact_number({"number": item.numero})
        if not number:
            continue
        result.append({
            "id": item.id,
            "name": item.nome or "Sem nome",
            "number": item.numero,
            "company": item.empresa or "",
            "note": item.observacao or "",
            "instance": item.whatsapp_instance or instance or get_default_whatsapp_instance(get_whatsapp_config()) or "",
            "local": True,
            "is_local": True,
        })
    return result


@router.get("/contacts")
def get_whatsapp_contacts(request: Request, instance: Optional[str] = None):
    _require_atendimento_access(request)
    _ensure_whatsapp_columns()
    if not instance and atendimento_multiempresa_enabled() and get_signed_cookie(request, "user_role") != "admin":
        try:
            context = resolve_context(request)
            with Session(engine) as session:
                tenant_instance = session.exec(text("""
                    SELECT instance_name
                    FROM instancias_whatsapp_tenant
                    WHERE empresa_atendimento_id = :tenant_id AND ativa = TRUE
                    ORDER BY padrao DESC, instance_name
                    LIMIT 1
                """).bindparams(tenant_id=context.tenant_id)).first()
            if tenant_instance:
                instance = str(tenant_instance[0])
        except Exception:
            pass
    base_url, wa_token, resolved = get_evolution_api_endpoints(instance)
    if not base_url:
        return _get_local_whatsapp_contacts(instance)
    try:
        response = requests.post(
            f"{base_url}/chat/findContacts/{resolved}",
            headers={"apikey": wa_token or "", "Content-Type": "application/json"},
            json={"where": {}, "take": 1000, "skip": 0, "orderBy": {}},
            timeout=20,
        )
        if not response.ok:
            return _get_local_whatsapp_contacts(instance or resolved)
        payload = response.json()
        if isinstance(payload, list):
            contacts = payload
        elif isinstance(payload, dict):
            contacts = payload.get("contacts") or payload.get("data") or payload.get("results") or []
            if isinstance(contacts, dict):
                contacts = contacts.get("contacts") or contacts.get("data") or []
        else:
            contacts = []
        synced = []
        seen_keys = set()
        with Session(engine) as session:
            local = session.exec(select(ContatoWhatsApp).order_by(ContatoWhatsApp.nome)).all()

        local_by_key = {}
        for item in local:
            num = _real_contact_number({"number": item.numero})
            if num:
                local_by_key[_canonical_contact_key(num)] = item

        for item in contacts:
            number = _real_contact_number(item)
            if not number:
                continue
            key = _canonical_contact_key(number)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            loc = local_by_key.get(key)
            synced.append({
                "id": loc.id if loc else (item.get("id") or number),
                "name": (loc.nome if loc and loc.nome else None) or item.get("pushName") or item.get("name") or "Sem nome",
                "number": loc.numero if loc and loc.numero else number,
                "profile_picture": item.get("profilePictureUrl") or item.get("profilePicUrl") or item.get("profile_picture"),
                "company": loc.empresa if loc and loc.empresa else "",
                "note": loc.observacao if loc and loc.observacao else "",
                "instance": (loc.whatsapp_instance if loc and loc.whatsapp_instance else None) or resolved,
                "local": bool(loc),
                "is_local": bool(loc),
            })

        for key, loc in local_by_key.items():
            if key not in seen_keys:
                seen_keys.add(key)
                synced.append({
                    "id": loc.id,
                    "name": loc.nome or "Sem nome",
                    "number": loc.numero,
                    "company": loc.empresa or "",
                    "note": loc.observacao or "",
                    "instance": loc.whatsapp_instance or resolved,
                    "local": True,
                    "is_local": True,
                })
        return synced
    except HTTPException:
        raise
    except Exception as exc:
        try:
            return _get_local_whatsapp_contacts(instance or resolved)
        except Exception:
            raise HTTPException(status_code=502, detail=f"Erro ao sincronizar contatos: {exc}")


@router.post("/contacts/start")
def start_whatsapp_contact(payload: dict = Body(...), request: Request = None, background_tasks: BackgroundTasks = None):
    payload = payload or {}
    if request is None:
        raise HTTPException(status_code=401, detail="Sessão inválida para iniciar conversa")
    _require_atendimento_access(request)
    user_name, _ = _get_user(request)
    number = str(payload.get("number") or "").strip()
    contact_name = str(payload.get("name") or number).strip()
    message_text = str(payload.get("message") or "").strip()
    instance = str(payload.get("instance") or get_default_whatsapp_instance(get_whatsapp_config()) or "").strip()
    force_new = bool(payload.get("force_new", False))
    if not number:
        raise HTTPException(status_code=400, detail="Número do contato é obrigatório")

    ticket_id = None
    warning = ""
    try:
        with Session(engine) as session:
            chamado = None
            if not force_new:
                chamado = session.exec(select(Chamado).where(
                    Chamado.whatsapp_cliente == number,
                    Chamado.whatsapp_instance == instance,
                    Chamado.status != "Resolvido",
                ).order_by(desc(Chamado.data_abertura))).first()
            if not chamado:
                chamado = Chamado(
                    usuario=contact_name,
                    titulo="Atendimento WhatsApp",
                    categoria="WhatsApp",
                    descricao=message_text or "Conversa iniciada pelo atendente",
                    origem="WhatsApp",
                    whatsapp_cliente=number,
                    whatsapp_instance=instance,
                    empresa_atendimento_id=tenant_id_for_instance(instance),
                    status="Aberto",
                    prioridade="Media",
                    visivel_suporte=True,
                    assigned_user=user_name,
                )
                session.add(chamado)
                session.commit()
                session.refresh(chamado)
            else:
                # Quem inicia uma conversa pela Lista de Contatos assume o atendimento.
                chamado.assigned_user = user_name
                if chamado.status == "Aberto":
                    chamado.status = "Em Atendimento"
                session.add(chamado)
                session.commit()

            ticket_id = chamado.id

            if message_text:
                interaction = ChamadoInteracao(chamado_id=chamado.id, usuario=user_name, mensagem=message_text, whatsapp_status="sent")
                session.add(interaction)
                session.commit()
                try:
                    if background_tasks:
                        background_tasks.add_task(send_whatsapp_text, number, f"*{user_name}*:\n{message_text}", instance)
                    else:
                        send_whatsapp_text(number, f"*{user_name}*:\n{message_text}", instance)
                except Exception as send_exc:
                    print(f"[WHATSAPP_CONTACT_START] Falha ao disparar envio WhatsApp: {send_exc}")
                    warning = f"Conversa iniciada, mas o envio do WhatsApp não foi confirmado: {send_exc}"

        response = {"success": True, "ticket_id": ticket_id}
        if warning:
            response["warning"] = warning
        return response
    except Exception as exc:
        print(f"[WHATSAPP_CONTACT_START] Falha ao iniciar conversa: {exc}")
        if ticket_id:
            return {"success": True, "ticket_id": ticket_id, "warning": f"Conversa iniciada, mas houve um erro de finalização: {exc}"}
        raise HTTPException(status_code=500, detail=f"Não foi possível iniciar a conversa: {exc}") from exc


@router.post("/contacts/local")
def create_local_contact(payload: dict = Body(...), request: Request = None):
    _require_atendimento_access(request)
    name = str(payload.get("name") or "").strip()
    number = _normalize_contact_number(payload.get("number")) or ""
    if not name or len(number) < 8:
        raise HTTPException(status_code=400, detail="Informe nome e um número válido")
    with Session(engine) as session:
        contact = ContatoWhatsApp(nome=name, numero=number, empresa=str(payload.get("company") or "").strip() or None, observacao=str(payload.get("note") or "").strip() or None, whatsapp_instance=str(payload.get("instance") or get_default_whatsapp_instance(get_whatsapp_config()) or ""))
        session.add(contact)
        session.commit()
        session.refresh(contact)
        return {"success": True, "id": contact.id}


@router.post("/contacts/import")
def import_local_contacts(payload: dict = Body(...), request: Request = None):
    """Importa uma lista de contatos externos, ignorando identificadores @lid."""
    _require_atendimento_access(request)
    raw_contacts = payload.get("contacts") or []
    if not isinstance(raw_contacts, list):
        raise HTTPException(status_code=400, detail="A lista de contatos é inválida")

    instance = str(payload.get("instance") or get_default_whatsapp_instance(get_whatsapp_config()) or "").strip()
    normalized = {}
    ignored = 0
    for item in raw_contacts:
        if not isinstance(item, dict):
            ignored += 1
            continue
        number = _normalize_contact_number(item.get("number")) or ""
        if len(number) < 8:
            ignored += 1
            continue
        name = str(item.get("name") or "").strip() or f"Contato {number}"
        normalized[number] = name[:180]

    if not normalized:
        return {"success": True, "imported": 0, "updated": 0, "ignored": ignored}

    imported = 0
    updated = 0
    with Session(engine) as session:
        existing = session.exec(select(ContatoWhatsApp).where(ContatoWhatsApp.numero.in_(list(normalized.keys())))).all()
        existing_by_number = {str(contact.numero): contact for contact in existing}
        for number, name in normalized.items():
            contact = existing_by_number.get(number)
            if contact:
                if not contact.nome or contact.nome.startswith("Contato "):
                    contact.nome = name
                if instance and not contact.whatsapp_instance:
                    contact.whatsapp_instance = instance
                session.add(contact)
                updated += 1
                continue
            session.add(ContatoWhatsApp(nome=name, numero=number, whatsapp_instance=instance or None))
            imported += 1
        session.commit()

    return {"success": True, "imported": imported, "updated": updated, "ignored": ignored}


@router.put("/contacts/local/{contact_id}")
def update_local_contact(contact_id: int, payload: dict = Body(...), request: Request = None):
    _require_atendimento_access(request)
    name = str(payload.get("name") or "").strip()
    number = _normalize_contact_number(payload.get("number")) or ""
    if not name or len(number) < 8:
        raise HTTPException(status_code=400, detail="Informe nome e um número válido")
    with Session(engine) as session:
        contact = session.get(ContatoWhatsApp, contact_id)
        if not contact:
            raise HTTPException(status_code=404, detail="Contato não encontrado")
        contact.nome = name
        contact.numero = number
        contact.empresa = str(payload.get("company") or "").strip() or None
        contact.observacao = str(payload.get("note") or "").strip() or None
        session.add(contact)
        session.commit()
    return {"success": True, "id": contact_id}


@router.delete("/contacts/local/{contact_id}")
def delete_local_contact(contact_id: int, request: Request = None):
    _require_atendimento_access(request)
    with Session(engine) as session:
        contact = session.get(ContatoWhatsApp, contact_id)
        if not contact:
            raise HTTPException(status_code=404, detail="Contato não encontrado")
        session.delete(contact)
        session.commit()
    return {"success": True, "id": contact_id}


@router.post("/promover/{ticket_id}")
def promover_chamado_whatsapp(ticket_id: int, request: Request, background_tasks: BackgroundTasks):
    """Torna visível no módulo Chamados uma conversa que estava apenas na Central."""
    _require_atendimento_access(request)
    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404, detail="Conversa não encontrada")
        if chamado.origem != "WhatsApp":
            raise HTTPException(status_code=400, detail="A conversa não é de origem WhatsApp")

        chamado.visivel_suporte = True
        session.add(chamado)
        session.commit()

    background_tasks.add_task(manager.broadcast, {
        "event": "whatsapp_ticket_updated",
        "ticket_id": ticket_id,
        "visivel_suporte": True,
    })
    return {"success": True, "ticket_id": ticket_id}


@router.post("/assumir/{ticket_id}")
def assumir_chat(ticket_id: int, request: Request, background_tasks: BackgroundTasks):
    _require_atendimento_access(request)
    user_name, _ = _get_user(request)
    
    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")
            
        if chamado.origem != "WhatsApp":
            raise HTTPException(status_code=400, detail="Este chamado não é de origem WhatsApp")
            
        # Atribui o chamado ao operador logado e atualiza status se estiver em Aberto
        chamado.assigned_user = user_name
        if chamado.status == "Aberto":
            chamado.status = "Em Atendimento"
            
        session.commit()
        
        # Envia mensagem automática para o WhatsApp avisando quem assumiu
        if chamado.whatsapp_cliente:
            msg_wa = f"Seu atendimento foi iniciado. Você está conversando com o(a) atendente *{user_name}*."
            background_tasks.add_task(send_whatsapp_text, chamado.whatsapp_cliente, msg_wa, chamado.whatsapp_instance)
        
        # Avisa todos via WebSocket sobre a alteração de atribuição
        background_tasks.add_task(
            manager.broadcast,
            {
                "event": "whatsapp_chat_assigned",
                "ticket_id": ticket_id,
                "assigned_user": user_name,
                "status": chamado.status
            }
        )
        return {"success": True, "assigned_user": user_name}


@router.get("/operators")
def list_atendimento_operators(request: Request):
    _require_atendimento_access(request)
    tenant_context = resolve_context(request)
    with Session(engine) as session:
        tenant_user_ids = None
        if tenant_context.enabled and tenant_context.tenant_id is not None:
            rows = session.exec(text("SELECT usuario_id FROM usuarios_empresas_atendimento WHERE empresa_atendimento_id = :tenant_id AND ativo = TRUE").bindparams(tenant_id=tenant_context.tenant_id)).all()
            tenant_user_ids = [int(row[0]) for row in rows]
        users = session.exec(
            select(Usuario)
            .where(
                Usuario.status_conta == "ativo",
                *([Usuario.id.in_(tenant_user_ids)] if tenant_user_ids is not None else []),
                Usuario.role.notin_(["recepcao", "recepção", "recepcionista", "cliente_atendimento"]),
            )
            .order_by(Usuario.nome, Usuario.username)
        ).all()
        return [
            {
                "id": user.id,
                "name": user.nome or user.username,
                "role": user.role,
            }
            for user in users
        ]


@router.post("/transferir/{ticket_id}")
def transferir_chat(ticket_id: int, payload: dict = Body(...), request: Request = None, background_tasks: BackgroundTasks = None):
    _require_atendimento_access(request)
    user_name, user_role = _get_user(request)
    target_user = str(payload.get("assigned_user") or "").strip()
    if not target_user:
        raise HTTPException(status_code=400, detail="Selecione um atendente")

    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado or chamado.origem != "WhatsApp":
            raise HTTPException(status_code=404, detail="Chamado não encontrado")
        if not _can_manage_atendimento(request, user_role) and chamado.assigned_user != user_name:
            raise HTTPException(status_code=403, detail="Somente o responsável pode transferir este atendimento")

        target = session.exec(
            select(Usuario).where(
                (Usuario.nome == target_user) | (Usuario.username == target_user),
                Usuario.status_conta == "ativo",
            )
        ).first()
        if not target:
            raise HTTPException(status_code=400, detail="Atendente não encontrado ou inativo")

        assigned_name = target.nome or target.username
        chamado.assigned_user = assigned_name
        chamado.status = "Em Atendimento"
        session.commit()

        if background_tasks and chamado.whatsapp_cliente:
            background_tasks.add_task(
                send_whatsapp_text,
                chamado.whatsapp_cliente,
                f"Seu atendimento foi transferido para o(a) atendente *{assigned_name}*.",
                chamado.whatsapp_instance,
            )
        if background_tasks:
            background_tasks.add_task(
                manager.broadcast,
                {"event": "whatsapp_chat_assigned", "ticket_id": ticket_id, "assigned_user": assigned_name, "status": chamado.status},
            )
        return {"success": True, "assigned_user": assigned_name}


# ─── Webhook Receptor de Mensagens da Evolution API ──────────────────────────

def _unwrap_whatsapp_message(message_obj: dict) -> dict:
    """Remove wrappers comuns do Baileys/Evolution antes de ler a mensagem."""
    atual = message_obj if isinstance(message_obj, dict) else {}
    wrappers = (
        "ephemeralMessage",
        "viewOnceMessage",
        "viewOnceMessageV2",
        "viewOnceMessageV2Extension",
        "documentWithCaptionMessage",
    )
    for _ in range(4):
        proxima = None
        for wrapper in wrappers:
            node = atual.get(wrapper)
            if isinstance(node, dict) and isinstance(node.get("message"), dict):
                proxima = node["message"]
                break
        if not proxima:
            break
        atual = proxima
    return atual


def _extract_whatsapp_text(message_obj: dict) -> str:
    """Lê textos de formatos alternativos sem transformar a mensagem em marcador."""
    if not isinstance(message_obj, dict):
        return ""
    direct_keys = ("text", "body", "content", "conversation")
    for key in direct_keys:
        value = message_obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested_keys = (
        ("extendedTextMessage", "text"),
        ("textMessage", "text"),
        ("buttonsResponseMessage", "selectedDisplayText"),
        ("listResponseMessage", "singleSelectReply"),
        ("listResponseMessage", "title"),
        ("templateButtonReplyMessage", "selectedDisplayText"),
        ("pollUpdateMessage", "name"),
    )
    for parent, child in nested_keys:
        node = message_obj.get(parent)
        if isinstance(node, dict):
            if parent == "listResponseMessage" and isinstance(node.get(child), dict):
                selected = node[child]
                value = selected.get("selectedRowId") or selected.get("selectedDisplayText")
                if isinstance(value, str) and value.strip():
                    return value.strip()
            value = node.get(child)
            if isinstance(value, str) and value.strip():
                return value.strip()
def _handle_agendamento_bot_interaction(
    phone_number: str,
    customer_name: str,
    msg_text: str,
    instance: str,
    ticket_id: int,
    is_new_ticket: bool,
    background_tasks: BackgroundTasks,
) -> bool:
    try:
        config = get_whatsapp_config()
        tenant_id = tenant_id_for_instance(instance)

        import api_atendimento_agenda
        settings = api_atendimento_agenda.get_agenda_settings(tenant_id=tenant_id)
        if not settings.get("enabled", False):
            return False

        nome_loja = settings.get("estabelecimento_nome") or "Nosso Estabelecimento"
        texto = (msg_text or "").strip()
        # O WhatsApp pode entregar o comando formatado com asteriscos e
        # alguns clientes colocam ';' depois do horário.
        texto = re.sub(r"^[*_`]+|[*_`]+$", "", texto).strip()
        texto = texto.replace("*", "").replace("_", "").replace("`", "").strip()
        texto_lower = texto.lower()
        comando_agenda = bool(re.match(r"^agenda(?:r)?\b", texto_lower))

        pending_key = f"{tenant_id}:{phone_number}"
        pending = _agenda_pending_slots.get(pending_key)
        if pending and pending[2] < time.time():
            _agenda_pending_slots.pop(pending_key, None)
            pending = None

        if texto_lower.startswith("agenda_slot|"):
            partes_slot = texto.split("|", 2)
            if len(partes_slot) == 3:
                _, data_selecionada, hora_selecionada = partes_slot
                _agenda_pending_slots[pending_key] = (data_selecionada, hora_selecionada, time.time() + 900)
                resposta = (
                    f"✅ Horário selecionado: *{data_selecionada} às {hora_selecionada}*\n\n"
                    "Agora informe o serviço desejado (ex.: *Corte*).\n"
                    "Digite *0* para escolher outro horário."
                )
                background_tasks.add_task(send_whatsapp_text, phone_number, resposta, instance)
                return True

        if pending and texto_lower not in ("0", "5") and not comando_agenda:
            data_selecionada, hora_selecionada, _ = pending
            sucesso, msg_resultado, dt_agendado = api_atendimento_agenda.agendar_horario_bot(
                nome_cliente=customer_name,
                telefone=phone_number,
                data_str=data_selecionada,
                hora_str=hora_selecionada,
                servico=texto,
                tenant_id=tenant_id,
            )
            _agenda_pending_slots.pop(pending_key, None)
            if sucesso and dt_agendado:
                resposta = (
                    "🎉 *Agendamento confirmado com sucesso!*\n\n"
                    f"👤 *Cliente:* {customer_name}\n"
                    f"📅 *Data:* {dt_agendado.strftime('%d/%m/%Y')} às {dt_agendado.strftime('%H:%M')}\n"
                    f"✂️ *Serviço:* {texto}\n\n"
                    "Se precisar de ajuda, digite *5* para falar com a recepção."
                )
                background_tasks.add_task(
                    manager.broadcast,
                    {
                        "event": "new_appointment",
                        "empresa_atendimento_id": tenant_id,
                        "nome_cliente": customer_name,
                        "telefone": phone_number,
                        "servico": texto,
                        "data_hora": dt_agendado.strftime("%d/%m/%Y %H:%M"),
                    },
                )
            else:
                resposta = f"⚠️ *Não foi possível confirmar o agendamento:*\n{msg_resultado}\n\nDigite *1* para escolher outro horário."
            background_tasks.add_task(send_whatsapp_text, phone_number, resposta, instance)
            return True
        if texto_lower == "0":
            _agenda_pending_slots.pop(pending_key, None)

        if texto_lower.startswith("cancelar"):
            partes_cancelar = texto.split()
            if len(partes_cancelar) < 3:
                resposta = "Para cancelar, envie: *CANCELAR [data] [horário]*\nExemplo: *CANCELAR 19/11 19:30*"
            else:
                encontrados = api_atendimento_agenda.localizar_agendamentos_cliente(
                    phone_number, partes_cancelar[1], partes_cancelar[2], tenant_id=tenant_id
                )
                if len(encontrados) != 1:
                    resposta = "⚠️ Não encontrei um agendamento exatamente nesse dia e horário."
                else:
                    cancelado, detalhe, _ = api_atendimento_agenda.cancelar_agendamento_cliente(
                        phone_number, encontrados[0]["id"], tenant_id=tenant_id
                    )
                    resposta = ("✅ " if cancelado else "⚠️ ") + detalhe
            background_tasks.add_task(send_whatsapp_text, phone_number, resposta, instance)
            return True

        if texto_lower.startswith(("remarcar", "remacar", "reagendar")):
            partes_remarcar = texto.split()
            remarcado = False
            detalhe = "Formato de remarcação inválido."
            agendamento_remarcado = None
            data_nova = None
            hora_nova = None

            # Formato curto: quando existe somente um agendamento ativo,
            # o cliente pode informar apenas o novo dia e horário.
            if len(partes_remarcar) == 3:
                ativos = api_atendimento_agenda.consultar_agendamentos_cliente(
                    phone_number, tenant_id=tenant_id
                )
                if len(ativos) == 1:
                    agendamento_id = ativos[0]["id"]
                    data_nova, hora_nova = partes_remarcar[1], partes_remarcar[2]
                    remarcado, detalhe, agendamento_remarcado = api_atendimento_agenda.remarcar_agendamento_cliente(
                        phone_number, agendamento_id, data_nova, hora_nova, tenant_id=tenant_id
                    )
                elif not ativos:
                    detalhe = "Não encontrei nenhum agendamento ativo para este número."
                else:
                    detalhe = (
                        "Você possui mais de um agendamento. Para eu identificar o correto, "
                        "envie: *REMARCAR [data atual] [horário atual] [nova data] [novo horário]*"
                    )
            # Formato completo e sem números de identificação:
            # REMARCAR [data atual] [horário atual] [nova data] [novo horário]
            elif len(partes_remarcar) >= 5:
                encontrados = api_atendimento_agenda.localizar_agendamentos_cliente(
                    phone_number, partes_remarcar[1], partes_remarcar[2], tenant_id=tenant_id
                )
                data_nova, hora_nova = partes_remarcar[3], partes_remarcar[4]
                if len(encontrados) != 1:
                    detalhe = "Não encontrei um agendamento exatamente nesse dia e horário."
                else:
                    remarcado, detalhe, agendamento_remarcado = api_atendimento_agenda.remarcar_agendamento_cliente(
                        phone_number,
                        encontrados[0]["id"],
                        data_nova,
                        hora_nova,
                        tenant_id=tenant_id,
                    )
            else:
                detalhe = (
                    "Para remarcar, envie: *REMARCAR [nova data] [novo horário]*.\n"
                    "Se tiver mais de um agendamento, envie: *REMARCAR [data atual] [horário atual] [nova data] [novo horário]*"
                )

            print(
                f"[AgendamentoBot] Remarcação telefone={phone_number} "
                f"comando={texto!r} sucesso={remarcado} detalhe={detalhe}"
            )
            if remarcado:
                data_confirmacao = data_nova or ""
                hora_confirmacao = hora_nova or ""
                titulo_confirmacao = (agendamento_remarcado or {}).get("titulo") or "Atendimento"
                resposta = (
                    f"✅ Agendamento remarcado com sucesso!\n\n"
                    f"Novo horário: *{data_confirmacao} às {hora_confirmacao}*\n"
                    f"Serviço: *{titulo_confirmacao}*\n\n"
                    "O horário anterior foi liberado e este novo horário foi reservado para você."
                )
                background_tasks.add_task(
                    manager.broadcast,
                    {
                        "event": "appointment_rescheduled",
                        "empresa_atendimento_id": tenant_id,
                        "nome_cliente": customer_name,
                        "telefone": phone_number,
                        "servico": titulo_confirmacao,
                        "data_hora": f"{data_confirmacao} {hora_confirmacao}",
                        "acao": "remarcado",
                    },
                )
            else:
                resposta = "⚠️ " + detalhe
            background_tasks.add_task(send_whatsapp_text, phone_number, resposta, instance)
            return True

        gatilhos_menu = (
            "menu", "inicio", "início", "oi", "ola", "olá", "bom dia", "boa tarde",
            "boa noite", "ajuda", "0", "comecar", "começar", "opcoes", "opções"
        )
        if is_new_ticket or texto_lower in gatilhos_menu:
            menu_msg = (
                f"Olá, {customer_name}! Bem-vindo(a) à *{nome_loja}*! ✂️💈\n\n"
                f"{settings.get('mensagem_boas_vindas')}\n\n"
                f"Digite o *número* da opção desejada:\n\n"
                f"1️⃣ - 📅 *Agendar um horário*\n"
                f"2️⃣ - 💇‍♂️ *Ver serviços e valores*\n"
                f"3️⃣ - 🔍 *Consultar, cancelar ou remarcar*\n"
                f"4️⃣ - 📍 *Endereço e horários*\n"
                f"5️⃣ - 👤 *Falar com a recepção*"
            )
            background_tasks.add_task(send_whatsapp_agenda_menu, phone_number, menu_msg, instance)
            return True

        if texto_lower in ("1", "agendar", "agendamento", "marcar", "marcar horario", "marcar horário"):
            horarios = api_atendimento_agenda.proximos_horarios_formatados(dias_desejados=3, tenant_id=tenant_id)
            dias_interativos = api_atendimento_agenda.proximos_horarios_interativos(dias_desejados=3, tenant_id=tenant_id)
            agenda_msg = (
                f"📅 *Próximos horários disponíveis em {nome_loja}:*\n\n"
                f"{horarios}\n\n"
                f"👉 *Para confirmar seu agendamento*, responda assim:\n"
                f"*AGENDAR [Data] [Horário] [Serviço]*\n\n"
                f"Exemplo:\n"
                f"*AGENDAR 20/11 14:00 Corte*\n\n"
                f"*(Ou digite 5 para falar com nossa recepção, ou 0 para voltar ao menu)*"
            )
            background_tasks.add_task(send_whatsapp_agenda_slots, phone_number, agenda_msg, dias_interativos, instance)
            return True

        if comando_agenda:
            partes = texto.split()
            if len(partes) >= 3:
                data_input = partes[1]
                hora_input = re.sub(r"[;,]+$", "", partes[2]).strip()
                servico_input = " ".join(partes[3:]).strip(" ;,*_`") if len(partes) > 3 else "Atendimento"
                sucesso, msg_resultado, dt_agendado = api_atendimento_agenda.agendar_horario_bot(
                    nome_cliente=customer_name,
                    telefone=phone_number,
                    data_str=data_input,
                    hora_str=hora_input,
                    servico=servico_input,
                    tenant_id=tenant_id,
                )
                if sucesso and dt_agendado:
                    resposta = (
                        f"🎉 *Agendamento Confirmado com Sucesso!*\n\n"
                        f"👤 *Cliente:* {customer_name}\n"
                        f"📅 *Data:* {dt_agendado.strftime('%d/%m/%Y')} às {dt_agendado.strftime('%H:%M')}\n"
                        f"✂️ *Serviço:* {servico_input}\n"
                        f"📍 *Local:* {settings.get('endereco')}\n\n"
                        f"Te esperamos! Caso precise remarcar, digite *3* ou envie *5* para falar com a recepção."
                    )
                    background_tasks.add_task(
                        manager.broadcast,
                        {
                            "event": "new_appointment",
                            "empresa_atendimento_id": tenant_id,
                            "nome_cliente": customer_name,
                            "telefone": phone_number,
                            "servico": servico_input,
                            "data_hora": dt_agendado.strftime("%d/%m/%Y %H:%M"),
                        }
                    )
                else:
                    resposta = (
                        f"⚠️ *Não foi possível confirmar o agendamento:*\n{msg_resultado}\n\n"
                        f"Digite *1* para rever os horários livres ou *5* para falar com nossa equipe."
                    )
                background_tasks.add_task(send_whatsapp_text, phone_number, resposta, instance)
                return True
            else:
                instrucao = (
                    f"Formato incompleto. Para agendar, envie:\n"
                    f"*AGENDAR [Data] [Horário] [Serviço]*\n\n"
                    f"Exemplo: *AGENDAR 20/11 14:00 Corte*"
                )
                background_tasks.add_task(send_whatsapp_text, phone_number, instrucao, instance)
                return True

        if texto_lower in ("2", "servicos", "serviços", "precos", "preços", "valores", "tabela", "preço", "preco"):
            servicos_msg = (
                f"✂️ *Serviços & Valores - {nome_loja}*\n\n"
                f"{settings.get('servicos_precos')}\n\n"
                f"─────────────────\n"
                f"👉 Para agendar, digite *1*\n"
                f"👉 Para falar com a recepção, digite *5*\n"
                f"👉 Para voltar ao menu, digite *0*"
            )
            background_tasks.add_task(send_whatsapp_text, phone_number, servicos_msg, instance)
            return True

        if texto_lower in ("3", "consultar", "meu agendamento", "meus agendamentos", "horario marcado", "horário marcado"):
            agendamentos = api_atendimento_agenda.consultar_agendamentos_cliente(phone_number, tenant_id=tenant_id)
            if agendamentos:
                linhas = []
                for ag in agendamentos:
                    linhas.append(f"• 📅 *{ag['data']} às {ag['hora']}* - {ag['titulo']}")
                lista_str = "\n".join(linhas)
                resp = (
                    f"🔍 *Seu(s) agendamento(s) ativo(s):*\n\n"
                    f"{lista_str}\n\n"
                    f"Para cancelar, envie *CANCELAR [data] [horário]*.\n"
                    f"Para remarcar, envie *REMARCAR [data atual] [horário atual] [nova data] [novo horário]*.\n"
                    f"Exemplo: *REMARCAR 19/11 19:30 20/11 09:45*\n\n"
                    f"📍 *Local:* {settings.get('endereco')}\n\n"
                )
            else:
                resp = (
                    f"Você não possui nenhum agendamento futuro no momento para este número.\n\n"
                    f"Digite *1* para ver os horários disponíveis e agendar!"
                )
            background_tasks.add_task(send_whatsapp_text, phone_number, resp, instance)
            return True

        if texto_lower in ("4", "endereco", "endereço", "localizacao", "localização", "onde fica", "horarios", "horários"):
            info_msg = (
                f"📍 *Endereço & Horários - {nome_loja}*\n\n"
                f"🏢 *Endereço:* {settings.get('endereco')}\n"
                f"⏰ *Funcionamento:* {settings.get('horarios_info')}\n\n"
                f"─────────────────\n"
                f"👉 Para agendar, digite *1*\n"
                f"👉 Para falar com atendente, digite *5*\n"
                f"👉 Para voltar ao menu, digite *0*"
            )
            background_tasks.add_task(send_whatsapp_text, phone_number, info_msg, instance)
            return True

        if texto_lower in ("5", "atendente", "falar", "humano", "recepcao", "recepção", "suporte", "operador"):
            humano_msg = (
                f"👤 *Aguarde um instante!*\n\n"
                f"Um de nossos atendentes da *{nome_loja}* já vai te responder por aqui."
            )
            background_tasks.add_task(send_whatsapp_text, phone_number, humano_msg, instance)
            return True

        return False
    except Exception as exc:
        print(f"[AgendamentoBot] Erro ao processar mensagem: {exc}")
        return False


@router.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "detail": "Corpo da requisição não é um JSON válido."}

    return await _process_whatsapp_webhook_payload(payload, background_tasks)


async def _process_whatsapp_webhook_payload(
    payload: dict,
    background_tasks: BackgroundTasks,
    send_auto_reply: bool = True,
    is_history_sync: bool = False,
):
    event = (payload.get("event") or "").lower().replace("_", ".").replace("-", ".")
    print(f"[Webhook] Evento recebido: '{event}' | Payload keys: {list(payload.keys())}")

    if event in ("presence.update", "presence.upsert"):
        presence_data = payload.get("data", {}) or {}
        if isinstance(presence_data, list):
            presence_data = presence_data[0] if presence_data and isinstance(presence_data[0], dict) else {}
        remote = presence_data.get("id") or presence_data.get("remoteJid") or presence_data.get("chatId") or ""
        presences = presence_data.get("presences") or {}
        presence = presence_data.get("presence") or presence_data.get("lastKnownPresence") or ""
        if isinstance(presences, dict) and presences:
            remote = remote or next(iter(presences.keys()))
            first_presence = next(iter(presences.values())) or {}
            if isinstance(first_presence, dict):
                presence = first_presence.get("lastKnownPresence") or first_presence.get("presence") or presence
        elif isinstance(presences, list) and presences:
            first_presence = presences[0] if isinstance(presences[0], dict) else {}
            remote = remote or first_presence.get("id") or first_presence.get("remoteJid") or ""
            presence = first_presence.get("lastKnownPresence") or first_presence.get("presence") or presence
        # Identificadores @lid precisam ser preservados, pois é assim que o
        # chamado foi salvo pelo webhook de mensagens.
        phone = remote.split(":")[0] if remote and "@lid" in remote else (remote.split("@")[0].split(":")[0] if remote else "")
        if remote and "@lid" in remote:
            phone = remote.split(":")[0]
        if phone:
            with Session(engine) as session:
                ticket = session.exec(select(Chamado).where(
                    Chamado.whatsapp_cliente == phone,
                    Chamado.status != "Resolvido",
                ).order_by(desc(Chamado.data_abertura))).first()
                if ticket:
                    is_typing = str(presence).lower() in ("composing", "recording")
                    ticket.whatsapp_typing_until = datetime.now() + timedelta(seconds=6) if is_typing else None
                    ticket.whatsapp_typing_media = str(presence).lower() == "recording"
                    session.add(ticket)
                    session.commit()
                    await manager.broadcast({
                        "event": "whatsapp_typing",
                        "ticket_id": ticket.id,
                        "typing": is_typing,
                        "media": str(presence).lower() == "recording",
                    })
        return {"status": "success", "presence": presence}

    if event == "messages.update":
        raw_updates = payload.get("data", [])
        updates = raw_updates if isinstance(raw_updates, list) else [raw_updates]
        payload_instance = payload.get("instance") or payload.get("instanceName") or payload.get("instance_name")
        changed = 0
        for item in updates:
            if not isinstance(item, dict):
                continue
            update_data = item.get("data") if isinstance(item.get("data"), dict) else item
            message_data = update_data.get("message") if isinstance(update_data.get("message"), dict) else {}
            key = update_data.get("key") or message_data.get("key") or {}
            # Evolution API v2.3.7 envia formato flat: keyId (ID WhatsApp real) + messageId (CUID2 interno).
            # O banco armazena o ID retornado pelo sendText (key.id = ID WhatsApp = keyId no formato flat).
            message_id = (
                key.get("id")
                or update_data.get("keyId")        # formato flat v2.3.7: ID real do WhatsApp
                or update_data.get("messageId")    # fallback: ID interno CUID2 da Evolution
            )
            # fromMe pode estar em key (nested) ou diretamente no update_data (flat v2.3.7)
            from_me_value = key.get("fromMe") if key else update_data.get("fromMe")
            if from_me_value is False:
                continue
            update = update_data.get("update") or update_data.get("messageUpdate") or {}
            raw_status = (update.get("status") or update.get("ack") or update.get("statusCode")) if isinstance(update, dict) else update
            # Formato flat v2.3.7: status pode vir diretamente em update_data.status
            if not raw_status:
                raw_status = update_data.get("status")
            status_text = str(raw_status or "").lower()
            print(f"[WhatsApp Status] Recebido evento: id={message_id} raw_status={raw_status} status_text={status_text} fromMe={from_me_value}")
            if status_text in ("4", "5", "read", "played", "read_ack"):
                message_status = "read"
            elif status_text in ("2", "3", "server_ack", "delivery_ack", "delivered"):
                message_status = "delivered"
            else:
                diagnostic_id = message_id or update_data.get("id") or "ausente"
                print(f"[WhatsApp Status] Atualização ignorada: id={str(diagnostic_id)[:24]} status={status_text or 'ausente'}")
                continue
            raw_inst = update_data.get("instance") or update_data.get("instanceName") or update_data.get("instanceId") or payload_instance
            instance = resolve_instance_name(raw_inst)
            with Session(engine) as session:
                interaction = None
                if message_id:
                    interaction = session.exec(select(ChamadoInteracao).where(
                        ChamadoInteracao.whatsapp_message_id == str(message_id),
                    ).order_by(desc(ChamadoInteracao.id))).first()
                if not interaction:
                    remote = key.get("remoteJid") or update_data.get("remoteJid") or ""
                    remote_number = (
                        key.get("senderPn") or key.get("phoneNumber") or key.get("participant")
                        or update_data.get("senderPn") or update_data.get("phoneNumber") or remote
                    )
                    phone = _normalize_contact_number(remote_number)
                    recent_ticket = None
                    if phone and instance:
                        recent_ticket = session.exec(select(Chamado).where(
                            Chamado.whatsapp_instance == str(instance),
                            Chamado.whatsapp_cliente == phone,
                        ).order_by(desc(Chamado.data_abertura))).first()
                    if not recent_ticket and remote and instance:
                        recent_interactions = session.exec(select(ChamadoInteracao).where(
                            ChamadoInteracao.whatsapp_remote_jid == str(remote),
                            ChamadoInteracao.whatsapp_status == "sent",
                            ChamadoInteracao.data_hora >= datetime.now(timezone.utc) - timedelta(minutes=10),
                        ).order_by(ChamadoInteracao.id)).all()
                        for candidate in recent_interactions:
                            candidate_ticket = session.get(Chamado, candidate.chamado_id)
                            if candidate_ticket and resolve_instance_name(candidate_ticket.whatsapp_instance) == instance:
                                recent_ticket = candidate_ticket
                                break
                    if recent_ticket:
                        pending_query = select(ChamadoInteracao).where(
                            ChamadoInteracao.chamado_id == recent_ticket.id,
                            ChamadoInteracao.usuario != recent_ticket.usuario,
                            ChamadoInteracao.whatsapp_status == "sent",
                            ChamadoInteracao.data_hora >= datetime.now(timezone.utc) - timedelta(minutes=10),
                        )
                        if message_id:
                            pending_query = pending_query.where(
                                (ChamadoInteracao.whatsapp_message_id.is_(None))
                                | (ChamadoInteracao.whatsapp_message_id != str(message_id))
                            )
                        interaction = session.exec(pending_query.order_by(ChamadoInteracao.id).limit(1)).first()
                        if interaction:
                            if message_id:
                                interaction.whatsapp_message_id = str(message_id)
                            remote_jid = key.get("remoteJid") or update_data.get("remoteJid")
                            if remote_jid:
                                interaction.whatsapp_remote_jid = str(remote_jid)
                            print(f"[WhatsApp Status] Associado por conversa: interação={interaction.id} status={message_status}")
                    if not interaction:
                        diagnostic_id = message_id or update_data.get("id") or "ausente"
                        remote_value = str(remote or "")
                        remote_type = "lid" if "@lid" in remote_value.lower() else "group" if "@g.us" in remote_value.lower() else "phone" if remote_value else "absent"
                        remote_tail = re.sub(r"\D", "", remote_value)[-4:]
                        key_fields = ",".join(sorted(str(field) for field in key.keys())) if isinstance(key, dict) else "none"
                        update_fields = ",".join(sorted(str(field) for field in update_data.keys()))
                        print(
                            f"[WhatsApp Status] Interação não encontrada: id={str(diagnostic_id)[:24]} "
                            f"status={message_status} instance={instance or 'absent'} remote_type={remote_type} "
                            f"remote_last4={remote_tail or 'none'} phone_resolved={bool(phone)} "
                            f"ticket_found={bool(recent_ticket)} key_fields={key_fields} update_fields={update_fields}"
                        )
                        continue
                ticket = session.get(Chamado, interaction.chamado_id)
                if not ticket:
                    continue
                ticket_inst = resolve_instance_name(ticket.whatsapp_instance)
                if instance and ticket_inst and ticket_inst != instance and str(ticket.whatsapp_instance) != str(raw_inst):
                    print(f"[WhatsApp Status] Instância divergente: id={str(message_id)[:24]} ticket={ticket_inst} webhook={instance}")
                    continue
                current_status = str(interaction.whatsapp_status or "sent").lower()
                if current_status == "read" or (current_status == "delivered" and message_status == "delivered"):
                    continue
                interaction.whatsapp_status = message_status
                session.add(interaction)
                session.commit()
                changed += 1
                print(f"[WhatsApp Status] Atualizado: interação={interaction.id} status={message_status}")
                await manager.broadcast({
                    "event": "whatsapp_message_status",
                    "ticket_id": ticket.id,
                    "msg_id": interaction.id,
                    "status": message_status,
                })
        return {"status": "success", "updated": changed}

    if event != "messages.upsert":
        return {"status": "ignored", "reason": f"evento nao mapeado: {event}"}

    # A Evolution API v2 pode enviar data como objeto único, lista de mensagens ou wrapper com lista de mensagens.
    raw_data = payload.get("data", {})
    instance_from_payload = None
    for k in ('instance', 'instanceName', 'instance_name', 'instanceId', 'instance_id'):
        instance_from_payload = payload.get(k)
        if instance_from_payload:
            break
        if isinstance(raw_data, dict):
            instance_from_payload = raw_data.get(k)
            if instance_from_payload:
                break
        if isinstance(raw_data, list):
            for item in raw_data:
                if isinstance(item, dict) and item.get(k):
                    instance_from_payload = item.get(k)
                    break
            if instance_from_payload:
                break

    if not instance_from_payload:
        print("[Webhook] Mensagem rejeitada: instancia ausente no evento")
        return {"status": "ignored", "reason": "instance_missing"}

    instance_from_payload = resolve_instance_name(instance_from_payload)
    configured_instances, _ = get_whatsapp_instances()
    configured_names = {str(item.get("instanceName")) for item in configured_instances}
    try:
        with Session(engine) as session:
            tenant_names = session.exec(text("""
                SELECT iw.instance_name
                FROM instancias_whatsapp_tenant iw
                JOIN empresas_atendimento e ON e.id = iw.empresa_atendimento_id
                WHERE iw.ativa = TRUE AND e.status = 'ativa'
            """)).all()
        configured_names.update(str(row[0]) for row in tenant_names if row[0])
    except Exception as exc:
        print(f"[Webhook] Nao foi possivel consultar instancias por empresa: {exc}")
    if str(instance_from_payload) not in configured_names:
        print(f"[Webhook] Mensagem rejeitada: instancia nao cadastrada '{instance_from_payload}'")
        return {"status": "ignored", "reason": "instance_not_configured"}

    # Uma instância de empresa só pode processar mensagens enquanto a empresa
    # estiver ativa. Isso evita que uma empresa suspensa continue abrindo
    # chamados ou que a mensagem fique sem tenant após a desativação.
    tenant_id = tenant_id_for_instance(instance_from_payload)
    if atendimento_multiempresa_enabled() and tenant_id is None:
        print(f"[Webhook] Mensagem rejeitada: instancia sem empresa ativa '{instance_from_payload}'")
        return {"status": "ignored", "reason": "instance_without_active_tenant"}

    if not _instance_is_connected(str(instance_from_payload)):
        print(f"[Webhook] Mensagem rejeitada: instancia '{instance_from_payload}' esta desconectada")
        return {"status": "ignored", "reason": "instance_disconnected"}

    messages_list = []

    if isinstance(raw_data, list):
        for item in raw_data:
            if isinstance(item, dict) and isinstance(item.get("messages"), list):
                messages_list.extend(item["messages"])
            else:
                messages_list.append(item)
    elif isinstance(raw_data, dict):
        if isinstance(raw_data.get("messages"), list):
            messages_list.extend(raw_data["messages"])
        else:
            messages_list.append(raw_data)

    if not messages_list and isinstance(payload.get("messages"), list):
        messages_list.extend(payload["messages"])

    if not messages_list and isinstance(payload.get("message"), dict):
        messages_list.append(payload["message"])

    if not messages_list:
        print(f"[Webhook] Nenhuma mensagem encontrada no payload. Payload keys: {list(payload.keys())}")
        return {"status": "ignored", "reason": "no_messages_found"}

    last_ticket_id = None

    _ensure_whatsapp_columns()

    for data in messages_list:
        message_obj = _unwrap_whatsapp_message(data.get("message", {}) or {})
        key = data.get("key", {}) or {}
        # A Evolution envia `fromMe` em formatos diferentes conforme a versão:
        # normalmente dentro de `key`, mas algumas versões usam o campo direto
        # no item ou deixam a chave dentro da própria mensagem. Se não lermos
        # todos eles, uma mensagem enviada pelo aparelho pode ser tratada como
        # recebida e disparar o bot para o próprio número.
        nested_message_key = message_obj.get("key") if isinstance(message_obj, dict) else {}
        if not isinstance(nested_message_key, dict):
            nested_message_key = {}
        from_me = bool(
            key.get("fromMe")
            if "fromMe" in key
            else data.get("fromMe")
            if "fromMe" in data
            else nested_message_key.get("fromMe", False)
        )
        message_received_at = _whatsapp_message_datetime(data.get("messageTimestamp"))

        # Ignora mensagens enviadas pelo próprio número para evitar loops
        if from_me:
            print(f"[Webhook] Mensagem própria ignorada (fromMe=True)")
            continue
        remote_jid = (
            key.get("remoteJid")
            or key.get("participant")
            or data.get("remoteJid")
            or data.get("from")
            or data.get("chatId")
            or (message_obj.get("key") or {}).get("remoteJid")
            or (message_obj.get("key") or {}).get("participant")
            or ""
        )
        print(f"[Webhook] remoteJid recebido: {remote_jid}")

        # Aceita qualquer número pessoal — exclui apenas grupos (@g.us)
        if not remote_jid:
            print(f"[Webhook] JID vazio ignorado: {remote_jid}")
            continue
        is_group = "@g.us" in str(remote_jid).lower()
        # Algumas versões omitem fromMe; compare também com o número real da
        # instância para impedir que mensagens próprias acionem o bot.
        if not is_group:
            remote_number = _normalize_contact_number(remote_jid)
            if remote_number and remote_number in _instance_connected_numbers(instance_from_payload):
                print(f"[Webhook] Mensagem própria ignorada pelo número conectado: {remote_number}")
                continue

        # Grupos não participam do fluxo de atendimento. Mensagens enviadas
        # por qualquer participante são ignoradas, sem criar ou reabrir ticket.
        # A Evolution API pode reenviar o mesmo webhook. Evita duplicar a interação.
        incoming_message_id = str(key.get("id") or "").strip()
        if incoming_message_id:
            with Session(engine) as dedupe_session:
                already_saved = dedupe_session.exec(
                    select(ChamadoInteracao).where(
                        ChamadoInteracao.whatsapp_message_id == incoming_message_id
                    )
                ).first()
            if already_saved:
                print(f"[Webhook] Mensagem duplicada ignorada: {incoming_message_id}")
                continue

        # Extrai o número limpo
        if is_group:
            # Preserve the complete group JID so the Central can identify it
            # and replies are sent back to the group, not to a participant.
            phone_number = str(remote_jid).strip()
        elif remote_jid.endswith("@lid"):
            phone_number = (
                key.get("senderPn") or key.get("phoneNumber") or data.get("senderPn")
                or data.get("phoneNumber") or remote_jid
            )
            phone_number = str(phone_number).split("@")[0].split(":")[0]
        else:
            phone_number = remote_jid.split("@")[0]
            # Remove o sufixo :XX que aparece em alguns JIDs de dispositivos múltiplos
            phone_number = phone_number.split(":")[0]

        reaction_payload = message_obj.get("reactionMessage") if isinstance(message_obj, dict) else None
        if isinstance(reaction_payload, dict):
            reaction_key = reaction_payload.get("key") or {}
            target_message_id = reaction_key.get("id") or reaction_payload.get("id")
            reaction_value = reaction_payload.get("text") or reaction_payload.get("reaction") or ""
            if target_message_id and reaction_value:
                with Session(engine) as session:
                    target_message = session.exec(select(ChamadoInteracao).where(ChamadoInteracao.whatsapp_message_id == str(target_message_id))).first()
                    if target_message:
                        reaction_text = str(reaction_value)[:32]
                        reactor_name = data.get("pushName") or data.get("notifyName") or data.get("senderName") or "Participante"
                        # O participant dentro de reactionMessage.key pertence à
                        # mensagem reagida, não necessariamente à pessoa que
                        # clicou na reação. Para identificar o reator, use a
                        # chave externa do evento (key) e os campos do payload.
                        participant = (
                            key.get("participant") or key.get("senderPn") or key.get("phoneNumber")
                            or data.get("participant") or data.get("senderPn") or data.get("phoneNumber") or ""
                        )
                        if reactor_name == "Participante" and participant:
                            reactor_name = str(participant).split("@")[0].split(":")[0]
                        try:
                            reaction_people = json.loads(target_message.reacao_detalhes or "[]")
                            if not isinstance(reaction_people, list): reaction_people = []
                        except Exception:
                            reaction_people = []
                        if target_message.reacao == reaction_text:
                            if not any(str(item.get("name")) == str(reactor_name) for item in reaction_people if isinstance(item, dict)):
                                reaction_people.append({"name": str(reactor_name), "emoji": reaction_text})
                            target_message.reacao_quantidade = max(len(reaction_people), (target_message.reacao_quantidade or 1))
                        else:
                            target_message.reacao = reaction_text
                            target_message.reacao_quantidade = 1
                            reaction_people = [{"name": str(reactor_name), "emoji": reaction_text}]
                        target_message.reacao_detalhes = json.dumps(reaction_people, ensure_ascii=False)
                        session.add(target_message)
                        session.commit()
                        background_tasks.add_task(manager.broadcast, {"event": "whatsapp_reaction", "ticket_id": target_message.chamado_id, "message_id": target_message.id, "reaction": target_message.reacao})
            continue

        customer_name = (data.get("groupName") or data.get("subject") or key.get("groupName") or key.get("subject") or "") if is_group else (data.get("pushName") or data.get("notifyName") or data.get("senderName") or "")
        if is_group and not customer_name:
            customer_name = get_whatsapp_group_name(phone_number, instance_from_payload) or "Grupo WhatsApp"

        # Extrai o texto de acordo com o tipo da mensagem (Baileys/Evolution v2)
        msg_text = ""
        if "conversation" in message_obj:
            msg_text = message_obj["conversation"]
        elif "extendedTextMessage" in message_obj:
            msg_text = message_obj["extendedTextMessage"].get("text", "")
        elif "albumMessage" in message_obj:
            album = message_obj.get("albumMessage") or {}
            caption = album.get("caption", "") if isinstance(album, dict) else ""
            msg_text = _save_incoming_media(message_obj, key, instance_from_payload, "image", caption)
        elif "imageMessage" in message_obj:
            caption = message_obj["imageMessage"].get("caption", "")
            msg_text = _save_incoming_media(message_obj, key, instance_from_payload, "image", caption)
        elif "videoMessage" in message_obj:
            caption = message_obj["videoMessage"].get("caption", "")
            media_kind = "gif" if message_obj["videoMessage"].get("gifPlayback") else "video"
            msg_text = _save_incoming_media(message_obj, key, instance_from_payload, media_kind, caption)
        elif "documentMessage" in message_obj:
            doc = message_obj["documentMessage"] or {}
            mime = str(doc.get("mimetype") or "").lower()
            fname = doc.get("fileName", "")
            if mime.startswith("image/"):
                caption = doc.get("caption", "") or fname
                msg_text = _save_incoming_media(message_obj, key, instance_from_payload, "image", caption)
            else:
                msg_text = _save_incoming_media(message_obj, key, instance_from_payload, "document", doc.get("caption", ""))
        elif "audioMessage" in message_obj:
            msg_text = _save_incoming_media(message_obj, key, instance_from_payload, "audio")
        elif "stickerMessage" in message_obj:
            msg_text = _save_incoming_media(message_obj, key, instance_from_payload, "sticker")
        elif "locationMessage" in message_obj:
            msg_text = "[Localização]"
        elif "contactMessage" in message_obj:
            msg_text = "[Contato]"
        elif "reactionMessage" in message_obj:
            # Reações não criam chamado
            print(f"[Webhook] Reação ignorada de {phone_number}")
            continue
        else:
            # Tipo desconhecido — loga para diagnóstico mas cria registro
            print(f"[Webhook] Tipo de mensagem desconhecido: {list(message_obj.keys())}")
            msg_text = _extract_whatsapp_text(message_obj) or "[Mensagem recebida]"

        if not customer_name:
            customer_name = phone_number

        if not msg_text:
            msg_text = "[Mensagem recebida]"

        print(f"[Webhook] Processando: {customer_name} ({phone_number}) -> '{msg_text}'")

        now_utc = datetime.now(timezone.utc)
        message_dt = message_received_at
        if message_dt.tzinfo is None:
            message_dt = message_dt.replace(tzinfo=timezone.utc)
        msg_age_seconds = (now_utc - message_dt).total_seconds()
        # Mensagens antigas: somente sync histórico OU mensagens com mais de 2 horas.
        # O threshold anterior (600s / 10min) era agressivo demais e causava
        # supressão de notificações WebSocket em mensagens legítimas que chegavam
        # com pequeno atraso ou drift de relógio entre containers.
        is_old_message = is_history_sync or (msg_age_seconds > 7200)
        print(f"[Webhook] Idade da msg: {msg_age_seconds:.0f}s | is_history_sync={is_history_sync} | is_old={is_old_message}")

        with Session(engine) as session:
            # 1) Tenta achar chamado ativo na MESMA instância
            if not is_group:
                legacy_group_message = session.exec(
                    select(ChamadoInteracao).where(
                        ChamadoInteracao.whatsapp_remote_jid.like(f"{phone_number}@g.us%")
                    ).order_by(desc(ChamadoInteracao.data_hora)).limit(1)
                ).first()
                if legacy_group_message:
                    is_group = True
                    phone_number = str(legacy_group_message.whatsapp_remote_jid)

            stmt = select(Chamado).where(
                Chamado.whatsapp_cliente == phone_number,
                Chamado.whatsapp_instance == instance_from_payload,
                Chamado.status != "Resolvido"
            ).order_by(desc(Chamado.data_abertura))
            chamado = session.exec(stmt).first()

            # 2) Se não encontrar, tenta buscar por legado (sem instância) ou qualquer
            if not chamado:
                stmt2 = select(Chamado).where(
                    Chamado.whatsapp_cliente == phone_number,
                    Chamado.whatsapp_instance == None,
                    Chamado.status != "Resolvido"
                ).order_by(desc(Chamado.data_abertura))
                chamado = session.exec(stmt2).first()

            # 3) Se for mensagem antiga e não achou chamado ativo, busca o chamado mais recente (mesmo Resolvido)
            # para salvar a mensagem no histórico SEM reabrir o chamado e SEM criar um novo
            if not chamado and is_old_message:
                chamado = session.exec(
                    select(Chamado).where(
                        Chamado.whatsapp_cliente == phone_number,
                    ).order_by(desc(Chamado.data_abertura))
                ).first()

            if chamado:
                # A Evolution pode entregar o evento da mensagem enviada antes
                # de o retorno do sendText gravar o ID local. Nesse intervalo,
                # o webhook chega sem fromMe e a mensagem do atendente seria
                # duplicada como recebida. Reconcilia pelo mesmo texto e ticket.
                if not from_me and not is_group:
                    outgoing_cutoff = message_received_at - timedelta(seconds=90)
                    recent_outgoing = session.exec(
                        select(ChamadoInteracao)
                        .where(
                            ChamadoInteracao.chamado_id == chamado.id,
                            ChamadoInteracao.mensagem == msg_text,
                            ChamadoInteracao.usuario != customer_name,
                            ChamadoInteracao.data_hora >= outgoing_cutoff,
                            ChamadoInteracao.whatsapp_status.in_(("sent", "delivered", "read")),
                        )
                        .order_by(desc(ChamadoInteracao.data_hora))
                        .limit(1)
                    ).first()
                    if recent_outgoing:
                        if key.get("id") and not recent_outgoing.whatsapp_message_id:
                            recent_outgoing.whatsapp_message_id = key.get("id")
                        if remote_jid and not recent_outgoing.whatsapp_remote_jid:
                            recent_outgoing.whatsapp_remote_jid = str(remote_jid)
                        session.add(recent_outgoing)
                        session.commit()
                        print(f"[Webhook] Evento da própria mensagem reconciliado com a interação #{recent_outgoing.id}")
                        continue
                if is_group and customer_name != "Grupo WhatsApp" and chamado.usuario != customer_name:
                    chamado.usuario = customer_name
                # Chamado encontrado: adiciona interação
                interacao = ChamadoInteracao(
                    chamado_id=chamado.id,
                    usuario=customer_name,
                    mensagem=msg_text,
                    whatsapp_message_id=key.get("id"),
                    whatsapp_remote_jid=str(remote_jid),
                    whatsapp_participant=str(key.get("senderPn") or key.get("phoneNumber") or key.get("participant") or data.get("senderPn") or data.get("phoneNumber") or data.get("participant") or "") or None,
                    data_hora=message_received_at
                )
                session.add(interacao)

                # Apenas incrementa não lidas se for mensagem nova em tempo real e o chamado estiver aberto
                if not is_old_message and chamado.status != "Resolvido":
                    chamado.unread_admin = (chamado.unread_admin or 0) + 1

                # Garanta que o chamado tem a instância registrada
                if not chamado.whatsapp_instance:
                    chamado.whatsapp_instance = instance_from_payload
                if chamado.empresa_atendimento_id is None:
                    chamado.empresa_atendimento_id = tenant_id_for_instance(instance_from_payload)
                session.commit()
                session.refresh(interacao)
                ticket_id = chamado.id
                print(f"[Webhook] Mensagem adicionada ao chamado #{ticket_id} (antiga={is_old_message})")

                # Dispara notificação WebSocket APENAS se for mensagem nova em tempo real
                if not is_old_message:
                    background_tasks.add_task(
                        manager.broadcast,
                        {
                            "event": "new_whatsapp_message",
                            "ticket_id": ticket_id,
                            "msg_id": interacao.id,
                            "whatsapp_instance": instance_from_payload,
                            "empresa_atendimento_id": chamado.empresa_atendimento_id,
                            "usuario": customer_name,
                            "mensagem": msg_text,
                            "data_hora": _display_datetime(interacao.data_hora).strftime("%d/%m/%Y %H:%M:%S")
                        }
                    )
                    if not is_group and send_auto_reply:
                        _handle_agendamento_bot_interaction(
                            phone_number=phone_number,
                            customer_name=customer_name,
                            msg_text=msg_text,
                            instance=instance_from_payload,
                            ticket_id=ticket_id,
                            is_new_ticket=False,
                            background_tasks=background_tasks,
                        )
            else:
                # Mensagens de grupos não devem abrir chamados automaticamente.
                # O grupo só continua sendo processado se já existir um chamado.
                # Abre novo chamado (se antiga, nasce com unread=0 e Resolvido para não poluir atendimento)
                auto_create_ticket = bool(get_whatsapp_config().get("WHATSAPP_AUTO_CREATE_TICKETS", True))
                initial_status = "Resolvido" if is_old_message else "Aberto"
                unread_count = 0 if is_old_message else 1

                chamado = Chamado(
                    usuario=customer_name,
                    titulo="Atendimento WhatsApp",
                    categoria="WhatsApp",
                    descricao=msg_text,
                    origem="WhatsApp",
                    whatsapp_cliente=phone_number,
                    whatsapp_instance=instance_from_payload,
                    empresa_atendimento_id=tenant_id_for_instance(instance_from_payload),
                    status=initial_status,
                    prioridade="Media",
                    visivel_suporte=auto_create_ticket,
                    unread_admin=unread_count,
                    data_abertura=message_received_at,
                )
                session.add(chamado)
                session.commit()
                session.refresh(chamado)
                ticket_id = chamado.id
                print(f"[Webhook] Novo chamado criado: #{ticket_id} para {customer_name} (status={initial_status}, antiga={is_old_message})")

                interacao = ChamadoInteracao(
                    chamado_id=ticket_id,
                    usuario=customer_name,
                    mensagem=msg_text,
                    whatsapp_message_id=key.get("id"),
                    whatsapp_remote_jid=str(remote_jid),
                    whatsapp_participant=str(key.get("senderPn") or key.get("phoneNumber") or key.get("participant") or data.get("senderPn") or data.get("phoneNumber") or data.get("participant") or "") or None,
                    data_hora=message_received_at
                )
                session.add(interacao)
                session.commit()

                # Dispara notificação WebSocket e auto-reply APENAS se for mensagem nova em tempo real
                if not is_old_message:
                    background_tasks.add_task(
                        manager.broadcast,
                        {
                            "event": "new_whatsapp_chat",
                            "ticket_id": ticket_id,
                            "whatsapp_instance": instance_from_payload,
                            "empresa_atendimento_id": chamado.empresa_atendimento_id,
                            "usuario": customer_name,
                            "mensagem": msg_text,
                            "prioridade": chamado.prioridade,
                            "data_hora": _display_datetime(chamado.data_abertura).strftime("%d/%m/%Y %H:%M:%S")
                        }
                    )

                    bot_handled = False
                    if not is_group and send_auto_reply:
                        bot_handled = _handle_agendamento_bot_interaction(
                            phone_number=phone_number,
                            customer_name=customer_name,
                            msg_text=msg_text,
                            instance=instance_from_payload,
                            ticket_id=ticket_id,
                            is_new_ticket=True,
                            background_tasks=background_tasks,
                        )

                    # Auto-resposta padrão de boas-vindas se o bot não atendeu
                    if not bot_handled and send_auto_reply and tenant_id_for_instance(instance_from_payload) != 1:
                        welcome_msg = f"Olá, {customer_name}! Seu atendimento foi registrado sob o chamado #{ticket_id}. Um de nossos operadores irá atendê-lo em breve."
                        background_tasks.add_task(send_whatsapp_text, phone_number, welcome_msg, instance_from_payload)

            last_ticket_id = ticket_id

    return {"status": "success", "ticket_id": last_ticket_id}


async def _fetch_evolution_message_page(
    base_url: str,
    token: str,
    instance: str,
    since: datetime,
    through: datetime,
    page: int,
    page_size: int,
):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["apikey"] = token
    response = await asyncio.to_thread(
        requests.post,
        f"{base_url}/chat/findMessages/{instance}",
        headers=headers,
        json={
            "where": {
                "messageTimestamp": {
                    "gte": since.isoformat(),
                    "lte": through.isoformat(),
                }
            },
            "page": page,
            "offset": page_size,
        },
        timeout=(5, 30),
    )
    if not response.ok:
        raise RuntimeError(f"Evolution findMessages respondeu HTTP {response.status_code}")

    payload = response.json()
    message_data = payload.get("messages") if isinstance(payload, dict) else None
    if isinstance(message_data, list):
        return message_data, 1
    if not isinstance(message_data, dict):
        raise ValueError("Resposta inválida de Evolution findMessages.")

    records = message_data.get("records")
    if not isinstance(records, list):
        raise ValueError("Evolution findMessages não retornou a lista de mensagens.")
    try:
        pages = int(message_data.get("pages") or 0)
    except (TypeError, ValueError):
        pages = 0
    return records, max(pages, 1 if records else 0)


async def _sync_whatsapp_instance_history(instance_name: str):
    instances, _ = get_whatsapp_instances()
    if not any(item["instanceName"] == instance_name for item in instances):
        return
    if not await asyncio.to_thread(_instance_is_connected, instance_name):
        return

    _ensure_whatsapp_columns()
    through = datetime.now(timezone.utc)
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT last_synced_at FROM whatsapp_message_sync_state "
                "WHERE instance_name = :instance_name"
            ),
            {"instance_name": instance_name},
        ).first()

    if row and row[0]:
        last_synced_at = row[0]
        if last_synced_at.tzinfo is None:
            last_synced_at = last_synced_at.replace(tzinfo=timezone.utc)
        since = min(last_synced_at - timedelta(seconds=1), through - timedelta(seconds=1))
    else:
        since = through - timedelta(days=7)

    base_url, token, resolved_instance = get_evolution_api_endpoints(instance_name)
    if not base_url:
        return

    page_size = 100
    records, page_count = await _fetch_evolution_message_page(
        base_url, token, resolved_instance, since, through, 1, page_size
    )

    for page in range(page_count, 0, -1):
        if page == 1:
            page_records = records
        else:
            page_records, _ = await _fetch_evolution_message_page(
                base_url, token, resolved_instance, since, through, page, page_size
            )

        # A página da Evolution vem da mais nova para a mais antiga.
        historical_messages = [
            item for item in reversed(page_records)
            if isinstance(item, dict)
            and isinstance(item.get("key"), dict)
            and not item["key"].get("fromMe")
        ]
        if not historical_messages:
            continue

        background_tasks = BackgroundTasks()
        await _process_whatsapp_webhook_payload(
            {
                "event": "messages.upsert",
                "instance": instance_name,
                "data": historical_messages,
            },
            background_tasks,
            send_auto_reply=False,
            is_history_sync=True,
        )
        await background_tasks()

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO whatsapp_message_sync_state (instance_name, last_synced_at)
                VALUES (:instance_name, :last_synced_at)
                ON CONFLICT (instance_name)
                DO UPDATE SET last_synced_at = EXCLUDED.last_synced_at
                """
            ),
            {"instance_name": instance_name, "last_synced_at": through},
        )

async def whatsapp_history_recovery_loop():
    await asyncio.sleep(15)
    while True:
        try:
            instances, _ = get_whatsapp_instances()
            for item in instances:
                instance_name = item["instanceName"]
                try:
                    await _sync_whatsapp_instance_history(instance_name)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(
                        f"[WhatsApp History] Falha ao sincronizar "
                        f"'{instance_name}': {exc}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[WhatsApp History] Falha ao listar instâncias: {exc}")
        await asyncio.sleep(60)
