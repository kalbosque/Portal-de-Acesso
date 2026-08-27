import os
import shutil
import base64
import json
import mimetypes
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from sqlmodel import Session, select, func, desc
from sqlalchemy import text

from models import Chamado, ChamadoInteracao, Impressora, TipoProblema
from database import engine
from auth_utils import get_signed_cookie
from notifications import send_alert
from websocket_manager import manager

router = APIRouter(prefix="/api/tickets", tags=["Tickets"])

UPLOADS_DIR = "public_html/uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)

# ─── Helpers ────────────────────────────────────────────────────────────────

def _get_user(request: Request):
    name = get_signed_cookie(request, "user_name", "Desconhecido")
    role = get_signed_cookie(request, "user_role", "operator")
    return name, role


def _calc_sla(prioridade: str) -> datetime:
    hours = {"Alta": 4, "Media": 24, "Baixa": 72}.get(prioridade, 24)
    return datetime.now() + timedelta(hours=hours)


# ─── Contagem de tickets (usado no badge do menu) ───────────────────────────

@router.get("/count")
def get_ticket_count(request: Request):
    user_name, user_role = _get_user(request)
    with Session(engine) as session:
        if user_role == "admin":
            count = session.exec(
                select(func.count(Chamado.id)).where(Chamado.status != "Resolvido")
            ).one()
        else:
            count = session.exec(
                select(func.count(Chamado.id))
                .where(Chamado.usuario == user_name, Chamado.status != "Resolvido")
            ).one()
    return {"count": count}


# ─── Status global (polling para toasts em tempo real) ──────────────────────

@router.get("/status_global")
def status_global(request: Request):
    user_name, user_role = _get_user(request)
    with Session(engine) as session:
        stmt = select(Chamado.id, Chamado.status, Chamado.usuario, Chamado.unread_admin, Chamado.unread_user)
        chamados = session.exec(stmt).all()
        
        abertos = 0
        resolvidos_meus = 0
        unread_list = {}
        
        for cid, status, usu, un_admin, un_user in chamados:
            if status == "Aberto":
                abertos += 1
            if status == "Resolvido" and usu == user_name:
                resolvidos_meus += 1
            if user_role == "admin" and un_admin and un_admin > 0:
                unread_list[str(cid)] = un_admin
            elif user_role != "admin" and usu == user_name and un_user and un_user > 0:
                unread_list[str(cid)] = un_user

        latest_msg = session.exec(
            select(ChamadoInteracao.id, ChamadoInteracao.chamado_id).order_by(desc(ChamadoInteracao.id)).limit(1)
        ).first()

        return {
            "abertos": abertos,
            "meus_resolvidos": resolvidos_meus,
            "latest_msg_id": latest_msg.id if latest_msg else 0,
            "latest_chamado_id": latest_msg.chamado_id if latest_msg else 0,
            "unread_list": unread_list,
        }


# ─── Abrir chamado (POST form) ───────────────────────────────────────────────

@router.post("/abrir")
async def create_ticket(
    request: Request,
    background_tasks: BackgroundTasks,
    titulo: str = Form(""),
    titulo_custom: str = Form(""),
    descricao: str = Form(...),
    prioridade: str = Form("Media"),
    categoria: str = Form("Outros"),
    equipamento_id: str = Form(""),
    anexo: UploadFile = File(None),
    usuario_kiosk: str = Form(None),
    custom_redirect: str = Form(None),
):
    user_name, _ = _get_user(request)
    if usuario_kiosk and (user_name == "Desconhecido" or not user_name):
        user_name = usuario_kiosk

    titulo_final = titulo_custom.strip() if titulo_custom.strip() else titulo.strip() or "Suporte Técnico"

    anexo_url = None
    if anexo and anexo.filename:
        ext = os.path.splitext(anexo.filename)[1]
        fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{user_name}{ext}"
        dest = os.path.join(UPLOADS_DIR, fname)
        with open(dest, "wb") as f:
            shutil.copyfileobj(anexo.file, f)
        anexo_url = f"/uploads/{fname}"

    with Session(engine) as session:
        chamado = Chamado(
            usuario=user_name,
            titulo=titulo_final,
            categoria=categoria,
            descricao=descricao,
            prioridade=prioridade,
            equipamento_id=equipamento_id or None,
            anexo_url=anexo_url,
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent", ""),
            vencimento_sla=_calc_sla(prioridade),
        )
        session.add(chamado)
        session.commit()
        session.refresh(chamado)
        ticket_id = chamado.id

    # Notificação Telegram para tickets Alta prioridade
    if prioridade == "Alta":
        msg = (
            f"🚨 <b>NOVO CHAMADO URGENTE!</b>\n\n"
            f"🆔 Ticket #<b>{ticket_id}</b>\n"
            f"👤 Usuário: <b>{user_name}</b>\n"
            f"📋 Assunto: <b>{titulo_final}</b>\n"
            f"📁 Categoria: {categoria}\n"
            f"⚡ Prioridade: <b>ALTA</b>\n\n"
            f"📝 {descricao[:200]}{'...' if len(descricao) > 200 else ''}"
        )
        background_tasks.add_task(send_alert, msg)

    # Broadcast WebSocket para atualizar todos os painéis em tempo real
    background_tasks.add_task(
        manager.broadcast,
        {"event": "new_ticket", "ticket_id": ticket_id, "prioridade": prioridade, "usuario": user_name}
    )

    if custom_redirect:
        return RedirectResponse(url=f"{custom_redirect}?success=1", status_code=303)
    return RedirectResponse(url=f"/chamados?success=Chamado+%23{ticket_id}+aberto!", status_code=303)


# ─── Atualizar status ────────────────────────────────────────────────
@router.post("/atualizar_status")
async def update_status(request: Request, background_tasks: BackgroundTasks):
    user_name, user_role = _get_user(request)

    data = await request.json()
    ticket_id = data.get("id")
    new_status = data.get("status")

    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")
        
        chamado.status = new_status
        if new_status == "Em Atendimento" and not chamado.assigned_user:
            chamado.assigned_user = user_name
            
        if new_status == "Resolvido":
            chamado.data_resolucao = datetime.now()
            
        session.commit()
        session.refresh(chamado)

        if chamado.origem == "WhatsApp" and chamado.whatsapp_cliente:
            from api_whatsapp import send_whatsapp_text
            if new_status == "Resolvido":
                msg_wa = f"Seu chamado #{chamado.id} foi finalizado."
                background_tasks.add_task(send_whatsapp_text, chamado.whatsapp_cliente, msg_wa, chamado.whatsapp_instance)
            elif new_status == "Em Atendimento":
                msg_wa = f"Seu chamado #{chamado.id} foi assumido e já está em atendimento com {user_name}."
                background_tasks.add_task(send_whatsapp_text, chamado.whatsapp_cliente, msg_wa, chamado.whatsapp_instance)

    background_tasks.add_task(
        manager.broadcast,
        {"event": "ticket_updated", "ticket_id": ticket_id, "status": new_status}
    )
    return {"success": True}


# ─── Finalizar com nota técnica ──────────────────────────────────────

@router.post("/finalizar")
async def finalizar_ticket(request: Request, background_tasks: BackgroundTasks):
    user_name, user_role = _get_user(request)

    data = await request.json()
    ticket_id = data.get("id")
    nota = data.get("nota_tecnica", "")

    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")
        if chamado.visivel_suporte and not str(nota or '').strip():
            raise HTTPException(status_code=400, detail="Informe a nota técnica para finalizar um chamado do suporte")
            
        chamado.status = "Resolvido"
        if not chamado.assigned_user:
            chamado.assigned_user = user_name
            
        chamado.nota_tecnica = nota
        chamado.data_resolucao = datetime.now()
        session.commit()
        session.refresh(chamado)

        if chamado.origem == "WhatsApp" and chamado.whatsapp_cliente:
            from api_whatsapp import send_whatsapp_text
            msg_resolucao = f"Seu chamado #{chamado.id} foi finalizado.\n\n*Nota Técnica:* {nota or 'Nenhuma nota informada.'}"
            background_tasks.add_task(send_whatsapp_text, chamado.whatsapp_cliente, msg_resolucao, chamado.whatsapp_instance)

    background_tasks.add_task(
        manager.broadcast,
        {"event": "ticket_resolved", "ticket_id": ticket_id}
    )
    return {"success": True}


@router.post("/resolver/{ticket_id}")
async def resolver_ticket_compat(ticket_id: int, request: Request, background_tasks: BackgroundTasks):
    """Compatibilidade com versões antigas do JavaScript da tela de chamados."""
    user_name, _ = _get_user(request)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        nota = data.get("nota_tecnica", "")
    else:
        form = await request.form()
        nota = str(form.get("nota_tecnica", ""))

    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")

        chamado.status = "Resolvido"
        chamado.assigned_user = chamado.assigned_user or user_name
        chamado.nota_tecnica = nota
        chamado.data_resolucao = datetime.now()
        session.add(chamado)
        session.commit()

    background_tasks.add_task(
        manager.broadcast,
        {"event": "ticket_resolved", "ticket_id": ticket_id}
    )
    return {"success": True}


# ─── Chat / Mural ────────────────────────────────────────────────────────────

# Armazena quem está digitando: {chamado_id: {user: timestamp}}
_typing_store: dict = {}
_typing_schema_ready = False

def _ensure_typing_schema():
    global _typing_schema_ready
    if _typing_schema_ready:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_typing_until TIMESTAMP NULL"))
        conn.execute(text("ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_typing_media BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS responde_a_id INTEGER NULL"))
        conn.execute(text("ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS responde_a_usuario VARCHAR(255) NULL"))
        conn.execute(text("ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS responde_a_texto TEXT NULL"))
        conn.execute(text("ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS whatsapp_message_id VARCHAR(160) NULL"))
        conn.execute(text("ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS whatsapp_remote_jid VARCHAR(180) NULL"))
        conn.execute(text("ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS reacao VARCHAR(32) NULL"))
    _typing_schema_ready = True
MESSAGE_EDIT_WINDOW_MINUTES = 15
MESSAGE_DELETE_WINDOW_HOURS = 60


def _message_can_edit(message: ChamadoInteracao, user_name: str) -> bool:
    return message.usuario == user_name and datetime.now() - message.data_hora <= timedelta(minutes=MESSAGE_EDIT_WINDOW_MINUTES)


def _message_can_delete(message: ChamadoInteracao, user_name: str, user_role: str) -> bool:
    return (message.usuario == user_name or user_role == "admin") and datetime.now() - message.data_hora <= timedelta(hours=MESSAGE_DELETE_WINDOW_HOURS)

# ── GET /api/tickets/chat?chamado_id=X&since_id=Y  (frontend polling) ─────────
@router.get("/chat")
def get_chat_messages(chamado_id: int, since_id: int = 0, request: Request = None):
    _ensure_typing_schema()
    user_name, user_role = _get_user(request)
    with Session(engine) as session:
        chamado = session.get(Chamado, chamado_id)
        if not chamado:
            raise HTTPException(status_code=404)

        msgs = session.exec(
            select(ChamadoInteracao)
            .where(
                ChamadoInteracao.chamado_id == chamado_id,
                ChamadoInteracao.id > since_id,
            )
            .order_by(ChamadoInteracao.data_hora)
        ).all()

        return {
            "ok": True,
            "messages": [
                {
                    "id": m.id,
                    "usuario": m.usuario,
                    "mensagem": m.mensagem,
                    "responde_a_id": m.responde_a_id,
                    "responde_a_usuario": m.responde_a_usuario,
                    "responde_a_texto": m.responde_a_texto,
                    "whatsapp_message_id": m.whatsapp_message_id,
                    "whatsapp_remote_jid": m.whatsapp_remote_jid,
                    "reacao": m.reacao,
                    "is_me": m.usuario == user_name,
                    "can_edit": _message_can_edit(m, user_name),
                    "can_delete": _message_can_delete(m, user_name, user_role),
                    "whatsapp_status": m.whatsapp_status or "sent",
                    "data_hora": m.data_hora.strftime("%d/%m/%Y %H:%M:%S"),
                }
                for m in msgs
            ],
        }


# ── POST /api/tickets/chat/send?chamado_id=X  (FormData) ──────────────────────
@router.post("/chat/send")
async def send_chat_message(
    chamado_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    mensagem: str = Form(""),
    reply_to_id: Optional[int] = Form(None),
    anexo: UploadFile = File(None),
):
    user_name, user_role = _get_user(request)
    msg_text = mensagem.strip()
    if not msg_text and not (anexo and anexo.filename):
        raise HTTPException(status_code=400, detail="Mensagem vazia")

    media_payload = None
    if anexo and anexo.filename:
        raw_bytes = await anexo.read()
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Arquivo vazio")
        if len(raw_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Arquivo maior que 25 MB")
        mime_type = anexo.content_type or mimetypes.guess_type(anexo.filename)[0] or "application/octet-stream"
        if mime_type == "image/gif" or anexo.filename.lower().endswith(".gif"):
            media_type = "gif"
        elif mime_type.startswith("image/"):
            media_type = "image"
        elif mime_type.startswith("video/"):
            media_type = "video"
        elif mime_type.startswith("audio/"):
            media_type = "audio"
        else:
            media_type = "document"
        safe_name = os.path.basename(anexo.filename).replace(" ", "_")
        stored_name = f"{uuid.uuid4().hex}_{safe_name}"
        media_dir = os.path.join(UPLOADS_DIR, "whatsapp_media")
        os.makedirs(media_dir, exist_ok=True)
        with open(os.path.join(media_dir, stored_name), "wb") as output:
            output.write(raw_bytes)
        media_payload = {
            "__wa_media__": True,
            "type": media_type,
            "url": f"/uploads/whatsapp_media/{stored_name}",
            "mime": mime_type,
            "filename": safe_name,
            "caption": msg_text,
            "base64": base64.b64encode(raw_bytes).decode("ascii"),
        }
        msg_text = json.dumps({k: v for k, v in media_payload.items() if k != "base64"}, ensure_ascii=False)

    _ensure_typing_schema()
    with Session(engine) as session:
        chamado = session.get(Chamado, chamado_id)
        if not chamado:
            raise HTTPException(status_code=404)

        reply = session.get(ChamadoInteracao, reply_to_id) if reply_to_id else None
        if reply and reply.chamado_id != chamado_id:
            reply = None
        msg = ChamadoInteracao(
            chamado_id=chamado_id,
            usuario=user_name,
            mensagem=msg_text,
            responde_a_id=reply.id if reply else None,
            responde_a_usuario=reply.usuario if reply else None,
            responde_a_texto=(reply.mensagem[:500] if reply else None),
        )
        session.add(msg)

        # Incrementar unread para o outro lado
        if user_role == "admin":
            chamado.unread_user = (chamado.unread_user or 0) + 1
        else:
            chamado.unread_admin = (chamado.unread_admin or 0) + 1

        session.commit()
        session.refresh(msg)

        if chamado.origem == "WhatsApp" and chamado.whatsapp_cliente:
            from api_whatsapp import send_whatsapp_text_for_interaction, send_whatsapp_media
            if media_payload:
                background_tasks.add_task(
                    send_whatsapp_media,
                    chamado.whatsapp_cliente,
                    media_payload["base64"],
                    media_payload["type"],
                    media_payload["mime"],
                    media_payload["filename"],
                    media_payload["caption"],
                    chamado.whatsapp_instance,
                )
            elif msg_text:
                whatsapp_text = f"*{user_name}*:\n{msg_text}"
                background_tasks.add_task(send_whatsapp_text_for_interaction, msg.id, chamado.whatsapp_cliente, whatsapp_text, chamado.whatsapp_instance)

    background_tasks.add_task(
        manager.broadcast,
        {
            "event": "new_message",
            "chamado_id": chamado_id,
            "msg_id": msg.id,
            "usuario": user_name,
            "preview": msg_text[:80],
        },
    )

    return {
        "ok": True,
        "message": {
            "id": msg.id,
            "usuario": user_name,
            "mensagem": msg_text,
            "responde_a_id": msg.responde_a_id,
            "responde_a_usuario": msg.responde_a_usuario,
            "responde_a_texto": msg.responde_a_texto,
            "whatsapp_status": msg.whatsapp_status or "sent",
            "data_hora": msg.data_hora.strftime("%d/%m/%Y %H:%M:%S"),
        },
    }


@router.put("/chat/message/{message_id}")
def edit_chat_message(message_id: int, payload: dict, request: Request, background_tasks: BackgroundTasks):
    user_name, user_role = _get_user(request)
    new_text = str(payload.get("mensagem") or "").strip()
    if not new_text:
        raise HTTPException(status_code=400, detail="Mensagem vazia")
    with Session(engine) as session:
        msg = session.get(ChamadoInteracao, message_id)
        if not msg:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")
        if False:
            raise HTTPException(status_code=403, detail="Você só pode editar suas próprias mensagens")
        if not _message_can_edit(msg, user_name):
            raise HTTPException(status_code=403, detail="Prazo de edição expirado")
        if msg.mensagem.lstrip().startswith('{'):
            raise HTTPException(status_code=400, detail="Anexos não podem ser editados")
        msg.mensagem = new_text
        session.add(msg)
        session.commit()
    return {"ok": True, "message_id": message_id, "mensagem": new_text}


@router.delete("/chat/message/{message_id}")
def delete_chat_message(message_id: int, request: Request, background_tasks: BackgroundTasks):
    user_name, user_role = _get_user(request)
    with Session(engine) as session:
        msg = session.get(ChamadoInteracao, message_id)
        if not msg:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")
        if False:
            raise HTTPException(status_code=403, detail="Você só pode excluir suas próprias mensagens")
        if not _message_can_delete(msg, user_name, user_role):
            raise HTTPException(status_code=403, detail="Prazo de exclusão expirado")
        chamado_id = msg.chamado_id
        msg.mensagem = "[Mensagem excluída]"
        session.add(msg)
        session.commit()
        background_tasks.add_task(manager.broadcast, {"event": "message_deleted", "chamado_id": chamado_id, "msg_id": message_id})
    return {"ok": True, "message_id": message_id}


# ── POST /api/tickets/chat/mark_read?chamado_id=X ─────────────────────────────
@router.post("/chat/mark_read")
def mark_chat_read(chamado_id: int, request: Request):
    _, user_role = _get_user(request)
    with Session(engine) as session:
        chamado = session.get(Chamado, chamado_id)
        if chamado:
            # A Central de Atendimento usa unread_admin para todos os perfis
            # autorizados; zerar ambos mantém o contador consistente após abrir.
            chamado.unread_admin = 0
            chamado.unread_user = 0
            session.commit()
    return {"ok": True}


# ── GET /api/tickets/chat/get_typing?chamado_id=X ────────────────────────────
@router.get("/chat/get_typing")
def get_typing(chamado_id: int, request: Request):
    _ensure_typing_schema()
    user_name, _ = _get_user(request)
    now = datetime.now().timestamp()
    store = _typing_store.get(chamado_id, {})
    # Usuários que digitaram nos últimos 4 segundos (excluindo o próprio usuário)
    active = [u for u, ts in store.items() if now - ts < 4 and u != user_name]
    with Session(engine) as session:
        chamado = session.get(Chamado, chamado_id)
        if chamado and chamado.whatsapp_typing_until and chamado.whatsapp_typing_until > datetime.now():
            active.append("Cliente")
            return {"typing": active, "media": bool(chamado.whatsapp_typing_media)}
    return {"typing": active, "media": False}


# ── POST /api/tickets/chat/typing?chamado_id=X ───────────────────────────────
@router.post("/chat/typing")
def set_typing(chamado_id: int, request: Request):
    user_name, _ = _get_user(request)
    if chamado_id not in _typing_store:
        _typing_store[chamado_id] = {}
    _typing_store[chamado_id][user_name] = datetime.now().timestamp()
    return {"ok": True}


# ── Endpoints legados com path param (mantidos para compatibilidade) ───────────
@router.get("/chat/{chamado_id}")
def get_chat_legacy(chamado_id: int, request: Request):
    _ensure_typing_schema()
    user_name, user_role = _get_user(request)
    with Session(engine) as session:
        chamado = session.get(Chamado, chamado_id)
        if not chamado:
            raise HTTPException(status_code=404)
        if user_role == "admin":
            chamado.unread_admin = 0
        else:
            chamado.unread_user = 0
        session.commit()
        msgs = session.exec(
            select(ChamadoInteracao)
            .where(ChamadoInteracao.chamado_id == chamado_id)
            .order_by(ChamadoInteracao.data_hora)
        ).all()
        return [
            {
                "id": m.id,
                "usuario": m.usuario,
                "mensagem": m.mensagem,
                "responde_a_id": m.responde_a_id,
                "responde_a_usuario": m.responde_a_usuario,
                "responde_a_texto": m.responde_a_texto,
                "whatsapp_message_id": m.whatsapp_message_id,
                "whatsapp_remote_jid": m.whatsapp_remote_jid,
                "reacao": m.reacao,
                "data_hora": m.data_hora.strftime("%d/%m %H:%M"),
                "is_me": m.usuario == user_name,
                "can_edit": _message_can_edit(m, user_name),
                "can_delete": _message_can_delete(m, user_name, user_role),
                "whatsapp_status": m.whatsapp_status or "sent",
            }
            for m in msgs
        ]


@router.post("/chat/{chamado_id}")
async def post_chat(chamado_id: int, request: Request, background_tasks: BackgroundTasks):
    user_name, user_role = _get_user(request)
    data = await request.json()
    msg_text = data.get("mensagem", "").strip()
    if not msg_text:
        raise HTTPException(status_code=400, detail="Mensagem vazia")

    with Session(engine) as session:
        chamado = session.get(Chamado, chamado_id)
        if not chamado:
            raise HTTPException(status_code=404)

        msg = ChamadoInteracao(chamado_id=chamado_id, usuario=user_name, mensagem=msg_text)
        session.add(msg)

        # Incrementar unread para o outro lado
        if user_role == "admin":
            chamado.unread_user = (chamado.unread_user or 0) + 1
        else:
            chamado.unread_admin = (chamado.unread_admin or 0) + 1

        session.commit()
        session.refresh(msg)
        msg_id = msg.id

        if chamado.origem == "WhatsApp" and chamado.whatsapp_cliente:
            from api_whatsapp import send_whatsapp_text
            background_tasks.add_task(send_whatsapp_text, chamado.whatsapp_cliente, msg_text, chamado.whatsapp_instance)

    background_tasks.add_task(
        manager.broadcast,
        {
            "event": "new_message",
            "chamado_id": chamado_id,
            "msg_id": msg_id,
            "usuario": user_name,
            "preview": msg_text[:80],
        }
    )
    return {"success": True, "msg_id": msg_id}


# ─── Avaliação NPS ───────────────────────────────────────────────────────────

@router.post("/avaliar/{chamado_id}")
async def avaliar_ticket(chamado_id: int, request: Request):
    user_name, _ = _get_user(request)
    data = await request.json()
    estrelas = int(data.get("estrelas", 0))
    comentario = data.get("comentario", "")

    with Session(engine) as session:
        chamado = session.get(Chamado, chamado_id)
        if not chamado or chamado.usuario != user_name:
            raise HTTPException(status_code=403, detail="Não autorizado")
        chamado.avaliacao_estrelas = estrelas
        chamado.avaliacao_comentario = comentario
        session.commit()
    return {"success": True}


# ─── CRUD Atalhos (admin) ────────────────────────────────────────────────────

@router.post("/atalhos")
async def create_atalho(request: Request):
    _, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403)
    data = await request.json()
    with Session(engine) as session:
        ap = TipoProblema(
            icone=data.get("icone", "🛠️"),
            label=data.get("label", "Problema"),
            titulo_padrao=data.get("titulo_padrao", ""),
            categoria=data.get("categoria", "Outros"),
            prioridade_padrao=data.get("prioridade_padrao", "Media"),
            sla_horas=int(data.get("sla_horas", 24)),
        )
        session.add(ap)
        session.commit()
        session.refresh(ap)
        return {"success": True, "id": ap.id}


@router.put("/atalhos/{atalho_id}")
async def update_atalho(atalho_id: int, request: Request):
    _, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403)
    data = await request.json()
    with Session(engine) as session:
        ap = session.get(TipoProblema, atalho_id)
        if not ap:
            raise HTTPException(status_code=404)
        for k, v in data.items():
            if hasattr(ap, k):
                setattr(ap, k, v)
        session.commit()
    return {"success": True}


@router.delete("/atalhos/{atalho_id}")
def delete_atalho(atalho_id: int, request: Request):
    _, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403)
    with Session(engine) as session:
        ap = session.get(TipoProblema, atalho_id)
        if ap:
            session.delete(ap)
            session.commit()
    return {"success": True}


# ─── Obter ticket por id ─────────────────────────────────────────────────────

@router.get("/{ticket_id}")
def get_ticket(ticket_id: int):
    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404)
        return chamado.dict()

# ─── Melhorias Fase 2 ────────────────────────────────────────────────────────

@router.post("/reabrir")
async def reabrir_ticket(request: Request, background_tasks: BackgroundTasks, id: int = Form(...)):
    user_name, user_role = _get_user(request)
    with Session(engine) as session:
        chamado = session.get(Chamado, id)
        if not chamado: return RedirectResponse(url="/chamados?error=not_found", status_code=303)
        if not (user_role == "admin" or chamado.usuario == user_name):
            return RedirectResponse(url="/chamados?error=denied", status_code=303)
            
        chamado.status = "Aberto"
        session.add(chamado)
        session.commit()
        
        background_tasks.add_task(
            manager.broadcast,
            {"event": "ticket_updated", "ticket_id": id, "status": "Aberto"}
        )
        return RedirectResponse(url=f"/chamados?success=Chamado+reaberto!", status_code=303)

@router.post("/avaliar_nps")
async def avaliar_nps(request: Request, background_tasks: BackgroundTasks, id: int = Form(...), estrelas: int = Form(...), comentario: str = Form("")):
    user_name, _ = _get_user(request)
    with Session(engine) as session:
        chamado = session.get(Chamado, id)
        if not chamado: return RedirectResponse(url="/chamados?error=not_found", status_code=303)
        if chamado.usuario != user_name:
            return RedirectResponse(url="/chamados?error=denied", status_code=303)
            
        chamado.avaliacao_estrelas = estrelas
        chamado.avaliacao_comentario = comentario
        session.add(chamado)
        session.commit()
        
        return RedirectResponse(url=f"/chamados?success=Avaliacao+salva!", status_code=303)
