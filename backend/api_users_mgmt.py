import json
import os
import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Form, Request, Depends, UploadFile, File
from sqlmodel import Session, select
from sqlalchemy import text
from models import Usuario
from database import engine
import bcrypt
from auth_utils import get_current_admin

router = APIRouter(prefix="/api/usuarios", tags=["User Management"], dependencies=[Depends(get_current_admin)])

CLIENT_ATTENDANCE_ROLE = "cliente_atendimento"

def _ensure_company_columns():
    for statement in (
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS empresa_nome VARCHAR(255)",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS empresa_logo_url VARCHAR(500)",
    ):
        try:
            with engine.begin() as conn:
                conn.execute(text(statement))
        except Exception as exc:
            print(f"[USUARIOS] Migração de empresa ignorada: {exc}")

async def _save_company_logo(upload: UploadFile) -> str:
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/svg+xml": ".svg"}
    extension = allowed.get(upload.content_type or "")
    if not extension:
        raise HTTPException(status_code=400, detail="Logo inválida. Use JPG, PNG, WEBP, GIF ou SVG")
    content = await upload.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="A logo deve ter no máximo 5 MB")
    upload_dir = os.path.join(os.path.dirname(__file__), "public_html", "uploads", "empresas")
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"empresa-{uuid.uuid4().hex}{extension}"
    with open(os.path.join(upload_dir, filename), "wb") as output:
        output.write(content)
    return f"uploads/empresas/{filename}"

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8')[:72], bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pwd_bytes = plain_password.encode('utf-8')[:72]
        hash_bytes = hashed_password.encode('utf-8')
        if hash_bytes.startswith(b"$2y$"):
            hash_bytes = b"$2b$" + hash_bytes[4:]
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except:
        return False

@router.get("/list")
async def list_users():
    _ensure_company_columns()
    with Session(engine) as session:
        users = session.exec(select(Usuario).order_by(Usuario.created_at.desc())).all()
        return {
            "success": True,
            "usuarios": [u.dict(exclude={"password_hash"}) for u in users]
        }

@router.post("/create")
async def create_user(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("operator"),
    empresa_nome: str = Form(""),
    empresa_logo_upload: Optional[UploadFile] = File(None)
):
    _ensure_company_columns()
    form_data = await request.form()
    perms = form_data.getlist("perms")
    if role == CLIENT_ATTENDANCE_ROLE:
        perms = ["Atendimento"]
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Senha muito curta")
        
    with Session(engine) as session:
        exist_email = session.exec(select(Usuario).where(Usuario.email == email)).first()
        if exist_email: raise HTTPException(status_code=400, detail="E-mail já cadastrado")
        
        exist_user = session.exec(select(Usuario).where(Usuario.username == username)).first()
        if exist_user: raise HTTPException(status_code=400, detail="Usuário já existe")
        
        empresa_logo_url = None
        if empresa_logo_upload and empresa_logo_upload.filename:
            empresa_logo_url = await _save_company_logo(empresa_logo_upload)
        novo = Usuario(
            nome=nome,
            email=email,
            username=username,
            password_hash=hash_password(password),
            role=role,
            status_conta="ativo",
            permissoes=json.dumps(perms)
            , empresa_nome=empresa_nome.strip() or None,
            empresa_logo_url=empresa_logo_url,
        )
        session.add(novo)
        session.commit()
        return {"success": True, "message": "Usuário criado"}

@router.post("/edit_pass")
async def edit_password(user_id: int = Form(...), new_password: str = Form(...)):
    with Session(engine) as session:
        user = session.get(Usuario, user_id)
        if not user: raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        user.password_hash = hash_password(new_password)
        session.add(user)
        session.commit()
        return {"success": True, "message": "Senha alterada"}

@router.post("/edit_perms")
async def edit_perms(
    request: Request,
    user_id: int = Form(...),
    nome: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    empresa_nome: str = Form(""),
    empresa_logo_upload: Optional[UploadFile] = File(None)
):
    _ensure_company_columns()
    form_data = await request.form()
    perms = form_data.getlist("perms")
    if role == CLIENT_ATTENDANCE_ROLE:
        perms = ["Atendimento"]
    with Session(engine) as session:
        user = session.get(Usuario, user_id)
        if not user: raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        user.nome = nome
        user.email = email
        user.role = role
        user.permissoes = json.dumps(perms)
        user.empresa_nome = empresa_nome.strip() or None
        if empresa_logo_upload and empresa_logo_upload.filename:
            user.empresa_logo_url = await _save_company_logo(empresa_logo_upload)
        
        session.add(user)
        session.commit()
        return {"success": True, "message": "Dados atualizados"}

@router.post("/set_status")
async def set_status(user_id: int = Form(...), status: str = Form(...)):
    with Session(engine) as session:
        user = session.get(Usuario, user_id)
        if not user: raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        user.status_conta = status
        session.add(user)
        session.commit()
        return {"success": True, "message": f"Status alterado para {status}"}

@router.post("/delete")
async def delete_user(user_id: int = Form(...)):
    with Session(engine) as session:
        user = session.get(Usuario, user_id)
        if not user: raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        if user.role == "admin":
            raise HTTPException(status_code=403, detail="Não é permitido excluir administradores")
            
        session.delete(user)
        session.commit()
        return {"success": True, "message": "Usuário removido"}
