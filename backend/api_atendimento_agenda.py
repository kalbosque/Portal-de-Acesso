import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Request
from sqlalchemy import text
from sqlmodel import Session, select

import api_whatsapp
from atendimento_tenant_context import is_enabled as atendimento_multiempresa_enabled
from atendimento_tenant_context import resolve_context, tenant_id_for_instance
from auth_utils import get_signed_cookie
from database import engine
from models import AtendimentoAgendaConfig, AtendimentoAgendamento, MensagemWhatsAppAgendada

router = APIRouter(prefix="/api/atendimento/agenda", tags=["Agenda do Atendimento"])
SETTING_KEY = "ATENDIMENTO_AGENDAMENTOS_ENABLED"


def _local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    local_tz = _local_timezone()
    start = datetime.combine(day, time.min, tzinfo=local_tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=local_tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def get_agenda_settings(config: Optional[dict] = None, tenant_id: Optional[int] = None) -> dict:
    """Busca as configurações da agenda diretamente no banco PostgreSQL por empresa."""
    nome_padrao = "Barbearia & Salão"
    if tenant_id is not None:
        try:
            with Session(engine) as session:
                comp = session.exec(text("SELECT nome FROM empresas_atendimento WHERE id = :tid").bindparams(tid=tenant_id)).first()
                if comp and comp[0]:
                    nome_padrao = comp[0]
        except Exception:
            pass
    elif config:
        nome_padrao = config.get("AGENDA_ESTABELECIMENTO_NOME") or "Barbearia & Salão"

    try:
        with Session(engine) as session:
            query = select(AtendimentoAgendaConfig)
            if tenant_id is not None:
                query = query.where(AtendimentoAgendaConfig.empresa_atendimento_id == tenant_id)
            else:
                query = query.where(AtendimentoAgendaConfig.empresa_atendimento_id.is_(None))
            db_cfg = session.exec(query).first()

            if db_cfg:
                dias_raw = None
                if db_cfg.dias_semana:
                    try:
                        dias_raw = json.loads(db_cfg.dias_semana)
                    except Exception:
                        dias_raw = None
                if not isinstance(dias_raw, list):
                    dias = [0, 1, 2, 3, 4, 5]
                else:
                    dias = [int(d) for d in dias_raw if 0 <= int(d) <= 6]

                return {
                    "enabled": bool(db_cfg.enabled),
                    "estabelecimento_nome": db_cfg.estabelecimento_nome or nome_padrao,
                    "mensagem_boas_vindas": db_cfg.mensagem_boas_vindas or "Olá! Bem-vindo(a) ao nosso atendimento! Como podemos te ajudar hoje?",
                    "servicos_precos": db_cfg.servicos_precos or "",
                    "endereco": db_cfg.endereco or "",
                    "horarios_info": db_cfg.horarios_info or "Segunda a Sábado das 08:00 às 18:00",
                    "duracao_minutos": int(db_cfg.duracao_minutos or 60),
                    "hora_abertura": db_cfg.hora_abertura or "08:00",
                    "hora_fechamento": db_cfg.hora_fechamento or "18:00",
                    "almoco_inicio": db_cfg.almoco_inicio if db_cfg.almoco_inicio is not None else "12:00",
                    "almoco_fim": db_cfg.almoco_fim if db_cfg.almoco_fim is not None else "13:00",
                    "dias_semana": dias,
                }
    except Exception as exc:
        print(f"[AGENDA] Erro ao consultar atendimento_agenda_config no banco: {exc}")

    # Padrão limpo e seguro para novas empresas (sem vazar dados de outra empresa!)
    return {
        "enabled": False,
        "estabelecimento_nome": nome_padrao,
        "mensagem_boas_vindas": "Olá! Bem-vindo(a) ao nosso atendimento! Como podemos te ajudar hoje?",
        "servicos_precos": "",
        "endereco": "",
        "horarios_info": "Segunda a Sábado das 08:00 às 18:00",
        "duracao_minutos": 60,
        "hora_abertura": "08:00",
        "hora_fechamento": "18:00",
        "almoco_inicio": "12:00",
        "almoco_fim": "13:00",
        "dias_semana": [0, 1, 2, 3, 4, 5],
    }


def _available_slots(
    day: date,
    booked_starts: list[datetime],
    now: Optional[datetime] = None,
    settings: Optional[dict] = None,
) -> list[str]:
    if settings is None:
        settings = get_agenda_settings()

    allowed_days = settings.get("dias_semana")
    if allowed_days is None:
        allowed_days = [0, 1, 2, 3, 4, 5]
    if day.weekday() not in allowed_days:
        return []

    local_tz = _local_timezone()
    now_local = (now or datetime.now(timezone.utc)).astimezone(local_tz)

    try:
        hab_parts = str(settings.get("hora_abertura") or "08:00").split(":")
        start_minute = int(hab_parts[0]) * 60 + int(hab_parts[1])
    except Exception:
        start_minute = 8 * 60

    try:
        hfe_parts = str(settings.get("hora_fechamento") or "18:00").split(":")
        end_minute = int(hfe_parts[0]) * 60 + int(hfe_parts[1])
    except Exception:
        end_minute = 18 * 60

    try:
        dur_min = int(settings.get("duracao_minutos") or 60)
        if dur_min < 15 or dur_min > 240:
            dur_min = 60
    except Exception:
        dur_min = 60

    almoco_ini_min = None
    almoco_fim_min = None
    alm_ini = settings.get("almoco_inicio")
    alm_fim = settings.get("almoco_fim")
    if alm_ini and alm_fim:
        try:
            ai_parts = str(alm_ini).split(":")
            af_parts = str(alm_fim).split(":")
            almoco_ini_min = int(ai_parts[0]) * 60 + int(ai_parts[1])
            almoco_fim_min = int(af_parts[0]) * 60 + int(af_parts[1])
        except Exception:
            pass

    duration = timedelta(minutes=dur_min)
    booked_utc = [start.astimezone(timezone.utc) for start in booked_starts]
    slots = []

    curr_minute = start_minute
    while curr_minute + dur_min <= end_minute:
        slot_end_minute = curr_minute + dur_min
        if almoco_ini_min is not None and almoco_fim_min is not None:
            if curr_minute < almoco_fim_min and slot_end_minute > almoco_ini_min:
                curr_minute += dur_min
                continue

        slot = datetime.combine(
            day,
            time(curr_minute // 60, curr_minute % 60),
            tzinfo=local_tz,
        )
        slot_utc = slot.astimezone(timezone.utc)
        if slot > now_local:
            if not any(slot_utc < booked + duration and slot_utc + duration > booked for booked in booked_utc):
                slots.append(slot.strftime("%H:%M"))
        curr_minute += dur_min

    return slots


def _booked_starts(session: Session, day: date, tenant_id: Optional[int]) -> list[datetime]:
    start_utc, end_utc = _day_bounds_utc(day)
    query = select(AtendimentoAgendamento.data_hora).where(
        AtendimentoAgendamento.status == "agendado",
        AtendimentoAgendamento.data_hora >= start_utc,
        AtendimentoAgendamento.data_hora < end_utc,
    ).order_by(AtendimentoAgendamento.data_hora)
    if tenant_id is not None:
        query = query.where(AtendimentoAgendamento.empresa_atendimento_id == tenant_id)
    return list(session.exec(query).all())


def _require_enabled(tenant_id: Optional[int] = None) -> None:
    settings = get_agenda_settings(tenant_id=tenant_id)
    if not settings.get("enabled", False):
        raise HTTPException(status_code=409, detail="A agenda está desativada.")


def _tenant_id(request: Request, instance: Optional[str] = None) -> Optional[int]:
    if not atendimento_multiempresa_enabled():
        return None

    role = get_signed_cookie(request, "user_role", "")
    if role == "admin":
        if instance:
            tenant_id = tenant_id_for_instance(instance)
            if tenant_id is not None:
                return tenant_id
        # Admin pode escolher a empresa ativa por header, query param ou cookie
        tenant_header = request.headers.get("X-Tenant-Id")
        if tenant_header and str(tenant_header).isdigit():
            return int(tenant_header)
        tenant_param = request.query_params.get("tenant_id")
        if tenant_param and str(tenant_param).isdigit():
            return int(tenant_param)
        tenant_cookie = get_signed_cookie(request, "atendimento_tenant_id")
        if tenant_cookie and str(tenant_cookie).isdigit():
            return int(tenant_cookie)
        return None

    tenant_id = resolve_context(request).tenant_id
    if instance and tenant_id_for_instance(instance) != tenant_id:
        raise HTTPException(status_code=403, detail="A instância selecionada não pertence à empresa ativa.")
    return tenant_id


def _parse_future_datetime(value: object) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Informe a data e o horário.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data ou horário inválido.") from exc

    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    parsed = parsed.astimezone(timezone.utc)
    if parsed <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Escolha uma data e horário futuros.")
    return parsed


def _serialize_appointment(item: AtendimentoAgendamento) -> dict:
    return {
        "id": item.id,
        "nome_cliente": item.nome_cliente,
        "telefone": item.telefone,
        "titulo": item.titulo,
        "data_hora": item.data_hora.isoformat(),
        "observacao": item.observacao,
        "status": item.status,
        "criado_por": item.criado_por,
    }


def _serialize_message(item: MensagemWhatsAppAgendada) -> dict:
    return {
        "id": item.id,
        "nome_destinatario": item.nome_destinatario,
        "telefone": item.telefone,
        "mensagem": item.mensagem,
        "data_hora": item.data_hora.isoformat(),
        "instancia": item.instancia,
        "status": item.status,
        "criado_por": item.criado_por,
        "enviado_em": item.enviado_em.isoformat() if item.enviado_em else None,
    }


@router.get("")
def get_agenda(request: Request):
    api_whatsapp._require_atendimento_access(request)
    config = api_whatsapp.get_whatsapp_config()
    tenant_id = _tenant_id(request)
    tenant_settings = get_agenda_settings(tenant_id=tenant_id)

    with Session(engine) as session:
        appointments_query = select(AtendimentoAgendamento).order_by(AtendimentoAgendamento.data_hora.desc()).limit(200)
        messages_query = select(MensagemWhatsAppAgendada).order_by(MensagemWhatsAppAgendada.data_hora.desc()).limit(200)
        if tenant_id is not None:
            appointments_query = appointments_query.where(AtendimentoAgendamento.empresa_atendimento_id == tenant_id)
            messages_query = messages_query.where(MensagemWhatsAppAgendada.empresa_atendimento_id == tenant_id)
        appointments = session.exec(appointments_query).all()
        messages = session.exec(messages_query).all()

    return {
        "enabled": bool(tenant_settings.get("enabled", False)),
        "appointments": [_serialize_appointment(item) for item in appointments],
        "messages": [_serialize_message(item) for item in messages],
    }


@router.get("/calendar")
def get_agenda_calendar(request: Request, year: int, month: int):
    api_whatsapp._require_atendimento_access(request)
    if year < 2000 or year > 2100 or month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Mês ou ano inválido.")

    first_day = date(year, month, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    start_utc, _ = _day_bounds_utc(first_day)
    end_utc, _ = _day_bounds_utc(next_month)
    tenant_id = _tenant_id(request)
    query = select(AtendimentoAgendamento).where(
        AtendimentoAgendamento.status == "agendado",
        AtendimentoAgendamento.data_hora >= start_utc,
        AtendimentoAgendamento.data_hora < end_utc,
    ).order_by(AtendimentoAgendamento.data_hora)
    if tenant_id is not None:
        query = query.where(AtendimentoAgendamento.empresa_atendimento_id == tenant_id)

    with Session(engine) as session:
        booked_starts = session.exec(query).all()

    local_tz = _local_timezone()
    appointments_by_day: dict[date, list[AtendimentoAgendamento]] = {}
    for appointment in booked_starts:
        local_day = appointment.data_hora.astimezone(local_tz).date()
        appointments_by_day.setdefault(local_day, []).append(appointment)

    settings = get_agenda_settings(tenant_id=tenant_id)
    now = datetime.now(timezone.utc)
    today = now.astimezone(local_tz).date()
    days = []
    allowed_days = settings.get("dias_semana") or [0, 1, 2, 3, 4, 5]
    for day_number in range((next_month - first_day).days):
        day = first_day + timedelta(days=day_number)
        appointments = appointments_by_day.get(day, [])
        slots = _available_slots(day, [item.data_hora for item in appointments], now, settings)
        days.append({
            "date": day.isoformat(),
            "available": bool(slots),
            "open": day.weekday() in allowed_days,
            "past": day < today,
            "slots": slots,
            "appointments": [
                {
                    "time": item.data_hora.astimezone(local_tz).strftime("%H:%M"),
                    "nome_cliente": item.nome_cliente,
                    "titulo": item.titulo,
                }
                for item in appointments
            ],
        })

    return {
        "year": year,
        "month": month,
        "enabled": bool(settings.get("enabled", False)),
        "days": days,
        "settings": {
            "opening_time": settings.get("hora_abertura", "08:00"),
            "closing_time": settings.get("hora_fechamento", "18:00"),
            "break_start": settings.get("almoco_inicio", "12:00"),
            "break_end": settings.get("almoco_fim", "13:00"),
            "duration_minutes": settings.get("duracao_minutos", 60),
            "allowed_days": allowed_days,
            "estabelecimento_nome": settings.get("estabelecimento_nome", "Barbearia & Salão"),
        },
    }


@router.get("/config")
def get_comercio_config(request: Request, tenant_id: Optional[int] = None):
    api_whatsapp._require_atendimento_access(request)
    role = get_signed_cookie(request, "user_role")
    resolved_tenant = tenant_id if (tenant_id is not None and role == "admin") else _tenant_id(request)
    return get_agenda_settings(tenant_id=resolved_tenant)


@router.post("/config")
def save_comercio_config(request: Request, payload: dict = Body(...)):
    api_whatsapp._require_atendimento_access(request)
    role = get_signed_cookie(request, "user_role")
    tenant_id = None
    if role == "admin":
        raw_tid = payload.get("empresa_atendimento_id") or payload.get("tenant_id") or _tenant_id(request)
        tenant_id = int(raw_tid) if raw_tid is not None else None
    else:
        tenant_id = _tenant_id(request)

    with Session(engine) as session:
        query = select(AtendimentoAgendaConfig)
        if tenant_id is not None:
            query = query.where(AtendimentoAgendaConfig.empresa_atendimento_id == tenant_id)
        else:
            query = query.where(AtendimentoAgendaConfig.empresa_atendimento_id.is_(None))
        item = session.exec(query).first()
        if not item:
            item = AtendimentoAgendaConfig(empresa_atendimento_id=tenant_id)

        if "estabelecimento_nome" in payload:
            item.estabelecimento_nome = str(payload["estabelecimento_nome"]).strip()
        if "mensagem_boas_vindas" in payload:
            item.mensagem_boas_vindas = str(payload["mensagem_boas_vindas"]).strip()
        if "servicos_precos" in payload:
            item.servicos_precos = str(payload["servicos_precos"]).strip()
        if "endereco" in payload:
            item.endereco = str(payload["endereco"]).strip()
        if "horarios_info" in payload:
            item.horarios_info = str(payload["horarios_info"]).strip()
        if "duracao_minutos" in payload:
            try:
                item.duracao_minutos = max(15, min(240, int(payload["duracao_minutos"])))
            except (ValueError, TypeError):
                pass
        if "hora_abertura" in payload:
            item.hora_abertura = str(payload["hora_abertura"]).strip()
        if "hora_fechamento" in payload:
            item.hora_fechamento = str(payload["hora_fechamento"]).strip()
        if "almoco_inicio" in payload:
            item.almoco_inicio = str(payload["almoco_inicio"]).strip()
        if "almoco_fim" in payload:
            item.almoco_fim = str(payload["almoco_fim"]).strip()
        if "dias_semana" in payload and isinstance(payload["dias_semana"], list):
            valid_dias = [int(d) for d in payload["dias_semana"] if 0 <= int(d) <= 6]
            item.dias_semana = json.dumps(valid_dias)
        if "enabled" in payload and isinstance(payload["enabled"], bool):
            item.enabled = payload["enabled"]

        item.atualizado_em = datetime.now(timezone.utc)
        session.add(item)
        session.commit()
        session.refresh(item)

    return {"success": True, "config": get_agenda_settings(tenant_id=tenant_id)}


@router.get("/instances")
def get_agenda_instances(request: Request):
    api_whatsapp._require_atendimento_access(request)
    instances, default_instance = api_whatsapp.get_whatsapp_instances()
    available = [
        item for item in instances
        if api_whatsapp.user_can_access_instance(request, item.get("instanceName"))
    ]
    available_names = {item.get("instanceName") for item in available}
    if default_instance not in available_names:
        default_instance = available[0].get("instanceName") if available else None
    return {
        "instances": available,
        "default_instance": default_instance,
    }


@router.get("/tenants")
def get_agenda_tenants(request: Request):
    api_whatsapp._require_atendimento_access(request)
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT e.id, e.nome, e.status, COALESCE(c.enabled, FALSE) AS agenda_enabled
            FROM empresas_atendimento e
            LEFT JOIN atendimento_agenda_config c ON c.empresa_atendimento_id = e.id
            ORDER BY e.nome
        """)).all()
        return [
            {
                "id": int(r[0]),
                "nome": str(r[1]),
                "status": str(r[2] or "inativa"),
                "enabled": bool(r[3]),
            }
            for r in rows
        ]


@router.post("/enabled")
def set_agenda_enabled(request: Request, payload: dict = Body(...)):
    api_whatsapp._require_atendimento_access(request)
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="Informe se a agenda deve ficar ativada ou desativada.")
    
    role = get_signed_cookie(request, "user_role")
    tenant_id = None
    if role == "admin":
        raw_tid = payload.get("empresa_atendimento_id") or payload.get("tenant_id") or _tenant_id(request)
        tenant_id = int(raw_tid) if raw_tid is not None and str(raw_tid).isdigit() else None
    else:
        tenant_id = _tenant_id(request)

    with Session(engine) as session:
        if tenant_id is not None:
            query = select(AtendimentoAgendaConfig).where(AtendimentoAgendaConfig.empresa_atendimento_id == tenant_id)
            item = session.exec(query).first()
            if not item:
                item = AtendimentoAgendaConfig(empresa_atendimento_id=tenant_id)
            item.enabled = enabled
            item.atualizado_em = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
        else:
            # Se for admin desativando/ativando sem tenant específico, atualiza todos os registros
            query = select(AtendimentoAgendaConfig)
            items = session.exec(query).all()
            for it in items:
                it.enabled = enabled
                it.atualizado_em = datetime.now(timezone.utc)
                session.add(it)
            none_item = [it for it in items if it.empresa_atendimento_id is None]
            if not none_item:
                session.add(AtendimentoAgendaConfig(empresa_atendimento_id=None, enabled=enabled))
            session.commit()

    return {"success": True, "enabled": enabled}


@router.post("/appointments")
def create_appointment(request: Request, payload: dict = Body(...)):
    api_whatsapp._require_atendimento_access(request)
    tenant_id = _tenant_id(request)
    _require_enabled(tenant_id=tenant_id)

    name = str(payload.get("nome_cliente") or "").strip()
    phone = re.sub(r"\D", "", str(payload.get("telefone") or ""))
    title = str(payload.get("titulo") or "").strip()
    notes = str(payload.get("observacao") or "").strip() or None
    if not name or len(name) > 180:
        raise HTTPException(status_code=400, detail="Informe o nome do cliente (até 180 caracteres).")
    if len(phone) < 8 or len(phone) > 32:
        raise HTTPException(status_code=400, detail="Informe um telefone válido.")
    if not title or len(title) > 180:
        raise HTTPException(status_code=400, detail="Informe o motivo do atendimento (até 180 caracteres).")
    if notes and len(notes) > 2000:
        raise HTTPException(status_code=400, detail="A observação deve ter no máximo 2.000 caracteres.")

    scheduled_at = _parse_future_datetime(payload.get("data_hora"))
    settings = get_agenda_settings(tenant_id=tenant_id)
    with Session(engine) as session:
        local_slot = scheduled_at.astimezone(_local_timezone())
        available_slots = _available_slots(
            local_slot.date(),
            _booked_starts(session, local_slot.date(), tenant_id),
            settings=settings,
        )
        if local_slot.strftime("%H:%M") not in available_slots:
            raise HTTPException(status_code=409, detail="Esse horário não está mais disponível. Atualize o calendário e escolha outro horário.")
        item = AtendimentoAgendamento(
            nome_cliente=name,
            telefone=phone,
            titulo=title,
            data_hora=scheduled_at,
            observacao=notes,
            criado_por=get_signed_cookie(request, "user_name", "Desconhecido"),
            empresa_atendimento_id=tenant_id,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
    return {"success": True, "appointment": _serialize_appointment(item)}


@router.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: int, request: Request):
    api_whatsapp._require_atendimento_access(request)
    tenant_id = _tenant_id(request)
    with Session(engine) as session:
        item = session.get(AtendimentoAgendamento, appointment_id)
        if not item or (tenant_id is not None and item.empresa_atendimento_id != tenant_id):
            raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
        if item.status != "agendado":
            raise HTTPException(status_code=409, detail="Este agendamento não está mais ativo.")
        item.status = "cancelado"
        session.add(item)
        session.commit()
    return {"success": True}


@router.post("/messages")
def create_scheduled_message(request: Request, payload: dict = Body(...)):
    api_whatsapp._require_atendimento_access(request)
    _require_enabled()

    name = str(payload.get("nome_destinatario") or "").strip()
    phone = re.sub(r"\D", "", str(payload.get("telefone") or ""))
    message = str(payload.get("mensagem") or "").strip()
    requested_instance = str(payload.get("instancia") or "").strip() or None
    instance = api_whatsapp.resolve_configured_instance(requested_instance)
    if not instance:
        raise HTTPException(status_code=503, detail="Nenhuma instância do WhatsApp está configurada.")
    if not api_whatsapp.user_can_access_instance(request, instance):
        raise HTTPException(status_code=403, detail="Você não tem acesso à instância selecionada.")
    if not name or len(name) > 180:
        raise HTTPException(status_code=400, detail="Informe o nome do destinatário (até 180 caracteres).")
    if len(phone) < 8 or len(phone) > 32:
        raise HTTPException(status_code=400, detail="Informe um telefone válido.")
    if not message or len(message) > 4000:
        raise HTTPException(status_code=400, detail="A mensagem deve ter entre 1 e 4.000 caracteres.")

    item = MensagemWhatsAppAgendada(
        nome_destinatario=name,
        telefone=phone,
        mensagem=message,
        data_hora=_parse_future_datetime(payload.get("data_hora")),
        instancia=instance,
        criado_por=get_signed_cookie(request, "user_name", "Desconhecido"),
        empresa_atendimento_id=_tenant_id(request, instance),
    )
    with Session(engine) as session:
        session.add(item)
        session.commit()
        session.refresh(item)
    return {"success": True, "message": _serialize_message(item)}


@router.post("/messages/{message_id}/cancel")
def cancel_scheduled_message(message_id: int, request: Request):
    api_whatsapp._require_atendimento_access(request)
    tenant_id = _tenant_id(request)
    with Session(engine) as session:
        item = session.get(MensagemWhatsAppAgendada, message_id)
        if not item or (tenant_id is not None and item.empresa_atendimento_id != tenant_id):
            raise HTTPException(status_code=404, detail="Mensagem agendada não encontrada.")
        if item.status != "pendente":
            raise HTTPException(status_code=409, detail="Somente mensagens pendentes podem ser canceladas.")
        item.status = "cancelada"
        session.add(item)
        session.commit()
    return {"success": True}


def process_due_messages() -> None:
    """Envia mensagens vencidas enquanto a agenda estiver ativada."""
    config = api_whatsapp.get_whatsapp_config()
    if config.get(SETTING_KEY) is not True:
        return

    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as session:
            due_messages = session.exec(
                select(MensagemWhatsAppAgendada)
                .where(
                    MensagemWhatsAppAgendada.status == "pendente",
                    MensagemWhatsAppAgendada.data_hora <= now,
                )
                .order_by(MensagemWhatsAppAgendada.data_hora)
                .limit(10)
                .with_for_update(skip_locked=True)
            ).all()
            for item in due_messages:
                item.status = "enviando"
                session.add(item)
            claimed = [
                (item.id, item.telefone, item.mensagem, item.instancia)
                for item in due_messages
            ]
            session.commit()
    except Exception as exc:
        print(f"[AGENDA] Não foi possível consultar mensagens vencidas: {exc}")
        return

    for message_id, phone, message, instance in claimed:
        if api_whatsapp.get_whatsapp_config().get(SETTING_KEY) is not True:
            with Session(engine) as session:
                item = session.get(MensagemWhatsAppAgendada, message_id)
                if item and item.status == "enviando":
                    item.status = "pendente"
                    session.add(item)
                    session.commit()
            return

        try:
            sent = api_whatsapp.send_whatsapp_text(phone, message, instance)
            error = None
        except Exception as exc:
            sent = False
            error = exc
        with Session(engine) as session:
            item = session.get(MensagemWhatsAppAgendada, message_id)
            if not item or item.status != "enviando":
                continue
            item.status = "enviada" if sent else "falhou"
            item.enviado_em = datetime.now(timezone.utc) if sent else None
            session.add(item)
            session.commit()
        if not sent:
            print(f"[AGENDA] Falha ao enviar mensagem agendada #{message_id}: {error or 'API do WhatsApp recusou o envio.'}")


def proximos_horarios_formatados(dias_desejados: int = 3, tenant_id: Optional[int] = None) -> str:
    settings = get_agenda_settings(tenant_id=tenant_id)
    local_tz = _local_timezone()
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(local_tz)
    hoje = now_local.date()

    dias_encontrados = []
    nomes_semana = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

    with Session(engine) as session:
        for offset in range(0, 10):
            dia = hoje + timedelta(days=offset)
            booked = _booked_starts(session, dia, tenant_id)
            slots = _available_slots(dia, booked, now_utc, settings)
            if slots:
                if dia == hoje:
                    label = f"Hoje ({dia.strftime('%d/%m')})"
                elif dia == hoje + timedelta(days=1):
                    label = f"Amanhã ({dia.strftime('%d/%m')})"
                else:
                    label = f"{nomes_semana[dia.weekday()]} ({dia.strftime('%d/%m')})"
                slots_str = ", ".join(slots[:6])
                if len(slots) > 6:
                    slots_str += f" e mais {len(slots) - 6} horários"
                dias_encontrados.append(f"📅 *{label}:* {slots_str}")
                if len(dias_encontrados) >= dias_desejados:
                    break

    if not dias_encontrados:
        return "Nenhum horário disponível nos próximos dias. Por favor, fale com a nossa equipe digitando *5*!"
    return "\n".join(dias_encontrados)


def agendar_horario_bot(
    nome_cliente: str,
    telefone: str,
    data_str: str,
    hora_str: str,
    servico: str,
    tenant_id: Optional[int] = None,
) -> tuple[bool, str, Optional[datetime]]:
    settings = get_agenda_settings(tenant_id=tenant_id)
    local_tz = _local_timezone()
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(local_tz)

    clean_phone = re.sub(r"\D", "", telefone)
    clean_servico = str(servico or "Atendimento").strip()

    data_limpa = data_str.strip().replace("-", "/")
    parts = data_limpa.split("/")
    try:
        dia_num = int(parts[0])
        mes_num = int(parts[1])
        ano_num = int(parts[2]) if len(parts) > 2 else now_local.year
        if len(parts) <= 2 and (mes_num < now_local.month or (mes_num == now_local.month and dia_num < now_local.day)):
            ano_num += 1
        data_agendamento = date(ano_num, mes_num, dia_num)
    except Exception:
        return False, "Data inválida. Use o formato DD/MM (ex.: 20/11)", None

    hora_str = hora_str.strip()
    try:
        h_parts = hora_str.split(":")
        hora_num = int(h_parts[0])
        min_num = int(h_parts[1]) if len(h_parts) > 1 else 0
        horario = time(hora_num, min_num)
    except Exception:
        return False, "Horário inválido. Use o formato HH:MM (ex.: 14:00)", None

    dt_local = datetime.combine(data_agendamento, horario, tzinfo=local_tz)
    dt_utc = dt_local.astimezone(timezone.utc)

    if dt_utc <= now_utc:
        return False, "Esse horário já passou. Por favor, escolha uma data e horário futuros.", None

    with Session(engine) as session:
        booked = _booked_starts(session, data_agendamento, tenant_id)
        slots = _available_slots(data_agendamento, booked, now_utc, settings)
        hora_fmt = horario.strftime("%H:%M")
        if hora_fmt not in slots:
            return False, f"O horário {hora_fmt} do dia {data_agendamento.strftime('%d/%m')} não está disponível.", None

        agendamento = AtendimentoAgendamento(
            nome_cliente=nome_cliente,
            telefone=clean_phone,
            titulo=clean_servico[:180],
            data_hora=dt_utc,
            observacao="Agendado automaticamente pelo Robô WhatsApp",
            criado_por="Robô WhatsApp",
            empresa_atendimento_id=tenant_id,
        )
        session.add(agendamento)
        session.commit()
        session.refresh(agendamento)
        return True, "Agendamento realizado com sucesso!", dt_local


def consultar_agendamentos_cliente(
    telefone: str,
    tenant_id: Optional[int] = None,
) -> list[dict]:
    clean_phone = re.sub(r"\D", "", telefone)
    last_digits = clean_phone[-8:] if len(clean_phone) >= 8 else clean_phone
    local_tz = _local_timezone()
    now_utc = datetime.now(timezone.utc)

    with Session(engine) as session:
        query = select(AtendimentoAgendamento).where(
            AtendimentoAgendamento.status == "agendado",
            AtendimentoAgendamento.data_hora >= now_utc,
        ).order_by(AtendimentoAgendamento.data_hora)
        if tenant_id is not None:
            query = query.where(AtendimentoAgendamento.empresa_atendimento_id == tenant_id)

        items = session.exec(query).all()
        result = []
        for it in items:
            it_phone = re.sub(r"\D", "", it.telefone or "")
            if it_phone.endswith(last_digits) or last_digits.endswith(it_phone):
                local_dt = it.data_hora.astimezone(local_tz)
                result.append({
                    "id": it.id,
                    "nome_cliente": it.nome_cliente,
                    "titulo": it.titulo,
                    "data": local_dt.strftime("%d/%m/%Y"),
                    "hora": local_dt.strftime("%H:%M"),
                })
        return result

