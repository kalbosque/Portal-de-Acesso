import json
import hmac
import hashlib
import base64
import os
from fastapi import Request, HTTPException, Response
from fastapi import Depends

SECRET_KEY = os.environ.get("JWT_SECRET", "super-secret-key-change-in-production")

def sign_value(value: str) -> str:
    """Signs a string value with HMAC SHA256."""
    signature = hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"

def verify_value(signed_value: str) -> str:
    """Verifies a signed string value and returns the original value, or None if invalid."""
    if not signed_value or "." not in signed_value:
        return signed_value
    value, signature = signed_value.rsplit(".", 1)
    expected_signature = hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(signature, expected_signature):
        return value
    return None

def set_signed_cookie(response: Response, key: str, value: str):
    """Sets a signed cookie."""
    response.set_cookie(key=key, value=sign_value(str(value)), httponly=True)

def get_signed_cookie(request: Request, key: str, default: str = None) -> str:
    """Gets and verifies a signed cookie."""
    cookie = request.cookies.get(key)
    val = verify_value(cookie) if cookie else None
    return val if val is not None else default

def _get_user_perms(request: Request) -> list:
    """Extrai a lista de permissões do cookie da sessão."""
    raw = get_signed_cookie(request, "user_perms") or "[]"
    try:
        return json.loads(raw)
    except Exception:
        return []


def normalize_permissions(perms) -> list:
    """Normaliza permissões antigas e novas para os rótulos usados no front-end."""
    mapping = {
        "dashboard": "Dashboard",
        "equipamentos": "Equipamentos",
        "relatorios": "Relatórios",
        "usuarios": "Usuários",
        "chamados": "Suporte",
        "suporte": "Suporte",
        "modulo_tickets": "Suporte",
        "config_suporte": "Ajustes",
        "ajustes": "Ajustes",
        "atendimento": "Atendimento",
    }
    normalized = []
    for perm in perms or []:
        key = str(perm).strip()
        if not key:
            continue
        normalized.append(mapping.get(key.lower(), key))
    return list(dict.fromkeys(normalized))


async def get_current_user(request: Request) -> str:
    """Exige apenas que o usuário esteja autenticado (qualquer role)."""
    user_id = get_signed_cookie(request, "user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return user_id


async def get_current_admin(request: Request) -> str:
    """Exige que o usuário seja administrador."""
    user_id = get_signed_cookie(request, "user_id")
    user_role = get_signed_cookie(request, "user_role")
    if not user_id or user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso exclusivo para administradores")
    return user_id


async def require_equipamentos(request: Request) -> str:
    """
    Exige que o usuário esteja autenticado E tenha permissão de 'Equipamentos'
    (ou seja administrador, que tem acesso total).
    """
    user_id = get_signed_cookie(request, "user_id")
    user_role = get_signed_cookie(request, "user_role")

    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    if user_role == "admin":
        return user_id

    perms = _get_user_perms(request)
    if "Equipamentos" not in perms:
        raise HTTPException(
            status_code=403,
            detail="Acesso negado: permissão 'Equipamentos' necessária"
        )

    return user_id
