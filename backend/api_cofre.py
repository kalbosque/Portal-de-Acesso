import os
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, desc

from auth_utils import get_current_admin
from database import engine
from models import CofreSenha

router = APIRouter(prefix="/api/cofre", tags=["Cofre de Senhas"], dependencies=[Depends(get_current_admin)])

# ---------------------------------------------------------------------------
# Criptografia Fernet — chave derivada de COFRE_SECRET_KEY (.env)
# ---------------------------------------------------------------------------
_RAW_KEY = os.environ["COFRE_SECRET_KEY"]
_FERNET_KEY = base64.urlsafe_b64encode(hashlib.sha256(_RAW_KEY.encode()).digest())
_fernet = Fernet(_FERNET_KEY)


def _encrypt(plain: str) -> str:
    return _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def _decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/list")
async def list_credentials():
    """Lista todas as credenciais — senhas mascaradas."""
    with Session(engine) as session:
        items = session.exec(select(CofreSenha).order_by(desc(CofreSenha.criado_em))).all()
        result = []
        for item in items:
            d = item.dict()
            d["senha_cifrada"] = "●●●●●●●●"
            result.append(d)
        return {"success": True, "credenciais": result}


@router.get("/reveal/{item_id}")
async def reveal_password(item_id: int):
    """Retorna a senha decifrada de uma credencial específica."""
    with Session(engine) as session:
        item = session.get(CofreSenha, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Credencial não encontrada")
        try:
            senha_real = _decrypt(item.senha_cifrada)
        except Exception:
            senha_real = "[Erro ao decifrar]"
        return {"success": True, "senha": senha_real}


@router.post("/create")
async def create_credential(
    titulo: str = Form(...),
    categoria: str = Form("E-mail"),
    setor: str = Form("TI"),
    login_email: str = Form(...),
    senha: str = Form(...),
    url: Optional[str] = Form(None),
    observacoes: Optional[str] = Form(None),
):
    """Cria nova credencial no cofre."""
    with Session(engine) as session:
        novo = CofreSenha(
            titulo=titulo.strip(),
            categoria=categoria.strip(),
            setor=setor.strip(),
            login_email=login_email.strip(),
            senha_cifrada=_encrypt(senha),
            url=(url or "").strip() or None,
            observacoes=(observacoes or "").strip() or None,
        )
        session.add(novo)
        session.commit()
        session.refresh(novo)
    return JSONResponse({"success": True, "message": "Credencial salva com sucesso!", "id": novo.id})


@router.post("/edit")
async def edit_credential(
    id: int = Form(...),
    titulo: str = Form(...),
    categoria: str = Form("E-mail"),
    setor: str = Form("TI"),
    login_email: str = Form(...),
    senha: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    observacoes: Optional[str] = Form(None),
):
    """Edita credencial existente. Se 'senha' vier vazio, mantém a anterior."""
    with Session(engine) as session:
        item = session.get(CofreSenha, id)
        if not item:
            raise HTTPException(status_code=404, detail="Credencial não encontrada")

        item.titulo = titulo.strip()
        item.categoria = categoria.strip()
        item.setor = setor.strip()
        item.login_email = login_email.strip()
        item.url = (url or "").strip() or None
        item.observacoes = (observacoes or "").strip() or None

        if senha and senha.strip():
            item.senha_cifrada = _encrypt(senha.strip())

        from datetime import datetime
        item.atualizado_em = datetime.now()

        session.add(item)
        session.commit()
    return JSONResponse({"success": True, "message": "Credencial atualizada!"})


@router.post("/delete")
async def delete_credential(id: int = Form(...)):
    """Remove credencial do cofre."""
    with Session(engine) as session:
        item = session.get(CofreSenha, id)
        if not item:
            raise HTTPException(status_code=404, detail="Credencial não encontrada")
        session.delete(item)
        session.commit()
    return JSONResponse({"success": True, "message": "Credencial removida!"})
