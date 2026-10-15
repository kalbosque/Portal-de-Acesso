"""Administração da estrutura multiempresa do módulo Atendimento.

Esta API apenas cadastra a fundação de tenants. O isolamento das rotas do
Atendimento permanece desligado até a fase de piloto.
"""

import json
import re
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from sqlalchemy import text

from auth_utils import get_signed_cookie, set_signed_cookie
from database import engine
from models import Usuario
from api_users_mgmt import hash_password
from atendimento_tenant_context import resolve_context

router = APIRouter(prefix="/api/atendimento/tenants", tags=["Atendimento Multiempresa"])
DOCUMENTO_RE = re.compile(r"^\d{11,14}$")


def _require_platform_admin(request: Request) -> None:
    if not get_signed_cookie(request, "user_id"):
        raise HTTPException(status_code=401, detail="Não autenticado")
    if get_signed_cookie(request, "user_role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso exclusivo ao administrador principal")


def _require_company_manager(request: Request, company_id: int) -> bool:
    """Permite ao admin global ou ao tenant_admin da própria empresa."""
    if not get_signed_cookie(request, "user_id"):
        raise HTTPException(status_code=401, detail="Não autenticado")
    if get_signed_cookie(request, "user_role") == "admin":
        return True
    context = resolve_context(request)
    if context.tenant_id != company_id:
        raise HTTPException(status_code=403, detail="Você só pode administrar sua própria empresa")
    with Session(engine) as session:
        allowed = session.exec(text("""
            SELECT 1 FROM usuarios_empresas_atendimento
            WHERE empresa_atendimento_id = :company_id AND usuario_id = :user_id
              AND papel = 'tenant_admin' AND ativo = TRUE
        """).bindparams(company_id=company_id, user_id=int(context.user_id))).first()
    if not allowed:
        raise HTTPException(status_code=403, detail="Apenas o administrador da empresa pode realizar esta alteração")
    return False


def _json_list(value: str, field: str) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field} deve ser uma lista JSON") from exc
    if not isinstance(data, list) or not all(isinstance(item, str) and item.strip() for item in data):
        raise HTTPException(status_code=400, detail=f"{field} deve conter uma lista de textos")
    return list(dict.fromkeys(item.strip() for item in data))


def _document_type(documento: str) -> str:
    return "CPF" if len(documento) == 11 else "CNPJ"


@router.get("/plans")
def list_plans(request: Request):
    _require_platform_admin(request)
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT id, codigo, nome, modulos, limite_usuarios,
                   limite_instancias_whatsapp, ativo
            FROM planos_atendimento ORDER BY id
        """)).mappings().all()
    return [dict(row) for row in rows]


@router.get("/context")
def atendimento_context(request: Request):
    """Lista as empresas de Atendimento disponíveis para o usuário logado."""
    user_id = get_signed_cookie(request, "user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if get_signed_cookie(request, "user_role") == "admin":
        return {"admin": True, "selected": None, "companies": []}
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT e.id, e.nome, e.documento, ue.papel
            FROM usuarios_empresas_atendimento ue
            JOIN empresas_atendimento e ON e.id = ue.empresa_atendimento_id
            WHERE ue.usuario_id = :usuario_id AND ue.ativo = TRUE AND e.status = 'ativa'
            ORDER BY e.nome
        """).bindparams(usuario_id=int(user_id))).mappings().all()
    selected = get_signed_cookie(request, "atendimento_tenant_id")
    return {
        "admin": False,
        "selected": int(selected) if selected and str(selected).isdigit() else None,
        "companies": [dict(row) for row in rows],
    }


@router.post("/context/select/{company_id}")
def select_atendimento_company(company_id: int, request: Request):
    """Seleciona uma empresa válida para a sessão atual do Atendimento."""
    user_id = get_signed_cookie(request, "user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if get_signed_cookie(request, "user_role") == "admin":
        raise HTTPException(status_code=400, detail="Administrador não precisa selecionar empresa")
    with Session(engine) as session:
        allowed = session.exec(text("""
            SELECT 1
            FROM usuarios_empresas_atendimento ue
            JOIN empresas_atendimento e ON e.id = ue.empresa_atendimento_id
            WHERE ue.usuario_id = :usuario_id AND ue.empresa_atendimento_id = :company_id
              AND ue.ativo = TRUE AND e.status = 'ativa'
        """).bindparams(usuario_id=int(user_id), company_id=company_id)).first()
    if not allowed:
        raise HTTPException(status_code=403, detail="Usuário não vinculado a esta empresa")
    response = JSONResponse({"success": True, "company_id": company_id})
    set_signed_cookie(response, "atendimento_tenant_id", str(company_id))
    return response


@router.post("/plans")
def create_plan(
    request: Request,
    codigo: str = Form(...),
    nome: str = Form(...),
    modulos: str = Form("[]"),
    limite_usuarios: Optional[int] = Form(None),
    limite_instancias_whatsapp: Optional[int] = Form(None),
):
    _require_platform_admin(request)
    codigo = codigo.strip().lower()
    nome = nome.strip()
    modules = _json_list(modulos, "modulos")
    if not codigo or not nome:
        raise HTTPException(status_code=400, detail="Código e nome são obrigatórios")
    if limite_usuarios is not None and limite_usuarios <= 0:
        raise HTTPException(status_code=400, detail="Limite de usuários inválido")
    if limite_instancias_whatsapp is not None and limite_instancias_whatsapp <= 0:
        raise HTTPException(status_code=400, detail="Limite de instâncias inválido")
    try:
        with Session(engine) as session:
            row = session.exec(text("""
                INSERT INTO planos_atendimento
                    (codigo, nome, modulos, limite_usuarios, limite_instancias_whatsapp)
                VALUES (:codigo, :nome, CAST(:modulos AS jsonb), :limite_usuarios, :limite_instancias)
                RETURNING id
            """).bindparams(
                codigo=codigo,
                nome=nome,
                modulos=json.dumps(modules),
                limite_usuarios=limite_usuarios,
                limite_instancias=limite_instancias_whatsapp,
            )).one()
            session.commit()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Não foi possível criar o plano. Verifique se o código já existe.") from exc
    return {"success": True, "id": row[0]}


@router.get("/companies")
def list_companies(request: Request):
    _require_platform_admin(request)
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT e.id, e.documento, e.nome, e.status, e.plano_id,
                   e.limite_usuarios_custom, e.limite_instancias_whatsapp_custom,
                   p.nome AS plano_nome,
                   (SELECT count(*) FROM usuarios_empresas_atendimento ue
                    WHERE ue.empresa_atendimento_id = e.id AND ue.ativo = TRUE) AS usuarios,
                   (SELECT count(*) FROM instancias_whatsapp_tenant iw
                    WHERE iw.empresa_atendimento_id = e.id AND iw.ativa = TRUE) AS instancias,
                   COALESCE(e.limite_usuarios_custom, (SELECT count(*) FROM usuarios_empresas_atendimento ue2 WHERE ue2.empresa_atendimento_id = e.id AND ue2.ativo = TRUE)) AS limite_usuarios,
                   COALESCE(e.limite_instancias_whatsapp_custom, (SELECT count(*) FROM instancias_whatsapp_tenant iw2 WHERE iw2.empresa_atendimento_id = e.id AND iw2.ativa = TRUE)) AS limite_instancias_whatsapp
            FROM empresas_atendimento e
            LEFT JOIN planos_atendimento p ON p.id = e.plano_id
            ORDER BY e.id DESC
        """)).mappings().all()
    return [dict(row) for row in rows]


@router.get("/users")
def list_users(request: Request):
    _require_platform_admin(request)
    with Session(engine) as session:
        users = session.exec(
            select(Usuario).where(Usuario.status_conta == "ativo").order_by(Usuario.nome, Usuario.username)
        ).all()
    return [{"id": user.id, "nome": user.nome or user.username, "username": user.username, "email": user.email} for user in users]


@router.get("/companies/{company_id}/management")
def company_management(company_id: int, request: Request):
    """Retorna a estrutura operacional visível ao administrador da empresa."""
    is_global = _require_company_manager(request, company_id)
    with Session(engine) as session:
        company = session.exec(text("SELECT id, nome FROM empresas_atendimento WHERE id = :id AND status = 'ativa'").bindparams(id=company_id)).mappings().first()
        if not company:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
        users = session.exec(text("""
            SELECT u.id, u.nome, u.username, u.email, ue.papel,
                   COALESCE(json_agg(DISTINCT jsonb_build_object('id', s.id, 'nome', s.nome))
                    FILTER (WHERE s.id IS NOT NULL), '[]'::json) AS setores
            FROM usuarios_empresas_atendimento ue
            JOIN usuarios u ON u.id = ue.usuario_id
            LEFT JOIN usuarios_setores_atendimento us ON us.usuario_id = u.id
            LEFT JOIN setores_atendimento s ON s.id = us.setor_id AND s.empresa_atendimento_id = ue.empresa_atendimento_id
            WHERE ue.empresa_atendimento_id = :id AND ue.ativo = TRUE
            GROUP BY u.id, u.nome, u.username, u.email, ue.papel
            ORDER BY u.nome, u.username
        """).bindparams(id=company_id)).mappings().all()
        sectors = session.exec(text("SELECT id, nome, ativo FROM setores_atendimento WHERE empresa_atendimento_id = :id ORDER BY nome").bindparams(id=company_id)).mappings().all()
        instances = session.exec(text("""
            SELECT i.id, i.instance_name, i.label,
                   COALESCE(json_agg(DISTINCT jsonb_build_object('id', s.id, 'nome', s.nome))
                    FILTER (WHERE s.id IS NOT NULL), '[]'::json) AS setores
            FROM instancias_whatsapp_tenant i
            LEFT JOIN instancias_setores_atendimento iset ON iset.instancia_id = i.id
            LEFT JOIN setores_atendimento s ON s.id = iset.setor_id AND s.empresa_atendimento_id = :id
            WHERE i.empresa_atendimento_id = :id AND i.ativa = TRUE
            GROUP BY i.id, i.instance_name, i.label ORDER BY i.label, i.instance_name
        """).bindparams(id=company_id)).mappings().all()
    return {"company": dict(company), "global_admin": is_global, "users": [dict(row) for row in users], "sectors": [dict(row) for row in sectors], "instances": [dict(row) for row in instances]}


@router.post("/companies/{company_id}/sectors")
def create_company_sector(company_id: int, request: Request, nome: str = Form(...)):
    _require_company_manager(request, company_id)
    nome = nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Informe o nome do setor")
    with Session(engine) as session:
        try:
            row = session.exec(text("""
                INSERT INTO setores_atendimento (empresa_atendimento_id, nome)
                VALUES (:company_id, :nome) RETURNING id, nome, ativo
            """).bindparams(company_id=company_id, nome=nome)).mappings().one()
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail="Setor já cadastrado ou empresa inválida") from exc
    return dict(row)


@router.post("/companies/{company_id}/users/create")
def create_company_user(
    company_id: int, request: Request, nome: str = Form(...), email: str = Form(...),
    username: str = Form(...), password: str = Form(...), papel: str = Form("operador"),
):
    _require_company_manager(request, company_id)
    if papel not in {"tenant_admin", "operador"} or len(password) < 6:
        raise HTTPException(status_code=400, detail="Perfil inválido ou senha muito curta")
    with Session(engine) as session:
        if session.exec(select(Usuario).where(Usuario.email == email.strip())).first() or session.exec(select(Usuario).where(Usuario.username == username.strip())).first():
            raise HTTPException(status_code=400, detail="E-mail ou usuário já cadastrado")
        company = session.exec(text("SELECT id FROM empresas_atendimento WHERE id = :id AND status = 'ativa'").bindparams(id=company_id)).first()
        if not company:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
        user = Usuario(nome=nome.strip(), email=email.strip(), username=username.strip(), password_hash=hash_password(password), role="cliente_atendimento", status_conta="ativo", permissoes=json.dumps(["Atendimento"]))
        session.add(user)
        session.flush()
        session.exec(text("""
            INSERT INTO usuarios_empresas_atendimento (empresa_atendimento_id, usuario_id, papel, modulos)
            VALUES (:company_id, :user_id, :papel, '["Atendimento"]'::jsonb)
        """).bindparams(company_id=company_id, user_id=user.id, papel=papel))
        session.commit()
    return {"success": True, "user_id": user.id}


@router.post("/companies/{company_id}/users/{user_id}/sectors")
def link_user_sector(company_id: int, user_id: int, request: Request, sector_id: int = Form(...)):
    _require_company_manager(request, company_id)
    with Session(engine) as session:
        valid = session.exec(text("""
            SELECT 1 FROM usuarios_empresas_atendimento ue JOIN setores_atendimento s ON s.empresa_atendimento_id = ue.empresa_atendimento_id
            WHERE ue.empresa_atendimento_id = :company_id AND ue.usuario_id = :user_id AND ue.ativo = TRUE AND s.id = :sector_id AND s.ativo = TRUE
        """).bindparams(company_id=company_id, user_id=user_id, sector_id=sector_id)).first()
        if not valid:
            raise HTTPException(status_code=400, detail="Usuário ou setor não pertence à empresa")
        session.exec(text("""
            INSERT INTO usuarios_setores_atendimento (usuario_id, setor_id) VALUES (:user_id, :sector_id)
            ON CONFLICT (usuario_id, setor_id) DO NOTHING
        """).bindparams(user_id=user_id, sector_id=sector_id))
        session.commit()
    return {"success": True}


@router.post("/companies/{company_id}/instances/{instance_id}/sectors")
def link_instance_sector(company_id: int, instance_id: int, request: Request, sector_id: int = Form(...)):
    _require_company_manager(request, company_id)
    with Session(engine) as session:
        valid = session.exec(text("""
            SELECT 1 FROM instancias_whatsapp_tenant i JOIN setores_atendimento s ON s.empresa_atendimento_id = i.empresa_atendimento_id
            WHERE i.id = :instance_id AND i.empresa_atendimento_id = :company_id AND i.ativa = TRUE AND s.id = :sector_id AND s.ativo = TRUE
        """).bindparams(instance_id=instance_id, company_id=company_id, sector_id=sector_id)).first()
        if not valid:
            raise HTTPException(status_code=400, detail="Número ou setor não pertence à empresa")
        session.exec(text("""
            INSERT INTO instancias_setores_atendimento (instancia_id, setor_id) VALUES (:instance_id, :sector_id)
            ON CONFLICT (instancia_id, setor_id) DO NOTHING
        """).bindparams(instance_id=instance_id, sector_id=sector_id))
        session.commit()
    return {"success": True}


@router.post("/users/create")
def create_attendance_user(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    company_id: int = Form(...),
    papel: str = Form("operador"),
):
    """Cria uma conta do Portal e já vincula ao Atendimento da empresa."""
    _require_platform_admin(request)
    if papel not in {"tenant_admin", "operador"}:
        raise HTTPException(status_code=400, detail="Papel inválido")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 6 caracteres")
    with Session(engine) as session:
        if session.exec(select(Usuario).where(Usuario.email == email.strip())).first():
            raise HTTPException(status_code=400, detail="E-mail já cadastrado")
        if session.exec(select(Usuario).where(Usuario.username == username.strip())).first():
            raise HTTPException(status_code=400, detail="Usuário já cadastrado")
        company = session.exec(text("SELECT id FROM empresas_atendimento WHERE id = :company_id AND status = 'ativa'").bindparams(company_id=company_id)).first()
        if not company:
            raise HTTPException(status_code=400, detail="Empresa ativa não encontrada")
        user = Usuario(
            nome=nome.strip(), email=email.strip(), username=username.strip(),
            password_hash=hash_password(password), role="cliente_atendimento",
            status_conta="ativo", permissoes=json.dumps(["Atendimento"]),
        )
        session.add(user)
        session.flush()
        session.exec(text("""
            INSERT INTO usuarios_empresas_atendimento
                (empresa_atendimento_id, usuario_id, papel, modulos)
            VALUES (:company_id, :user_id, :papel, CAST(:modulos AS jsonb))
        """).bindparams(company_id=company_id, user_id=user.id, papel=papel, modulos=json.dumps(["Atendimento"])))
        session.commit()
    return {"success": True, "user_id": user.id}


@router.post("/companies")
def create_company(
    request: Request,
    documento: str = Form(...),
    nome: str = Form(...),
    plano_id: Optional[int] = Form(None),
):
    _require_platform_admin(request)
    documento = re.sub(r"\D", "", documento)
    nome = nome.strip()
    if not DOCUMENTO_RE.fullmatch(documento):
        raise HTTPException(status_code=400, detail="Informe um CPF ou CNPJ válido")
    if not nome:
        raise HTTPException(status_code=400, detail="Nome da empresa é obrigatório")
    with Session(engine) as session:
        try:
            row = session.exec(text("""
                INSERT INTO empresas_atendimento (documento, nome, plano_id)
                VALUES (:documento, :nome, :plano_id)
                RETURNING id
            """).bindparams(documento=documento, nome=nome, plano_id=plano_id)).one()
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail="Não foi possível criar a empresa. Verifique documento e plano.") from exc
    return {"success": True, "id": row[0]}


@router.post("/companies/{company_id}/status")
def update_company_status(
    company_id: int,
    request: Request,
    status: str = Form(...),
):
    """Ativa, suspende ou encerra uma empresa do Atendimento."""
    _require_platform_admin(request)
    if status not in {"ativa", "suspensa", "encerrada"}:
        raise HTTPException(status_code=400, detail="Status inválido")
    with Session(engine) as session:
        result = session.exec(text("""
            UPDATE empresas_atendimento
            SET status = :status
            WHERE id = :company_id
            RETURNING id
        """).bindparams(status=status, company_id=company_id)).first()
        if not result:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
        session.commit()
    return {"success": True, "status": status}


@router.post("/companies/{company_id}/limits")
def update_company_limits(
    company_id: int,
    request: Request,
    limite_usuarios: int = Form(...),
    limite_instancias_whatsapp: int = Form(...),
):
    _require_platform_admin(request)
    if limite_usuarios < 0 or limite_instancias_whatsapp < 0:
        raise HTTPException(status_code=400, detail="As quantidades não podem ser negativas")
    with Session(engine) as session:
        result = session.exec(text("""
            UPDATE empresas_atendimento
            SET limite_usuarios_custom = :limite_usuarios,
                limite_instancias_whatsapp_custom = :limite_instancias_whatsapp
            WHERE id = :company_id
            RETURNING id
        """).bindparams(
            company_id=company_id,
            limite_usuarios=limite_usuarios,
            limite_instancias_whatsapp=limite_instancias_whatsapp,
        )).first()
        if not result:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
        session.commit()
    return {"success": True}


@router.post("/companies/{company_id}/users")
def attach_user(
    company_id: int,
    request: Request,
    usuario_id: int = Form(...),
    papel: str = Form("operador"),
    modulos: str = Form("[\"Atendimento\"]"),
):
    _require_platform_admin(request)
    if papel not in {"tenant_admin", "operador"}:
        raise HTTPException(status_code=400, detail="Papel inválido")
    modules = _json_list(modulos, "modulos")
    with Session(engine) as session:
        try:
            session.exec(text("""
                INSERT INTO usuarios_empresas_atendimento
                    (empresa_atendimento_id, usuario_id, papel, modulos)
                VALUES (:company_id, :usuario_id, :papel, CAST(:modulos AS jsonb))
                ON CONFLICT (empresa_atendimento_id, usuario_id)
                DO UPDATE SET papel = EXCLUDED.papel, modulos = EXCLUDED.modulos, ativo = TRUE
            """).bindparams(
                company_id=company_id, usuario_id=usuario_id,
                papel=papel, modulos=json.dumps(modules),
            ))
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail="Empresa ou usuário inválido") from exc
    return {"success": True}


@router.post("/companies/{company_id}/instances")
def attach_instance(
    company_id: int,
    request: Request,
    instance_name: str = Form(...),
    label: str = Form(...),
    padrao: bool = Form(False),
):
    _require_platform_admin(request)
    instance_name = instance_name.strip()
    label = label.strip()
    if not instance_name or not label:
        raise HTTPException(status_code=400, detail="Nome e rótulo da instância são obrigatórios")
    with Session(engine) as session:
        try:
            if padrao:
                session.exec(text("""
                    UPDATE instancias_whatsapp_tenant
                    SET padrao = FALSE
                    WHERE empresa_atendimento_id = :company_id AND ativa = TRUE
                """).bindparams(company_id=company_id))
            session.exec(text("""
                INSERT INTO instancias_whatsapp_tenant
                    (empresa_atendimento_id, instance_name, label, padrao)
                VALUES (:company_id, :instance_name, :label, :padrao)
            """).bindparams(
                company_id=company_id, instance_name=instance_name,
                label=label, padrao=padrao,
            ))
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail="Empresa ou instância inválida; verifique se o nome já existe.") from exc
    return {"success": True}
