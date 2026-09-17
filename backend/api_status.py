import os
import uuid
import requests
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from auth_utils import get_signed_cookie
from database import engine
from models import StatusEmpresa
from api_whatsapp import get_evolution_api_endpoints, get_whatsapp_instances

router = APIRouter()


def _admin(request: Request) -> str:
    if get_signed_cookie(request, "user_role") != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem publicar Status.")
    return get_signed_cookie(request, "user_name") or "admin"


def _payload(status: StatusEmpresa) -> dict:
    return {
        "id": status.id,
        "titulo": status.titulo,
        "mensagem": status.mensagem or "",
        "media_url": status.media_url,
        "media_tipo": status.media_tipo,
        "cor": status.cor,
        "criado_em": status.criado_em.strftime("%d/%m/%Y %H:%M") if status.criado_em else "",
        "expira_em": status.expira_em.isoformat() if status.expira_em else None,
    }


def _public_media_url(request: Request, media_url: Optional[str]) -> Optional[str]:
    if not media_url:
        return None
    relative = media_url.removeprefix("uploads/")
    return str(request.url_for("uploads", path=relative))


def _publish_whatsapp_status(request: Request, titulo: str, mensagem: str, media_url: Optional[str], media_tipo: Optional[str], cor: str) -> dict:
    """Publica o mesmo conteúdo no Status do WhatsApp conectado."""
    instances, default_instance = get_whatsapp_instances()
    instance = default_instance or (instances[0]["instanceName"] if instances else None)
    if not instance:
        return {"ok": False, "detail": "Nenhuma instância WhatsApp configurada."}

    base_url, token, resolved = get_evolution_api_endpoints(instance)
    if not base_url:
        return {"ok": False, "detail": "Evolution API não configurada."}

    if media_url:
        content = _public_media_url(request, media_url)
        status_type = "video" if media_tipo == "video" else "image"
        status_message = {
            "type": status_type,
            "content": content,
            "caption": mensagem or titulo,
            "allContacts": True,
        }
    else:
        status_message = {
            "type": "text",
            "content": mensagem or titulo,
            "backgroundColor": {"emerald": "#008f6b", "indigo": "#3730a3", "amber": "#92400e", "rose": "#9f1239"}.get(cor, "#008f6b"),
            "font": 1,
            "allContacts": True,
        }

    try:
        endpoint = f"{base_url}/message/sendStatus/{resolved}"
        headers = {"apikey": token or "", "Content-Type": "application/json"}
        # Evolution API v2.3.0 espera `type` diretamente no corpo.
        response = requests.post(endpoint, headers=headers, json=status_message, timeout=20)
        if not response.ok:
            return {"ok": False, "detail": f"Evolution API respondeu {response.status_code}: {response.text[:240]}"}
        return {"ok": True}
    except requests.RequestException as exc:
        return {"ok": False, "detail": f"Falha de comunicação com a Evolution API: {exc}"}


@router.get("/api/status-empresa")
def listar_status():
    agora = datetime.now()
    with Session(engine) as session:
        itens = session.exec(
            select(StatusEmpresa)
            .where(StatusEmpresa.ativo == True, StatusEmpresa.expira_em > agora)
            .order_by(StatusEmpresa.criado_em.desc())
        ).all()
        return JSONResponse([_payload(item) for item in itens])


@router.post("/api/status-empresa")
async def publicar_status(
    request: Request,
    titulo: str = Form("Status da empresa"),
    mensagem: str = Form(""),
    cor: str = Form("emerald"),
    media: Optional[UploadFile] = File(None),
):
    criado_por = _admin(request)
    media_url = None
    media_tipo = None
    if media and media.filename:
        allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico", "video/mp4": ".mp4", "video/webm": ".webm"}
        extension = allowed.get(media.content_type or "")
        if not extension:
            filename_extension = os.path.splitext(media.filename)[1].lower()
            extension = filename_extension if filename_extension in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".ico", ".mp4", ".webm"} else None
        if not extension:
            raise HTTPException(status_code=400, detail="Use uma imagem JPG, PNG, WEBP, GIF, ICO ou vídeo MP4/WEBM.")
        content = await media.read()
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="O Status deve ter no máximo 25 MB.")
        folder = os.path.join(os.path.dirname(__file__), "public_html", "uploads", "status")
        os.makedirs(folder, exist_ok=True)
        filename = f"status-{uuid.uuid4().hex}{extension}"
        with open(os.path.join(folder, filename), "wb") as output:
            output.write(content)
        media_url = f"uploads/status/{filename}"
        media_tipo = "video" if (media.content_type or "").startswith("video/") or extension in {".mp4", ".webm"} else "imagem"

    with Session(engine) as session:
        status = StatusEmpresa(
            titulo=(titulo or "Status da empresa").strip()[:120],
            mensagem=(mensagem or "").strip()[:2000] or None,
            media_url=media_url,
            media_tipo=media_tipo,
            cor=cor if cor in {"emerald", "indigo", "amber", "rose"} else "emerald",
            criado_por=criado_por,
            expira_em=datetime.now() + timedelta(hours=24),
        )
        session.add(status)
        session.commit()
        session.refresh(status)
        whatsapp = _publish_whatsapp_status(request, status.titulo, status.mensagem or "", status.media_url, status.media_tipo, status.cor)
        result = {"ok": True, "status": _payload(status), "whatsapp": whatsapp}
        return JSONResponse(result)


@router.delete("/api/status-empresa/{status_id}")
def remover_status(status_id: int, request: Request):
    _admin(request)
    with Session(engine) as session:
        status = session.get(StatusEmpresa, status_id)
        if not status:
            raise HTTPException(status_code=404, detail="Status não encontrado.")
        status.ativo = False
        session.add(status)
        session.commit()
        return JSONResponse({"ok": True})
