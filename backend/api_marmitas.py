from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from auth_utils import get_signed_cookie
from database import engine
from models import MarmitaCardapio, MarmitaPedido

router = APIRouter(prefix="/api/marmitas", tags=["marmitas"])


def _get_user(request: Request):
    user_name = get_signed_cookie(request, "user_name")
    user_role = get_signed_cookie(request, "user_role")
    if not user_name or not user_role:
        raise HTTPException(status_code=401, detail="Nao autenticado")
    return user_name, user_role


def _require_admin(request: Request):
    user_name, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso exclusivo para administradores")
    return user_name


@router.get("/cardapio")
def list_cardapio(request: Request):
    _, user_role = _get_user(request)
    with Session(engine) as session:
        query = select(MarmitaCardapio).order_by(MarmitaCardapio.ativo.desc(), MarmitaCardapio.id.desc())
        if user_role != "admin":
            query = query.where(MarmitaCardapio.ativo == True)
        itens = session.exec(query).all()
        return JSONResponse([
            {
                "id": item.id,
                "titulo": item.titulo,
                "descricao": item.descricao,
                "horario_limite": item.horario_limite,
                "ativo": item.ativo,
                "data_referencia": item.data_referencia.strftime("%d/%m/%Y") if item.data_referencia else "",
                "criado_por": item.criado_por,
                "criado_em": item.criado_em.strftime("%d/%m/%Y %H:%M") if item.criado_em else "",
            }
            for item in itens
        ])


@router.post("/cardapio")
async def create_cardapio(request: Request):
    user_name = _require_admin(request)
    data = await request.json()
    titulo = (data.get("titulo") or "").strip()
    if not titulo:
        raise HTTPException(status_code=400, detail="Titulo obrigatorio")

    with Session(engine) as session:
        item = MarmitaCardapio(
            titulo=titulo,
            descricao=(data.get("descricao") or "").strip() or None,
            horario_limite=(data.get("horario_limite") or "").strip() or None,
            ativo=bool(data.get("ativo", True)),
            criado_por=user_name or "admin",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return JSONResponse({"ok": True, "id": item.id})


@router.delete("/cardapio/{item_id}")
def delete_cardapio(item_id: int, request: Request):
    _require_admin(request)
    with Session(engine) as session:
        item = session.get(MarmitaCardapio, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item nao encontrado")
        session.delete(item)
        session.commit()
        return JSONResponse({"ok": True})


@router.get("/pedidos")
def list_pedidos(request: Request):
    _require_admin(request)
    with Session(engine) as session:
        cardapios = {c.id: c for c in session.exec(select(MarmitaCardapio)).all()}
        pedidos = session.exec(select(MarmitaPedido).order_by(MarmitaPedido.data_pedido.desc(), MarmitaPedido.id.desc())).all()
        return JSONResponse([
            {
                "id": pedido.id,
                "cardapio_id": pedido.cardapio_id,
                "cardapio_titulo": cardapios.get(pedido.cardapio_id).titulo if cardapios.get(pedido.cardapio_id) else "Cardapio removido",
                "colaborador": pedido.colaborador,
                "setor": pedido.setor,
                "quantidade": pedido.quantidade,
                "observacao": pedido.observacao,
                "status": pedido.status,
                "data_pedido": pedido.data_pedido.strftime("%d/%m/%Y %H:%M") if pedido.data_pedido else "",
                "entregue_em": pedido.entregue_em.strftime("%d/%m/%Y %H:%M") if pedido.entregue_em else "",
            }
            for pedido in pedidos
        ])


@router.post("/pedidos")
async def create_pedido(request: Request):
    user_name, user_role = _get_user(request)
    data = await request.json()
    cardapio_id = data.get("cardapio_id")
    if not cardapio_id:
        raise HTTPException(status_code=400, detail="Selecione um item do cardapio")

    colaborador = (data.get("colaborador") or "").strip() or user_name
    if user_role != "admin":
        colaborador = user_name

    quantidade = int(data.get("quantidade") or 1)
    if quantidade < 1:
        quantidade = 1

    with Session(engine) as session:
        cardapio = session.get(MarmitaCardapio, int(cardapio_id))
        if not cardapio:
            raise HTTPException(status_code=404, detail="Cardapio nao encontrado")
        if user_role != "admin" and not cardapio.ativo:
            raise HTTPException(status_code=400, detail="Cardapio indisponivel")

        pedido = MarmitaPedido(
            cardapio_id=cardapio.id,
            colaborador=colaborador,
            setor=(data.get("setor") or "").strip() or None,
            quantidade=quantidade,
            observacao=(data.get("observacao") or "").strip() or None,
            status=(data.get("status") or "Pendente").strip() or "Pendente",
            criado_por=user_name or "admin",
        )
        session.add(pedido)
        session.commit()
        session.refresh(pedido)
        return JSONResponse({"ok": True, "id": pedido.id})


@router.post("/pedidos/{pedido_id}/entregar")
def mark_entregue(pedido_id: int, request: Request):
    user_name = _require_admin(request)
    with Session(engine) as session:
        pedido = session.get(MarmitaPedido, pedido_id)
        if not pedido:
            raise HTTPException(status_code=404, detail="Pedido nao encontrado")
        pedido.status = "Entregue"
        pedido.entregue_em = datetime.now()
        pedido.criado_por = pedido.criado_por or user_name or "admin"
        session.add(pedido)
        session.commit()
        return JSONResponse({"ok": True})


@router.delete("/pedidos/{pedido_id}")
def delete_pedido(pedido_id: int, request: Request):
    _require_admin(request)
    with Session(engine) as session:
        pedido = session.get(MarmitaPedido, pedido_id)
        if not pedido:
            raise HTTPException(status_code=404, detail="Pedido nao encontrado")
        session.delete(pedido)
        session.commit()
        return JSONResponse({"ok": True})
