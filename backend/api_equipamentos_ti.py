import traceback
import unicodedata

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import Session, select

from auth_utils import get_signed_cookie
from database import engine
from models import EquipamentoTI

router = APIRouter(prefix="/api/equipamentos_ti", tags=["equipamentos_ti"])


def _get_user(request: Request):
    user_name = get_signed_cookie(request, "user_name")
    user_role = get_signed_cookie(request, "user_role")
    if not user_name or not user_role:
        raise HTTPException(status_code=401, detail="Nao autenticado")
    return user_name, user_role


def _simplify_text(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ASCII", "ignore").decode("ASCII").strip().lower()


def _normalize_nome_computador(data: dict) -> dict:
    """Aceita nomes antigos/alternativos e padroniza o campo novo."""
    aliases = ("nome_computador", "nomeComputador", "hostname", "nome_pc", "nome_maquina")
    value = ""
    for key in aliases:
        raw = data.get(key)
        if raw is not None and str(raw).strip():
            value = str(raw).strip()
            break

    if _simplify_text(value) in ("nao informado", "sem informado"):
        value = ""

    data["nome_computador"] = value
    return data


@router.get("")
@router.get("/")
def list_equipamentos(request: Request):
    user_name, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado")

    with Session(engine) as session:
        equipamentos = session.exec(select(EquipamentoTI).order_by(EquipamentoTI.colaborador)).all()
        return [e.dict() for e in equipamentos]


from notifications import send_alert

@router.post("")
@router.post("/")
async def create_equipamento(request: Request):
    user_name, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado")

    try:
        data = _normalize_nome_computador(await request.json())
        with Session(engine) as session:
            equipamento = EquipamentoTI(**data)
            session.add(equipamento)
            session.commit()
            session.refresh(equipamento)
            
            # Enviar Alerta
            msg = (
                f"🆕 *NOVO EQUIPAMENTO DE TI REGISTRADO*\n\n"
                f"👤 Colaborador: {equipamento.colaborador}\n"
                f"💻 Tipo: {equipamento.tipo_equipamento}\n"
                f"🏢 Setor: {equipamento.setor}\n"
                f"📝 Máquina: {equipamento.nome_computador or 'Não informado'}"
            )
            send_alert(msg)
            
            return {"success": True, "equipamento": equipamento.dict()}
    except Exception as exc:
        print(f"[equipamentos_ti] Erro ao criar equipamento: {exc}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Erro ao salvar equipamento")


@router.put("/{equipamento_id}")
async def update_equipamento(equipamento_id: int, request: Request):
    user_name, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado")

    try:
        data = _normalize_nome_computador(await request.json())
        with Session(engine) as session:
            equipamento = session.get(EquipamentoTI, equipamento_id)
            if not equipamento:
                raise HTTPException(status_code=404, detail="Equipamento nao encontrado")

            for key, value in data.items():
                if hasattr(equipamento, key):
                    if key == "nome_computador" and not str(value or "").strip():
                        continue
                    setattr(equipamento, key, value)

            session.commit()
            session.refresh(equipamento)
            return {"success": True, "equipamento": equipamento.dict()}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[equipamentos_ti] Erro ao atualizar equipamento {equipamento_id}: {exc}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Erro ao atualizar equipamento")


@router.delete("/{equipamento_id}")
def delete_equipamento(equipamento_id: int, request: Request):
    user_name, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado")

    try:
        with Session(engine) as session:
            equipamento = session.get(EquipamentoTI, equipamento_id)
            if equipamento:
                session.delete(equipamento)
                session.commit()
            return {"success": True}
    except Exception as exc:
        print(f"[equipamentos_ti] Erro ao excluir equipamento {equipamento_id}: {exc}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Erro ao excluir equipamento")
