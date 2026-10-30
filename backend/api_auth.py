import json
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from sqlalchemy import text

from auth_utils import create_study_access_token, get_signed_cookie, normalize_permissions
from database import engine
from models import Usuario
from utils_email import send_email_async

router = APIRouter(prefix="/api/auth", tags=["Auth"])
STUDY_ALLOWED_EMAIL = os.environ.get("STUDY_ALLOWED_EMAIL", "").strip().casefold()
STUDY_ADMIN_EMAILS = {item.strip().casefold() for item in os.environ.get("STUDY_ADMIN_EMAILS", "").split(",") if item.strip()}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _is_study_account_allowed(user: Usuario) -> bool:
    email_allowed = bool(STUDY_ALLOWED_EMAIL) and (user.email or "").strip().casefold() == STUDY_ALLOWED_EMAIL
    return user.role == "estudante" or email_allowed


def _is_study_admin(user: Usuario) -> bool:
    return (user.email or "").strip().casefold() in STUDY_ADMIN_EMAILS


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


SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 dias
ESTUDO_CODIGO_EXPIRA_MINUTOS = 10
ESTUDO_CODIGO_MAX_TENTATIVAS = 5


def _novo_codigo_estudos() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def _digest_codigo_estudos(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def _email_codigo_estudos(nome: str, codigo: str) -> str:
    return f"""
    <div style=\"font-family:Arial,sans-serif;max-width:560px;padding:24px;color:#172033\">
      <h2 style=\"color:#4f46e5\">Confirmação do cadastro de Estudos</h2>
      <p>Olá, <b>{nome}</b>! Use o código abaixo para confirmar seu acesso:</p>
      <div style=\"margin:24px 0;padding:18px;text-align:center;border-radius:12px;background:#eef2ff;color:#3730a3;font-size:32px;font-weight:800;letter-spacing:8px\">{codigo}</div>
      <p>O código expira em {ESTUDO_CODIGO_EXPIRA_MINUTOS} minutos e pode ser usado até 5 vezes.</p>
    </div>
    """


def _email_codigo_recuperacao_estudos(nome: str, codigo: str) -> str:
    return f"""
    <div style=\"font-family:Arial,sans-serif;max-width:560px;padding:24px;color:#172033\">
      <h2 style=\"color:#4f46e5\">Alteração de senha da Área de Estudos</h2>
      <p>Olá, <b>{nome}</b>! Use o código abaixo para criar uma nova senha:</p>
      <div style=\"margin:24px 0;padding:18px;text-align:center;border-radius:12px;background:#eef2ff;color:#3730a3;font-size:32px;font-weight:800;letter-spacing:8px\">{codigo}</div>
      <p>O código expira em {ESTUDO_CODIGO_EXPIRA_MINUTOS} minutos.</p>
    </div>
    """


def _set_session_cookies(response: Response, user: Usuario) -> None:
    try:
        raw_perms = json.loads(user.permissoes or "[]")
        perms = normalize_permissions(raw_perms if isinstance(raw_perms, list) else [])
    except Exception:
        perms = []

    cookie_kwargs = {
        "path": "/",
        "httponly": False,
        "samesite": "Lax",
        "max_age": SESSION_COOKIE_MAX_AGE,
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
                    path="/",
                    max_age=SESSION_COOKIE_MAX_AGE,
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


@router.post("/estudos/cadastrar")
async def cadastrar_estudos(
    nome: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    nome = nome.strip()
    email = email.strip().casefold()
    username = username.strip()
    if not nome or not EMAIL_PATTERN.match(email) or len(username) < 3:
        return JSONResponse({"success": False, "detail": "Preencha nome, e-mail e usuário corretamente."}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"success": False, "detail": "A senha precisa ter pelo menos 6 caracteres."}, status_code=400)
    if password != confirm_password:
        return JSONResponse({"success": False, "detail": "As senhas não coincidem."}, status_code=400)

    with Session(engine) as session:
        if session.exec(select(Usuario).where((Usuario.email.ilike(email)) | (Usuario.username.ilike(username)))).first():
            return JSONResponse({"success": False, "email_exists": True, "detail": "Este e-mail já está cadastrado. Você pode solicitar um código para alterar a senha."}, status_code=409)

    codigo = _novo_codigo_estudos()
    agora = datetime.now(timezone.utc)
    expira = agora + timedelta(minutes=ESTUDO_CODIGO_EXPIRA_MINUTOS)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM estudos_cadastros_confirmacao WHERE lower(email) = :email OR lower(username) = :username"), {"email": email, "username": username.casefold()})
        conn.execute(text("""INSERT INTO estudos_cadastros_confirmacao
            (nome, email, username, password_hash, codigo_hash, codigo_digest, expira_em, tentativas, usado)
            VALUES (:nome, :email, :username, :password_hash, :codigo_hash, :codigo_digest, :expira_em, 0, FALSE)"""), {
                "nome": nome[:180], "email": email[:255], "username": username[:120],
                "password_hash": hash_password(password), "codigo_hash": hash_password(codigo), "codigo_digest": _digest_codigo_estudos(codigo), "expira_em": expira,
            })

    if not send_email_async(email, "Confirme seu cadastro na Área de Estudos", _email_codigo_estudos(nome, codigo)):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM estudos_cadastros_confirmacao WHERE lower(email) = :email AND usado = FALSE"), {"email": email})
        return JSONResponse({"success": False, "detail": "Não foi possível enviar o e-mail. Configure o SMTP e tente novamente."}, status_code=503)
    return JSONResponse({"success": True, "message": "Código enviado para seu e-mail."})


@router.post("/estudos/confirmar-codigo")
async def confirmar_codigo_estudos(email: str = Form(...), codigo: str = Form(...)):
    email = email.strip().casefold()
    codigo = re.sub(r"\D", "", codigo)
    if len(codigo) != 6:
        return JSONResponse({"success": False, "detail": "Informe o código de 6 números."}, status_code=400)
    with engine.begin() as conn:
        row = conn.execute(text("""SELECT * FROM estudos_cadastros_confirmacao
            WHERE lower(email) = :email AND usado = FALSE ORDER BY id DESC LIMIT 1"""), {"email": email}).mappings().first()
        if not row:
            return JSONResponse({"success": False, "detail": "Cadastro não encontrado ou já confirmado."}, status_code=404)
        if row["expira_em"] < datetime.now(timezone.utc):
            return JSONResponse({"success": False, "detail": "O código expirou. Solicite um novo código."}, status_code=410)
        if row["tentativas"] >= ESTUDO_CODIGO_MAX_TENTATIVAS:
            return JSONResponse({"success": False, "detail": "Limite de tentativas atingido. Solicite um novo código."}, status_code=429)
        codigo_valido = bool(row.get("codigo_digest")) and hmac.compare_digest(_digest_codigo_estudos(codigo), row["codigo_digest"])
        if not codigo_valido and not verify_password(codigo, row["codigo_hash"]):
            conn.execute(text("UPDATE estudos_cadastros_confirmacao SET tentativas = tentativas + 1 WHERE id = :id"), {"id": row["id"]})
            return JSONResponse({"success": False, "detail": "Código inválido."}, status_code=400)

        existing = conn.execute(text("SELECT id FROM usuarios WHERE lower(email) = :email OR lower(username) = :username LIMIT 1"), {"email": email, "username": row["username"].casefold()}).first()
        if existing:
            return JSONResponse({"success": False, "detail": "Este e-mail ou usuário já foi utilizado."}, status_code=409)
        conn.execute(text("""INSERT INTO usuarios (nome, email, username, password_hash, role, status_conta, permissoes)
            VALUES (:nome, :email, :username, :password_hash, 'estudante', 'ativo', '[]')"""), {
                "nome": row["nome"], "email": row["email"], "username": row["username"], "password_hash": row["password_hash"]
            })
        conn.execute(text("UPDATE estudos_cadastros_confirmacao SET usado = TRUE WHERE id = :id"), {"id": row["id"]})
    return JSONResponse({"success": True, "message": "Cadastro confirmado. Você já pode entrar."})


@router.post("/estudos/reenviar-codigo")
async def reenviar_codigo_estudos(email: str = Form(...)):
    email = email.strip().casefold()
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM estudos_cadastros_confirmacao WHERE lower(email) = :email AND usado = FALSE ORDER BY id DESC LIMIT 1"), {"email": email}).mappings().first()
        if not row:
            return JSONResponse({"success": False, "detail": "Cadastro pendente não encontrado."}, status_code=404)
        codigo = _novo_codigo_estudos()
        conn.execute(text("UPDATE estudos_cadastros_confirmacao SET codigo_hash = :codigo_hash, codigo_digest = :codigo_digest, expira_em = :expira_em, tentativas = 0 WHERE id = :id"), {"codigo_hash": hash_password(codigo), "codigo_digest": _digest_codigo_estudos(codigo), "expira_em": datetime.now(timezone.utc) + timedelta(minutes=ESTUDO_CODIGO_EXPIRA_MINUTOS), "id": row["id"]})
    if not send_email_async(email, "Novo código de confirmação da Área de Estudos", _email_codigo_estudos(row["nome"], codigo)):
        return JSONResponse({"success": False, "detail": "Não foi possível enviar o e-mail."}, status_code=503)
    return JSONResponse({"success": True, "message": "Novo código enviado."})


@router.post("/estudos/solicitar-recuperacao")
async def solicitar_recuperacao_estudos(email: str = Form(...)):
    email = email.strip().casefold()
    with Session(engine) as session:
        user = session.exec(select(Usuario).where(Usuario.email.ilike(email))).first()
        if not user or not _is_study_account_allowed(user):
            return JSONResponse({"success": False, "detail": "Não encontramos uma conta de Estudos com este e-mail."}, status_code=404)
        user_id = user.id
        nome = user.nome or user.username

    codigo = _novo_codigo_estudos()
    with engine.begin() as conn:
        conn.execute(text("UPDATE estudos_recuperacao_codigos SET usado = TRUE WHERE usuario_id = :usuario_id AND usado = FALSE"), {"usuario_id": user_id})
        conn.execute(text("""INSERT INTO estudos_recuperacao_codigos
            (usuario_id, email, codigo_digest, expira_em, tentativas, usado)
            VALUES (:usuario_id, :email, :codigo_digest, :expira_em, 0, FALSE)"""), {
                "usuario_id": user_id, "email": email, "codigo_digest": _digest_codigo_estudos(codigo),
                "expira_em": datetime.now(timezone.utc) + timedelta(minutes=ESTUDO_CODIGO_EXPIRA_MINUTOS),
            })
    if not send_email_async(email, "Código para alterar sua senha nos Estudos", _email_codigo_recuperacao_estudos(nome, codigo)):
        return JSONResponse({"success": False, "detail": "Não foi possível enviar o código para o e-mail."}, status_code=503)
    return JSONResponse({"success": True, "message": "Código de alteração de senha enviado para seu e-mail."})


@router.post("/estudos/alterar-senha-codigo")
async def alterar_senha_codigo_estudos(
    email: str = Form(...),
    codigo: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    email = email.strip().casefold()
    codigo = re.sub(r"\D", "", codigo)
    if len(codigo) != 6:
        return JSONResponse({"success": False, "detail": "Informe o código de 6 números."}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"success": False, "detail": "A nova senha precisa ter pelo menos 6 caracteres."}, status_code=400)
    if password != confirm_password:
        return JSONResponse({"success": False, "detail": "As senhas não coincidem."}, status_code=400)
    with engine.begin() as conn:
        row = conn.execute(text("""SELECT * FROM estudos_recuperacao_codigos
            WHERE lower(email) = :email AND usado = FALSE ORDER BY id DESC LIMIT 1"""), {"email": email}).mappings().first()
        if not row:
            return JSONResponse({"success": False, "detail": "Solicitação de alteração não encontrada."}, status_code=404)
        if row["expira_em"] < datetime.now(timezone.utc):
            return JSONResponse({"success": False, "detail": "O código expirou. Solicite outro."}, status_code=410)
        if row["tentativas"] >= ESTUDO_CODIGO_MAX_TENTATIVAS:
            return JSONResponse({"success": False, "detail": "Limite de tentativas atingido. Solicite outro código."}, status_code=429)
        if not hmac.compare_digest(_digest_codigo_estudos(codigo), row["codigo_digest"]):
            conn.execute(text("UPDATE estudos_recuperacao_codigos SET tentativas = tentativas + 1 WHERE id = :id"), {"id": row["id"]})
            return JSONResponse({"success": False, "detail": "Código inválido."}, status_code=400)
        conn.execute(text("UPDATE usuarios SET password_hash = :password_hash, senha_temp = NULL WHERE id = :usuario_id"), {"password_hash": hash_password(password), "usuario_id": row["usuario_id"]})
        conn.execute(text("UPDATE estudos_recuperacao_codigos SET usado = TRUE WHERE id = :id"), {"id": row["id"]})
    return JSONResponse({"success": True, "message": "Senha alterada com sucesso. Você já pode entrar."})


@router.api_route("/heartbeat", methods=["GET", "POST"])
async def heartbeat(request: Request):
    user_id = request.cookies.get("user_id") or get_signed_cookie(request, "user_id")
    response = JSONResponse({"success": True})
    if user_id:
        try:
            with Session(engine) as session:
                user = session.get(Usuario, int(user_id))
                if user:
                    session.execute(text("UPDATE usuarios SET last_seen = :last_seen WHERE id = :user_id"), {"last_seen": datetime.now(), "user_id": user.id})
                    session.commit()
                    # Renova os cookies da sessão por mais 30 dias
                    _set_session_cookies(response, user)
                    if _is_study_account_allowed(user):
                        new_study_token = create_study_access_token(str(user.id))
                        if new_study_token:
                            forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
                            response.set_cookie(
                                "study_access",
                                new_study_token,
                                path="/",
                                max_age=SESSION_COOKIE_MAX_AGE,
                                httponly=True,
                                secure=forwarded_proto == "https",
                                samesite="lax",
                            )
        except Exception as exc:
            print(f"[HEARTBEAT] Nao foi possivel atualizar presenca: {exc}")
    return response


@router.post("/logout")
async def logout(request: Request):
    user_id = request.cookies.get("user_id") or get_signed_cookie(request, "user_id")
    if user_id:
        try:
            with Session(engine) as session:
                session.execute(text("UPDATE usuarios SET last_seen = NULL WHERE id = :user_id"), {"user_id": int(user_id)})
                session.commit()
        except Exception as exc:
            print(f"[LOGOUT] Nao foi possivel limpar presenca: {exc}")
    response = JSONResponse({"success": True})
    for key in ("user_id", "user_name", "username", "user_role", "user_perms", "study_access"):
        response.delete_cookie(key, path="/")
    response.delete_cookie("study_access", path="/estudos")
    return response
