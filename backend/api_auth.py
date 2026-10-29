import json
import os
import re
import secrets
from datetime import datetime
from typing import Optional

import bcrypt
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from sqlalchemy import text

from auth_utils import create_study_access_token, get_signed_cookie, normalize_permissions
from database import engine
from models import Usuario
from utils_email import send_email_async

router = APIRouter(prefix="/api/auth", tags=["Auth"])
STUDY_ALLOWED_EMAIL = os.environ.get("STUDY_ALLOWED_EMAIL", "").strip().casefold()
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _is_study_account_allowed(user: Usuario) -> bool:
    email_allowed = bool(STUDY_ALLOWED_EMAIL) and (user.email or "").strip().casefold() == STUDY_ALLOWED_EMAIL
    return user.role == "estudante" or email_allowed


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        if hash_bytes.startswith(b"$2y$"):
            hash_bytes = b"$2b$" + hash_bytes[4:]
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


def _set_session_cookies(response: JSONResponse, user: Usuario) -> None:
    try:
        raw_perms = json.loads(user.permissoes or "[]")
        perms = normalize_permissions(raw_perms if isinstance(raw_perms, list) else [])
    except Exception:
        perms = []

    cookie_kwargs = {
        "path": "/",
        "httponly": False,
        "samesite": "Lax",
    }
    response.set_cookie("user_id", str(user.id), **cookie_kwargs)
    response.set_cookie("user_name", user.nome or user.username, **cookie_kwargs)
    response.set_cookie("username", user.username, **cookie_kwargs)
    response.set_cookie("user_role", user.role, **cookie_kwargs)
    response.set_cookie("user_perms", json.dumps(perms, ensure_ascii=False), **cookie_kwargs)


@router.post("/login")
async def login(
    request: Request,
    login_id: str = Form(...),
    password: str = Form(...),
    intent: str = Form("suporte"),
    desktop: str = Form("0"),
):
    login_id = login_id.strip()
    if not login_id or not password:
        return JSONResponse({"success": False, "detail": "Por favor, preencha todos os campos."}, status_code=400)

    try:
        with Session(engine) as session:
            user = session.exec(
                select(Usuario).where(
                    (Usuario.email.ilike(login_id)) | (Usuario.username.ilike(login_id))
                ).limit(1)
            ).first()

            if not user:
                return JSONResponse({"success": False, "detail": "E-mail/usuario ou senha incorretos."}, status_code=401)

            status = user.status_conta or "ativo"
            if status == "pendente":
                return JSONResponse({"success": False, "detail": "Sua conta esta aguardando aprovacao do administrador."}, status_code=403)
            if status == "bloqueado":
                return JSONResponse({"success": False, "detail": "Sua conta foi bloqueada. Entre em contato com o administrador."}, status_code=403)

            temp_valid = bool(user.senha_temp) and verify_password(password, user.senha_temp)
            if not verify_password(password, user.password_hash) and not temp_valid:
                return JSONResponse({"success": False, "detail": "E-mail/usuario ou senha incorretos."}, status_code=401)

            study_token = None
            if intent == "estudos":
                if not _is_study_account_allowed(user):
                    return JSONResponse({"success": False, "detail": "Acesso à Área de Estudos não autorizado."}, status_code=403)
                study_token = create_study_access_token(str(user.id))
                if not study_token:
                    return JSONResponse({"success": False, "detail": "A Área de Estudos não está configurada com segurança."}, status_code=503)

            if temp_valid:
                user.senha_temp = None
                session.add(user)
                session.commit()

            if user.role not in ("admin", "gestor") and intent == "gestao":
                return JSONResponse(
                    {"success": False, "detail": "Este portal e exclusivo para Administradores. Use o portal de Suporte TI."},
                    status_code=403,
                )

            try:
                user_perms = normalize_permissions(json.loads(user.permissoes or "[]"))
            except Exception:
                user_perms = []

            desktop_mode = desktop == "1"
            if intent == "estudos":
                redirect = "/estudos"
            elif intent == "atendimento":
                if user.role != "admin" and "Atendimento" not in user_perms and "Suporte" not in user_perms:
                    return JSONResponse({"success": False, "detail": "Este usuário não possui permissão para Atendimento."}, status_code=403)
                if desktop_mode:
                    redirect = "/central-atendimento?desktop=1"
                elif user.role in ("admin", "recepcao", "recepção", "recepcionista"):
                    redirect = "/central-atendimento/dashboard"
                else:
                    redirect = "/central-atendimento"
            elif intent == "suporte":
                redirect = "/chamados"
            elif user.role in ("admin", "gestor") and intent == "gestao":
                redirect = "/"
            else:
                redirect = "/chamados"

            response = JSONResponse({"success": True, "redirect": redirect})
            session.execute(text("UPDATE usuarios SET last_seen = :last_seen WHERE id = :user_id"), {"last_seen": datetime.now(), "user_id": user.id})
            session.commit()
            if desktop_mode:
                response.set_cookie("central_atendimento_tauri", "1", path="/", httponly=False, samesite="Lax")
            _set_session_cookies(response, user)
            if study_token:
                forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
                response.set_cookie(
                    "study_access",
                    study_token,
                    path="/estudos",
                    max_age=86400,
                    httponly=True,
                    secure=forwarded_proto == "https",
                    samesite="lax",
                )
            return response
    except Exception as exc:
        print(f"[LOGIN_ERROR] Falha ao processar login: {exc}")
        return JSONResponse(
            {"success": False, "detail": "Nao foi possivel validar o login agora. O banco de dados pode estar indisponivel."},
            status_code=503,
        )


@router.post("/register")
async def register():
    return JSONResponse(
        {"success": False, "detail": "O cadastro público está desativado. Solicite acesso ao administrador."},
        status_code=403,
    )


@router.post("/reset_senha")
async def reset_senha(login_id: str = Form(...)):
    login_id = login_id.strip()
    if not login_id:
        return JSONResponse({"success": False, "detail": "Informe seu e-mail ou nome de usuario."}, status_code=400)

    with Session(engine) as session:
        user = session.exec(
            select(Usuario).where(
                (Usuario.email.ilike(login_id)) | (Usuario.username.ilike(login_id))
            ).limit(1)
        ).first()

        registered_email = (user.email or "").strip() if user else ""
        if not user or not EMAIL_PATTERN.fullmatch(registered_email):
            return JSONResponse(
                {"success": True, "message": "Se houver uma conta cadastrada com esse acesso, enviaremos as instrucoes para o e-mail registrado."}
            )

        # A recuperacao agora e validada pelo e-mail cadastrado; nao bloqueie a conta de Estudos.
        if False and STUDY_ALLOWED_EMAIL and (user.email or "").strip().casefold() == STUDY_ALLOWED_EMAIL:
            return JSONResponse(
                {"success": False, "detail": "A recuperação automática está desativada para esta conta. Solicite a redefinição ao administrador."},
                status_code=403,
            )

        temp = secrets.token_hex(4).upper()
        email = registered_email
        email_sent = send_email_async(
            email,
            "Recuperacao de acesso - Sistema de Impressao",
            f"""
            <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #1e293b;">
                <h2 style="color: #4f46e5;">Recuperacao de acesso</h2>
                <p>Foi solicitada uma senha temporaria para sua conta.</p>
                <p style="font-size: 22px; font-weight: bold; letter-spacing: 3px; background: #f1f5f9; padding: 14px; text-align: center;">{temp}</p>
                <p>Use essa senha para entrar e altere-a imediatamente apos o acesso.</p>
                <p style="font-size: 12px; color: #64748b;">Se voce nao solicitou esta recuperacao, ignore este e-mail e avise o administrador.</p>
            </div>
            """,
        )
        if not email_sent:
            return JSONResponse(
                {"success": False, "detail": "Nao foi possivel enviar o e-mail de recuperacao. Solicite ajuda ao administrador."},
                status_code=503,
            )

        user.senha_temp = hash_password(temp)
        session.add(user)
        session.commit()

    return JSONResponse(
        {
            "success": True,
            "message": "A senha temporaria foi enviada para o e-mail cadastrado. Verifique sua caixa de entrada.",
        }
    )


@router.post("/update_profile")
async def update_profile(request: Request, nome: str = Form(...)):
    user_id = get_signed_cookie(request, "user_id")
    if not user_id:
        return JSONResponse({"success": False, "detail": "Nao autenticado"}, status_code=401)

    with Session(engine) as session:
        user = session.get(Usuario, int(user_id))
        if not user:
            return JSONResponse({"success": False, "detail": "Usuario nao encontrado"}, status_code=404)

        user.nome = nome.strip() or user.nome
        updated_name = user.nome or user.username
        session.add(user)
        session.commit()

    response = JSONResponse({"success": True, "message": "Perfil atualizado"})
    response.set_cookie("user_name", updated_name, path="/", httponly=False, samesite="Lax")
    return response


@router.post("/change_password")
async def change_password(request: Request, password: str = Form(...), confirm_password: Optional[str] = Form(None)):
    if confirm_password is not None and password != confirm_password:
        return JSONResponse({"success": False, "detail": "As senhas nao coincidem."}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"success": False, "detail": "Senha muito curta."}, status_code=400)

    user_id = get_signed_cookie(request, "user_id")
    if not user_id:
        return JSONResponse({"success": False, "detail": "Nao autenticado"}, status_code=401)

    with Session(engine) as session:
        user = session.get(Usuario, int(user_id))
        if not user:
            return JSONResponse({"success": False, "detail": "Usuario nao encontrado"}, status_code=404)

        user.password_hash = hash_password(password)
        user.senha_temp = None
        session.add(user)
        session.commit()

    return JSONResponse({"success": True, "message": "Senha alterada com sucesso!"})


@router.post("/heartbeat")
async def heartbeat(request: Request):
    user_id = get_signed_cookie(request, "user_id")
    if user_id:
        try:
            with Session(engine) as session:
                session.execute(text("UPDATE usuarios SET last_seen = :last_seen WHERE id = :user_id"), {"last_seen": datetime.now(), "user_id": int(user_id)})
                session.commit()
        except Exception as exc:
            print(f"[HEARTBEAT] Nao foi possivel atualizar presenca: {exc}")
    return JSONResponse({"success": True})


@router.post("/logout")
async def logout(request: Request):
    user_id = get_signed_cookie(request, "user_id")
    if user_id:
        try:
            with Session(engine) as session:
                session.execute(text("UPDATE usuarios SET last_seen = NULL WHERE id = :user_id"), {"user_id": int(user_id)})
                session.commit()
        except Exception as exc:
            print(f"[LOGOUT] Nao foi possivel limpar presenca: {exc}")
    response = JSONResponse({"success": True})
    for key in ("user_id", "user_name", "username", "user_role", "user_perms"):
        response.delete_cookie(key, path="/")
    return response
