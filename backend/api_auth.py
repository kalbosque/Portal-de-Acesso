import json
import secrets
from typing import Optional

import bcrypt
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from auth_utils import get_signed_cookie, normalize_permissions
from database import engine
from models import Usuario

router = APIRouter(prefix="/api/auth", tags=["Auth"])


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
    login_id: str = Form(...),
    password: str = Form(...),
    intent: str = Form("suporte"),
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

            if intent == "atendimento":
                if user.role != "admin" and "Atendimento" not in user_perms and "Suporte" not in user_perms:
                    return JSONResponse({"success": False, "detail": "Este usuário não possui permissão para Atendimento."}, status_code=403)
                redirect = "/central-atendimento"
            elif intent == "suporte":
                redirect = "/chamados"
            elif user.role in ("admin", "gestor") and intent == "gestao":
                redirect = "/"
            else:
                redirect = "/chamados"

            response = JSONResponse({"success": True, "redirect": redirect})
            _set_session_cookies(response, user)
            return response
    except Exception as exc:
        print(f"[LOGIN_ERROR] Falha ao processar login: {exc}")
        return JSONResponse(
            {"success": False, "detail": "Nao foi possivel validar o login agora. O banco de dados pode estar indisponivel."},
            status_code=503,
        )


@router.post("/register")
async def register(
    nome: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    nome = nome.strip()
    email = email.strip()
    username = username.strip()

    if not nome or not email or not username or not password:
        return JSONResponse({"success": False, "detail": "Preencha todos os campos."}, status_code=400)
    if "@" not in email:
        return JSONResponse({"success": False, "detail": "Informe um e-mail valido."}, status_code=400)
    if len(password) < 6 or len(password) > 8:
        return JSONResponse({"success": False, "detail": "A senha precisa ter entre 6 e 8 caracteres."}, status_code=400)

    with Session(engine) as session:
        existing = session.exec(
            select(Usuario).where((Usuario.email.ilike(email)) | (Usuario.username.ilike(username)))
        ).first()
        if existing:
            return JSONResponse(
                {"success": False, "detail": "Este nome de usuario ou e-mail ja esta em uso."},
                status_code=400,
            )

        user = Usuario(
            nome=nome,
            email=email,
            username=username,
            password_hash=hash_password(password),
            role="operator",
            status_conta="ativo",
            permissoes=json.dumps(["Dashboard", "Suporte"], ensure_ascii=False),
        )
        session.add(user)
        session.commit()

    return JSONResponse({"success": True, "message": "Cadastro realizado com sucesso! Voce ja pode fazer login."})


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

        if not user:
            return JSONResponse(
                {"success": True, "message": "Se o usuario existir, uma senha temporaria foi gerada. Verifique com o suporte."}
            )

        temp = secrets.token_hex(4).upper()
        user.senha_temp = hash_password(temp)
        session.add(user)
        session.commit()

    return JSONResponse(
        {
            "success": True,
            "message": (
                "Senha temporaria gerada: "
                f"{temp}. Anote esta senha e use-a para entrar. Troque-a logo apos o acesso."
            ),
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
        session.add(user)
        session.commit()

    response = JSONResponse({"success": True, "message": "Perfil atualizado"})
    response.set_cookie("user_name", user.nome or user.username, path="/", httponly=False, samesite="Lax")
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


@router.post("/logout")
async def logout():
    response = JSONResponse({"success": True})
    for key in ("user_id", "user_name", "username", "user_role", "user_perms"):
        response.delete_cookie(key, path="/")
    return response
