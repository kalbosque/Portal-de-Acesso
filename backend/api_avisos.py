from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from database import engine
from models import AvisoCarrossel
from auth_utils import get_signed_cookie

router = APIRouter()

def get_user_role(request: Request):
    username = get_signed_cookie(request, "user_name")
    role = get_signed_cookie(request, "user_role")
    return username, role

# GET: Listar todos os avisos ativos
@router.get("/api/avisos")
def listar_avisos(request: Request):
    with Session(engine) as session:
        avisos = session.exec(select(AvisoCarrossel).where(AvisoCarrossel.ativo == True)).all()
        return JSONResponse([{
            "id": a.id,
            "icone": a.icone,
            "titulo": a.titulo,
            "mensagem": a.mensagem,
            "cor": a.cor,
            "criado_por": a.criado_por,
            "criado_em": a.criado_em.strftime("%d/%m/%Y") if a.criado_em else ""
        } for a in avisos])

# POST: Criar novo aviso (somente admin)
@router.post("/api/avisos")
async def criar_aviso(
    request: Request,
    icone: str = Form(default="📣"),
    titulo: str = Form(...),
    mensagem: str = Form(...),
    cor: str = Form(default="indigo")
):
    username, role = get_user_role(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas administradores podem gerenciar avisos.")

    with Session(engine) as session:
        aviso = AvisoCarrossel(
            icone=icone,
            titulo=titulo,
            mensagem=mensagem,
            cor=cor,
            criado_por=username or "admin"
        )
        session.add(aviso)
        session.commit()
        session.refresh(aviso)
        return JSONResponse({"ok": True, "id": aviso.id})

# DELETE: Remover aviso (somente admin)
@router.delete("/api/avisos/{aviso_id}")
def deletar_aviso(aviso_id: int, request: Request):
    username, role = get_user_role(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    with Session(engine) as session:
        aviso = session.get(AvisoCarrossel, aviso_id)
        if not aviso:
            raise HTTPException(status_code=404, detail="Aviso não encontrado.")
        session.delete(aviso)
        session.commit()
        return JSONResponse({"ok": True})
