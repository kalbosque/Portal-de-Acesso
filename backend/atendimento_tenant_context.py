"""Contexto seguro de empresa para as rotas do módulo Atendimento.

O recurso permanece desligado por padrão. Quando ativado, administradores da
plataforma continuam globais; os demais usuários precisam ter um vínculo
ativo com uma empresa de Atendimento.
"""

import os
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlmodel import Session

from auth_utils import get_signed_cookie
from database import engine
from tenant_core import tenant_feature_enabled


@dataclass(frozen=True)
class AtendimentoTenantContext:
    enabled: bool
    user_id: Optional[int]
    role: str
    tenant_id: Optional[int]


def is_enabled() -> bool:
    return tenant_feature_enabled(os.getenv("ATENDIMENTO_MULTIEMPRESA_ENABLED"))


def resolve_context(request: Request) -> AtendimentoTenantContext:
    raw_user_id = get_signed_cookie(request, "user_id")
    role = get_signed_cookie(request, "user_role", "operator") or "operator"
    user_id = int(raw_user_id) if raw_user_id and str(raw_user_id).isdigit() else None
    if not is_enabled() or role == "admin":
        return AtendimentoTenantContext(is_enabled(), user_id, role, None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")

    requested = get_signed_cookie(request, "atendimento_tenant_id")
    requested_id = int(requested) if requested and str(requested).isdigit() else None
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT ue.empresa_atendimento_id
            FROM usuarios_empresas_atendimento ue
            JOIN empresas_atendimento e ON e.id = ue.empresa_atendimento_id
            WHERE ue.usuario_id = :user_id AND ue.ativo = TRUE AND e.status = 'ativa'
            ORDER BY empresa_atendimento_id
        """).bindparams(user_id=user_id)).all()
    tenant_ids = {int(row[0]) for row in rows}
    if requested_id is not None and requested_id in tenant_ids:
        return AtendimentoTenantContext(True, user_id, role, requested_id)
    if len(tenant_ids) == 1:
        return AtendimentoTenantContext(True, user_id, role, next(iter(tenant_ids)))
    if not tenant_ids:
        raise HTTPException(status_code=403, detail="Usuário sem empresa de Atendimento vinculada")
    raise HTTPException(status_code=409, detail="Selecione a empresa de Atendimento antes de continuar")


def require_tenant(request: Request) -> int:
    context = resolve_context(request)
    if not context.enabled:
        raise HTTPException(status_code=503, detail="Multiempresa do Atendimento ainda não está ativada")
    if context.tenant_id is None:
        raise HTTPException(status_code=403, detail="Empresa de Atendimento não determinada")
    return context.tenant_id


def tenant_id_for_instance(instance_name: Optional[str]) -> Optional[int]:
    """Resolve a empresa da instância usada por um webhook do WhatsApp."""
    if not is_enabled() or not instance_name:
        return None
    with Session(engine) as session:
        row = session.exec(text("""
            SELECT iw.empresa_atendimento_id
            FROM instancias_whatsapp_tenant iw
            JOIN empresas_atendimento e ON e.id = iw.empresa_atendimento_id
            WHERE iw.instance_name = :instance_name AND iw.ativa = TRUE AND e.status = 'ativa'
        """).bindparams(instance_name=instance_name)).first()
    return int(row[0]) if row else None
