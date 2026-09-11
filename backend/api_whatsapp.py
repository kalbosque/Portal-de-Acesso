import os
import json
import time
import base64
import re
import uuid
import requests
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse, urlunparse
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Body, UploadFile, File
from sqlalchemy import text
from sqlmodel import Session, select, desc

from models import Chamado, ChamadoInteracao, Usuario, ContatoWhatsApp
from database import engine
from auth_utils import get_signed_cookie, normalize_permissions
from websocket_manager import manager

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

_whatsapp_columns_ready = False
_connected_map_cache = {"expires_at": 0.0, "value": {}}

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


def get_whatsapp_webhook_target(config: dict) -> str:
    target = str(config.get("WHATSAPP_WEBHOOK_TARGET", "") or "").strip()
    if target:
        if target.endswith("/api/whatsapp/webhook"):
            return target
        return target.rstrip("/") + "/api/whatsapp/webhook"

    url = str(config.get("URL_ATENDIMENTO", "") or "").strip()
    if url:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return urlunparse((parsed.scheme, parsed.netloc, "/api/whatsapp/webhook", "", "", ""))

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
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS reacao VARCHAR(32) NULL",
        "ALTER TABLE contatos_whatsapp ADD COLUMN IF NOT EXISTS status_interno VARCHAR(40) DEFAULT 'Normal'"
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
        
        if not instance:
            instance = "printdash"
            
        normalized.append({"instanceName": instance, "label": instance})

    default_instance = config.get("WHATSAPP_DEFAULT_INSTANCE") or (normalized[0]["instanceName"] if normalized else None)
    return normalized, default_instance


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

    if instance_name:
        instance = instance_name
    elif not instance:
        instance = get_default_whatsapp_instance(config)
            
    if not instance:
        instance = "printdash"
    return base_url, wa_token, instance


def get_whatsapp_group_name(group_jid: str, instance_name: Optional[str] = None) -> Optional[str]:
    """Busca o nome atual de um grupo na Evolution API."""
    if not group_jid or not str(group_jid).lower().endswith("@g.us"):
        return None
    try:
        base_url, wa_token, resolved = get_evolution_api_endpoints(instance_name)
        if not base_url or not resolved:
            return None
        response = requests.get(
            f"{base_url}/group/findGroupInfo/{resolved}",
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
                    return name
    except Exception as exc:
        print(f"[WhatsApp] Não foi possível obter nome do grupo {group_jid}: {exc}")
    return None


def send_whatsapp_text(number: str, text: str, instance: Optional[str] = None) -> bool:
    base_url, wa_token, instance = get_evolution_api_endpoints(instance)
    if not base_url:
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


def send_whatsapp_text_for_interaction(interaction_id: int, number: str, text: str, instance: Optional[str] = None) -> bool:
    """Envia a mensagem e salva o ID retornado pelo WhatsApp na interação local."""
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(instance)
    if not base_url:
        return False
    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    payload = {"number": number, "text": text, "delay": 1200}
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
        key = result.get("key") or (result.get("message") or {}).get("key") or {}
        message_id = key.get("id") or result.get("messageId") or result.get("id")
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


def send_whatsapp_reaction(number: str, message_id: str, reaction: str, instance: Optional[str] = None, remote_jid: Optional[str] = None) -> bool:
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(instance)
    if not base_url or not message_id:
        return False
    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
    target_jid = str(remote_jid or number or "")
    if "@" not in target_jid:
        target_jid = f"{target_jid}@s.whatsapp.net"
    payload = {"key": {"remoteJid": target_jid, "fromMe": False, "id": message_id}, "reaction": reaction}
    try:
        response = requests.post(f"{base_url}/message/sendReaction/{resolved_instance}", json=payload, headers=headers, timeout=8)
        if response.status_code in (200, 201):
            return True
        print(f"[WhatsApp API] Erro ao enviar reação: {response.status_code} - {response.text[:300]}")
    except Exception as exc:
        print(f"[WhatsApp API] Erro ao enviar reação: {exc}")
    return False


@router.post("/message/reaction")
def react_to_whatsapp_message(payload: dict = Body(...), request: Request = None):
    _require_atendimento_access(request)
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
        ok = send_whatsapp_reaction(
            chamado.whatsapp_cliente,
            interaction.whatsapp_message_id,
            reaction,
            chamado.whatsapp_instance,
            interaction.whatsapp_remote_jid,
        )
        if not ok:
            raise HTTPException(status_code=502, detail="Não foi possível enviar a reação ao WhatsApp")
        interaction.reacao = reaction
        session.add(interaction)
        session.commit()
        return {"success": True, "reaction": reaction}


def send_whatsapp_media(number: str, media_base64: str, media_type: str, mime_type: str, filename: str = "arquivo", caption: str = "", instance: Optional[str] = None) -> bool:
    """Envia imagem, áudio, vídeo ou documento pela Evolution API."""
    base_url, wa_token, resolved_instance = get_evolution_api_endpoints(instance)
    if not base_url:
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
            return True
        print(f"[WhatsApp API] Erro ao enviar mídia: {response.status_code} - {response.text[:300]}")
    except Exception as exc:
        print(f"[WhatsApp API] Erro ao enviar mídia: {exc}")
    return False


def _find_base64(value):
    if isinstance(value, dict):
        for key in ("base64", "data", "fileBase64"):
            candidate = value.get(key)
            if isinstance(candidate, str) and (candidate.startswith("data:") or len(candidate) > 200):
                return candidate
        for child in value.values():
            found = _find_base64(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_base64(child)
            if found:
                return found
    return None


def _save_incoming_media(message_obj: dict, message_key: dict, instance: str, media_kind: str, caption: str = ""):
    """Salva mídia recebida e retorna um marcador renderizável no frontend."""
    media_node = message_obj.get(f"{media_kind}Message", {}) or {}
    if not media_node and media_kind == "gif":
        media_node = message_obj.get("videoMessage", {}) or message_obj.get("imageMessage", {}) or {}
    raw_media = _find_base64(media_node) or _find_base64(message_obj)

    if not raw_media and message_key.get("id"):
        base_url, wa_token, resolved = get_evolution_api_endpoints(instance)
        if base_url:
            try:
                response = requests.post(
                    f"{base_url}/chat/getBase64FromMediaMessage/{resolved}",
                    headers={"apikey": wa_token, "Content-Type": "application/json"},
                    json={"message": {"key": {"id": message_key["id"]}}},
                    timeout=15,
                )
                if response.ok:
                    raw_media = _find_base64(response.json())
            except Exception as exc:
                print(f"[Webhook] Falha ao obter mídia {media_kind}: {exc}")

    if not raw_media:
        return f"[Mídia não disponível: {media_kind}]"

    try:
        mime = media_node.get("mimetype") or ("audio/ogg" if media_kind == "audio" else ("video/mp4" if media_kind in ("video", "gif") else "image/jpeg"))
        extension = "ogg" if media_kind == "audio" else ("mp4" if media_kind in ("video", "gif") and "video" in mime else ("gif" if "gif" in mime else "jpg"))
        if raw_media.startswith("data:"):
            header, raw_media = raw_media.split(",", 1)
            mime = header.split(";")[0].replace("data:", "") or mime
            extension = mime.split("/")[-1].replace("jpeg", "jpg")
        raw_media = re.sub(r"\s+", "", raw_media)
        binary = base64.b64decode(raw_media)
        media_dir = os.path.join("public_html", "uploads", "whatsapp_media")
        os.makedirs(media_dir, exist_ok=True)
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(message_key.get("id") or int(time.time())))
        filename = f"{safe_id}.{extension}"
        with open(os.path.join(media_dir, filename), "wb") as output:
            output.write(binary)
        return json.dumps({"__wa_media__": True, "type": media_kind, "url": f"/uploads/whatsapp_media/{filename}", "mime": mime, "caption": caption}, ensure_ascii=False)
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


def _require_admin(request: Request):
    user_role = get_signed_cookie(request, "user_role")
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso exclusivo para administradores")


@router.get("/instances")
def list_whatsapp_instances(request: Request):
    _require_atendimento_access(request)
    instances, default_instance = get_whatsapp_instances()

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
        "connected": connected_count
    }


@router.post("/instances/save")
def save_whatsapp_instances(request: Request, payload: dict = Body(...)):
    _require_admin(request)

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
        if chamado and chamado.whatsapp_cliente and "@lid" in str(chamado.whatsapp_cliente):
            try:
                base_url, wa_token, resolved = get_evolution_api_endpoints(chamado.whatsapp_instance)
                if base_url:
                    response = requests.post(
                        f"{base_url}/chat/findContacts/{resolved}",
                        headers={"apikey": wa_token or "", "Content-Type": "application/json"},
                        json={"where": {}, "take": 1000, "skip": 0, "orderBy": {}},
                        timeout=8,
                    )
                    contacts = response.json() if response.ok and isinstance(response.json(), list) else []
                    lid = str(chamado.whatsapp_cliente).split("@")[0]
                    match = next((item for item in contacts if isinstance(item, dict) and str(item.get("id") or "").split("@")[0] == lid and item.get("number")), None)
                    if match:
                        chamado.whatsapp_cliente = str(match["number"]).split("@")[0].split(":")[0]
                        session.add(chamado)
                        session.commit()
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
                "data_hora": it.data_hora.strftime("%d/%m/%Y %H:%M:%S")
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
                    "data_abertura": item.data_abertura.strftime("%d/%m/%Y %H:%M"),
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
            "data_abertura": chamado.data_abertura.strftime("%d/%m/%Y %H:%M:%S"),
            "assigned_user": chamado.assigned_user,
            "nota_interna": chamado.nota_tecnica or "",
            "status_interno": (contato.status_interno if contato and contato.status_interno else "Normal"),
            "last_messages": last_messages,
            "previous_tickets": previous_tickets
        }


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
    _require_atendimento_access(request)
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
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado")
        
    base_url, wa_token, instance = get_evolution_api_endpoints(instance)
    if not base_url:
        raise HTTPException(status_code=400, detail="Evolution API não configurada.")
        
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
                    # Remove da config
                    config = get_whatsapp_config()
                    instances = config.get("WHATSAPP_INSTANCES", [])
                    if not isinstance(instances, list):
                        instances = []
                    new_instances = [i for i in instances if (i.get("instanceName") if isinstance(i, dict) else i) != instance]
                    config["WHATSAPP_INSTANCES"] = new_instances
                    # update default if needed
                    if config.get("WHATSAPP_DEFAULT_INSTANCE") == instance:
                        config["WHATSAPP_DEFAULT_INSTANCE"] = new_instances[0].get("instanceName") if new_instances else None
                    save_whatsapp_config(config)
                    
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
            for inst in instances:
                name = inst.get('instanceName')
                if not name:
                    continue
                try:
                    base_url, wa_token, resolved = get_evolution_api_endpoints(name)
                    if base_url:
                        headers = {}
                        if wa_token:
                            headers['apikey'] = wa_token
                        resp = requests.get(f"{base_url}/instance/connectionState/{resolved}", headers=headers, timeout=3)
                        if resp.status_code == 200:
                            data = resp.json()
                            connected_map[name] = set(_extract_connected_numbers(data))
                        else:
                            connected_map[name] = set()
                    else:
                        connected_map[name] = set()
                except Exception:
                    connected_map[name] = set()
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
        
        resultado = []
        for c in chamados:
            # Busca a última mensagem do chamado
            last_msg_stmt = select(ChamadoInteracao).where(
                ChamadoInteracao.chamado_id == c.id
            ).order_by(desc(ChamadoInteracao.data_hora)).limit(1)
            
            last_msg = session.exec(last_msg_stmt).first()
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

            resultado.append({
                "id": c.id,
                "usuario": c.usuario or (f"Grupo WhatsApp · {str(c.whatsapp_cliente).split('@')[0]}" if is_group_chat else "Contato sem nome"),
                "is_group": is_group_chat,
                "whatsapp_instance": c.whatsapp_instance,
                "visivel_suporte": bool(c.visivel_suporte),
                "connected": is_connected,
                "whatsapp_cliente": c.whatsapp_cliente,
                "categoria": c.categoria,
                "status": c.status,
                "prioridade": c.prioridade,
                "assigned_user": c.assigned_user,
                # A fila Ã© compartilhada: todos os perfis autorizados precisam
                # enxergar o contador de mensagens pendentes.
                "unread_admin": c.unread_admin or 0,
                "data_abertura": c.data_abertura.strftime("%d/%m/%Y %H:%M"),
                "ultima_mensagem": last_msg.mensagem if last_msg else c.descricao,
                "data_ultima_mensagem": (last_msg.data_hora if last_msg else c.data_abertura).strftime("%d/%m %H:%M")
            })
            
        return resultado


@router.get("/contacts")
def get_whatsapp_contacts(request: Request, instance: Optional[str] = None):
    _require_atendimento_access(request)
    _ensure_whatsapp_columns()
    base_url, wa_token, resolved = get_evolution_api_endpoints(instance)
    if not base_url:
        raise HTTPException(status_code=400, detail="WhatsApp não configurado")
    try:
        response = requests.post(
            f"{base_url}/chat/findContacts/{resolved}",
            headers={"apikey": wa_token or "", "Content-Type": "application/json"},
            json={"where": {}, "take": 1000, "skip": 0, "orderBy": {}},
            timeout=20,
        )
        if not response.ok:
            raise HTTPException(status_code=502, detail="Não foi possível sincronizar os contatos")
        payload = response.json()
        if isinstance(payload, list):
            contacts = payload
        elif isinstance(payload, dict):
            contacts = payload.get("contacts") or payload.get("data") or payload.get("results") or []
            if isinstance(contacts, dict):
                contacts = contacts.get("contacts") or contacts.get("data") or []
        else:
            contacts = []
        synced = [{
            "id": item.get("id") or item.get("number"),
            "name": item.get("pushName") or item.get("name") or item.get("number") or "Sem nome",
            "number": item.get("number") or str(item.get("id") or "").split("@")[0],
            "profile_picture": item.get("profilePictureUrl"),
            "instance": resolved,
        } for item in contacts if isinstance(item, dict) and (item.get("number") or item.get("id"))]
        with Session(engine) as session:
            local = session.exec(select(ContatoWhatsApp).order_by(ContatoWhatsApp.nome)).all()
        existing = {str(item.get("number")) for item in synced}
        synced.extend({"id": item.id, "name": item.nome, "number": item.numero, "company": item.empresa or "", "note": item.observacao or "", "instance": item.whatsapp_instance or resolved, "local": True} for item in local if item.numero not in existing)
        return synced
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao sincronizar contatos: {exc}")


@router.post("/contacts/start")
def start_whatsapp_contact(payload: dict = Body(...), request: Request = None, background_tasks: BackgroundTasks = None):
    _require_atendimento_access(request)
    user_name, _ = _get_user(request)
    number = str(payload.get("number") or "").strip()
    contact_name = str(payload.get("name") or number).strip()
    message_text = str(payload.get("message") or "").strip()
    instance = str(payload.get("instance") or get_default_whatsapp_instance(get_whatsapp_config()) or "").strip()
    if not number:
        raise HTTPException(status_code=400, detail="Número do contato é obrigatório")
    with Session(engine) as session:
        chamado = session.exec(select(Chamado).where(
            Chamado.whatsapp_cliente == number,
            Chamado.whatsapp_instance == instance,
            Chamado.status != "Resolvido",
        ).order_by(desc(Chamado.data_abertura))).first()
        if not chamado:
            chamado = Chamado(usuario=contact_name, titulo="Atendimento WhatsApp", categoria="WhatsApp", descricao=message_text or "Conversa iniciada pelo atendente", origem="WhatsApp", whatsapp_cliente=number, whatsapp_instance=instance, status="Aberto", prioridade="Media", visivel_suporte=True, assigned_user=user_name)
            session.add(chamado)
            session.commit()
            session.refresh(chamado)
        if message_text:
            interaction = ChamadoInteracao(chamado_id=chamado.id, usuario=user_name, mensagem=message_text, whatsapp_status="sent")
            session.add(interaction)
            session.commit()
            if background_tasks:
                background_tasks.add_task(send_whatsapp_text, number, f"*{user_name}*:\n{message_text}", instance)
    return {"success": True, "ticket_id": chamado.id}


@router.post("/contacts/local")
def create_local_contact(payload: dict = Body(...), request: Request = None):
    _require_atendimento_access(request)
    name = str(payload.get("name") or "").strip()
    number = "".join(ch for ch in str(payload.get("number") or "") if ch.isdigit())
    if not name or len(number) < 8:
        raise HTTPException(status_code=400, detail="Informe nome e um número válido")
    with Session(engine) as session:
        contact = ContatoWhatsApp(nome=name, numero=number, empresa=str(payload.get("company") or "").strip() or None, observacao=str(payload.get("note") or "").strip() or None, whatsapp_instance=str(payload.get("instance") or get_default_whatsapp_instance(get_whatsapp_config()) or ""))
        session.add(contact)
        session.commit()
        session.refresh(contact)
        return {"success": True, "id": contact.id}


@router.put("/contacts/local/{contact_id}")
def update_local_contact(contact_id: int, payload: dict = Body(...), request: Request = None):
    _require_atendimento_access(request)
    name = str(payload.get("name") or "").strip()
    number = "".join(ch for ch in str(payload.get("number") or "") if ch.isdigit())
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
    with Session(engine) as session:
        users = session.exec(
            select(Usuario)
            .where(
                Usuario.status_conta == "ativo",
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

@router.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "detail": "Corpo da requisição não é um JSON válido."}

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
        changed = 0
        for item in updates:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or {}
            remote = key.get("remoteJid") or item.get("remoteJid") or ""
            update = item.get("update") or item.get("status") or {}
            raw_status = update.get("status") if isinstance(update, dict) else update
            status_text = str(raw_status or "").lower()
            if status_text in ("4", "5", "read", "played", "read_ack"):
                message_status = "read"
            elif status_text in ("2", "3", "server_ack", "delivery_ack", "delivered"):
                message_status = "delivered"
            else:
                continue
            is_group_remote = str(remote).lower().endswith("@g.us")
            phone = str(remote) if is_group_remote else (remote.split("@")[0].split(":")[0] if remote else "")
            if remote.endswith("@lid"):
                phone = remote.split(":")[0]
            if not phone:
                continue
            with Session(engine) as session:
                ticket = session.exec(select(Chamado).where(
                    Chamado.whatsapp_cliente == phone,
                    Chamado.status != "Resolvido",
                ).order_by(desc(Chamado.data_abertura))).first()
                if not ticket:
                    continue
                own_messages = session.exec(select(ChamadoInteracao).where(
                    ChamadoInteracao.chamado_id == ticket.id,
                    ChamadoInteracao.usuario != ticket.usuario,
                    ChamadoInteracao.whatsapp_status != "read",
                )).all()
                for own_message in own_messages:
                    own_message.whatsapp_status = message_status
                    session.add(own_message)
                    changed += 1
                session.commit()
                await manager.broadcast({"event": "whatsapp_message_status", "ticket_id": ticket.id, "status": message_status})
        return {"status": "success", "updated": changed}

    if event != "messages.upsert":
        return {"status": "ignored", "reason": f"evento nao mapeado: {event}"}

    # A Evolution API v2 pode enviar data como objeto único, lista de mensagens ou wrapper com lista de mensagens.
    raw_data = payload.get("data", {})
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

    # Tenta extrair o nome da instância do próprio payload (se presente)
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
        instance_from_payload = get_default_whatsapp_instance(get_whatsapp_config())

    last_ticket_id = None

    _ensure_whatsapp_columns()

    for data in messages_list:
        message_obj = data.get("message", {}) or {}
        key = data.get("key", {}) or {}
        from_me = key.get("fromMe", False)

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
                        target_message.reacao = str(reaction_value)[:32]
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
        elif "imageMessage" in message_obj:
            caption = message_obj["imageMessage"].get("caption", "")
            msg_text = _save_incoming_media(message_obj, key, instance_from_payload, "image", caption)
        elif "videoMessage" in message_obj:
            caption = message_obj["videoMessage"].get("caption", "")
            media_kind = "gif" if message_obj["videoMessage"].get("gifPlayback") else "video"
            msg_text = _save_incoming_media(message_obj, key, instance_from_payload, media_kind, caption)
        elif "documentMessage" in message_obj:
            fname = message_obj["documentMessage"].get("fileName", "")
            msg_text = f"[Documento]{': ' + fname if fname else ''}"
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
            msg_text = "[Mensagem]"

        if not customer_name:
            customer_name = phone_number

        if not msg_text:
            msg_text = "[Mensagem]"

        print(f"[Webhook] Processando: {customer_name} ({phone_number}) -> '{msg_text}'")

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
                    Chamado.status != "Resolvido"
                ).order_by(desc(Chamado.data_abertura))
                chamado = session.exec(stmt2).first()

            if chamado:
                if is_group and customer_name != "Grupo WhatsApp" and chamado.usuario != customer_name:
                    chamado.usuario = customer_name
                own_messages = session.exec(select(ChamadoInteracao).where(
                    ChamadoInteracao.chamado_id == chamado.id,
                    ChamadoInteracao.usuario != customer_name,
                    ChamadoInteracao.whatsapp_status != "read",
                )).all()
                for own_message in own_messages:
                    own_message.whatsapp_status = "read"
                    session.add(own_message)
                # Chamado ativo: adiciona interação
                interacao = ChamadoInteracao(
                    chamado_id=chamado.id,
                    usuario=customer_name,
                    mensagem=msg_text,
                    whatsapp_message_id=key.get("id"),
                    whatsapp_remote_jid=str(remote_jid),
                    data_hora=datetime.now()
                )
                session.add(interacao)
                chamado.unread_admin = (chamado.unread_admin or 0) + 1
                # Garanta que o chamado tem a instância registrada
                if not chamado.whatsapp_instance:
                    chamado.whatsapp_instance = instance_from_payload
                session.commit()
                session.refresh(interacao)
                ticket_id = chamado.id
                print(f"[Webhook] Mensagem adicionada ao chamado #{ticket_id}")

                background_tasks.add_task(
                    manager.broadcast,
                    {
                        "event": "new_whatsapp_message",
                        "ticket_id": ticket_id,
                        "msg_id": interacao.id,
                        "usuario": customer_name,
                        "mensagem": msg_text,
                        "data_hora": interacao.data_hora.strftime("%d/%m/%Y %H:%M:%S")
                    }
                )
            else:
                # Mensagens de grupos não devem abrir chamados automaticamente.
                # O grupo só continua sendo processado se já existir um chamado.
                # Abre novo chamado
                auto_create_ticket = bool(get_whatsapp_config().get("WHATSAPP_AUTO_CREATE_TICKETS", True))
                chamado = Chamado(
                    usuario=customer_name,
                    titulo="Atendimento WhatsApp",
                    categoria="WhatsApp",
                    descricao=msg_text,
                    origem="WhatsApp",
                    whatsapp_cliente=phone_number,
                    whatsapp_instance=instance_from_payload,
                    status="Aberto",
                    prioridade="Media",
                    visivel_suporte=auto_create_ticket,
                    unread_admin=1
                )
                session.add(chamado)
                session.commit()
                session.refresh(chamado)
                ticket_id = chamado.id
                print(f"[Webhook] Novo chamado criado: #{ticket_id} para {customer_name}")

                interacao = ChamadoInteracao(
                    chamado_id=ticket_id,
                    usuario=customer_name,
                    mensagem=msg_text,
                    whatsapp_message_id=key.get("id"),
                    whatsapp_remote_jid=str(remote_jid),
                    data_hora=datetime.now()
                )
                session.add(interacao)
                session.commit()

                background_tasks.add_task(
                    manager.broadcast,
                    {
                        "event": "new_whatsapp_chat",
                        "ticket_id": ticket_id,
                        "usuario": customer_name,
                        "mensagem": msg_text,
                        "prioridade": chamado.prioridade,
                        "data_hora": chamado.data_abertura.strftime("%d/%m/%Y %H:%M:%S")
                    }
                )

                # Auto-resposta de boas-vindas
                welcome_msg = f"Olá, {customer_name}! Seu atendimento foi registrado sob o chamado #{ticket_id}. Um de nossos operadores irá atendê-lo em breve."
                background_tasks.add_task(send_whatsapp_text, phone_number, welcome_msg, instance_from_payload)

            last_ticket_id = ticket_id

    return {"status": "success", "ticket_id": last_ticket_id}
