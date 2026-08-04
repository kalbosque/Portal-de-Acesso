import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Form, Request, Depends
from sqlmodel import Session, select
from models import Usuario
from database import engine
import bcrypt
from auth_utils import get_current_admin

router = APIRouter(prefix="/api/usuarios", tags=["User Management"], dependencies=[Depends(get_current_admin)])

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
    role: str = Form("operator")
):
    form_data = await request.form()
    perms = form_data.getlist("perms")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Senha muito curta")
        
    with Session(engine) as session:
        exist_email = session.exec(select(Usuario).where(Usuario.email == email)).first()
        if exist_email: raise HTTPException(status_code=400, detail="E-mail já cadastrado")
        
        exist_user = session.exec(select(Usuario).where(Usuario.username == username)).first()
        if exist_user: raise HTTPException(status_code=400, detail="Usuário já existe")
        
        novo = Usuario(
            nome=nome,
            email=email,
            username=username,
            password_hash=hash_password(password),
            role=role,
            status_conta="ativo",
            permissoes=json.dumps(perms)
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
    role: str = Form(...)
):
    form_data = await request.form()
    perms = form_data.getlist("perms")
    with Session(engine) as session:
        user = session.get(Usuario, user_id)
        if not user: raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        user.nome = nome
        user.email = email
        user.role = role
        user.permissoes = json.dumps(perms)
        
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
