import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Request
from sqlmodel import Session, select

import api_whatsapp
from atendimento_tenant_context import is_enabled as atendimento_multiempresa_enabled
from atendimento_tenant_context import resolve_context, tenant_id_for_instance
from auth_utils import get_signed_cookie
from database import engine
from models import AtendimentoAgendamento, MensagemWhatsAppAgendada

router = APIRouter(prefix="/api/atendimento/agenda", tags=["Agenda do Atendimento"])
SETTING_KEY = "ATENDIMENTO_AGENDAMENTOS_ENABLED"
APPOINTMENT_START_MINUTE = 8 * 60
APPOINTMENT_END_MINUTE = 17 * 60
APPOINTMENT_DURATION_MINUTES = 60
BREAK_START_MINUTE = 12 * 60
BREAK_END_MINUTE = 13 * 60


def _local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    local_tz = _local_timezone()
    start = datetime.combine(day, time.min, tzinfo=local_tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=local_tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _available_slots(day: date, booked_starts: list[datetime], now: Optional[datetime] = None) -> list[str]:
    if day.weekday() > 4:
        return []

    local_tz = _local_timezone()
    now_local = (now or datetime.now(timezone.utc)).astimezone(local_tz)
    duration = timedelta(minutes=APPOINTMENT_DURATION_MINUTES)
    booked_utc = [start.astimezone(timezone.utc) for start in booked_starts]
    slots = []

    for start_minute in range(APPOINTMENT_START_MINUTE, APPOINTMENT_END_MINUTE, APPOINTMENT_DURATION_MINUTES):
        end_minute = start_minute + APPOINTMENT_DURATION_MINUTES
        if start_minute < BREAK_END_MINUTE and end_minute > BREAK_START_MINUTE:
            continue

        slot = datetime.combine(
            day,
            time(start_minute // 60, start_minute % 60),
            tzinfo=local_tz,
        )
        slot_utc = slot.astimezone(timezone.utc)
        if slot <= now_local:
            continue
        if any(slot_utc < booked + duration and slot_utc + duration > booked for booked in booked_utc):
            continue
        slots.append(slot.strftime("%H:%M"))
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


def _require_enabled() -> None:
    if not api_whatsapp.get_whatsapp_config().get(SETTING_KEY, False):
        raise HTTPException(status_code=409, detail="A agenda está desativada.")


def _tenant_id(request: Request, instance: Optional[str] = None) -> Optional[int]:
    if not atendimento_multiempresa_enabled():
        return None

    role = get_signed_cookie(request, "user_role", "")
    if role == "admin":
        if instance:
            tenant_id = tenant_id_for_instance(instance)
            if tenant_id is None:
                raise HTTPException(status_code=400, detail="A instância do WhatsApp não está vinculada a uma empresa.")
            return tenant_id
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

    with Session(engine) as session:
        appointments_query = select(AtendimentoAgendamento).order_by(AtendimentoAgendamento.data_hora.desc()).limit(200)
        messages_query = select(MensagemWhatsAppAgendada).order_by(MensagemWhatsAppAgendada.data_hora.desc()).limit(200)
        if tenant_id is not None:
            appointments_query = appointments_query.where(AtendimentoAgendamento.empresa_atendimento_id == tenant_id)
            messages_query = messages_query.where(MensagemWhatsAppAgendada.empresa_atendimento_id == tenant_id)
        appointments = session.exec(appointments_query).all()
        messages = session.exec(messages_query).all()

    return {
        "enabled": bool(config.get(SETTING_KEY, False)),
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

    now = datetime.now(timezone.utc)
    today = now.astimezone(local_tz).date()
    days = []
    for day_number in range((next_month - first_day).days):
        day = first_day + timedelta(days=day_number)
        appointments = appointments_by_day.get(day, [])
        slots = _available_slots(day, [item.data_hora for item in appointments], now)
        days.append({
            "date": day.isoformat(),
            "available": bool(slots),
            "open": day.weekday() < 5,
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
        "enabled": bool(api_whatsapp.get_whatsapp_config().get(SETTING_KEY, False)),
        "days": days,
        "settings": {
            "opening_time": "08:00",
            "closing_time": "17:00",
            "break_start": "12:00",
            "break_end": "13:00",
            "duration_minutes": APPOINTMENT_DURATION_MINUTES,
        },
    }


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


@router.post("/enabled")
def set_agenda_enabled(request: Request, payload: dict = Body(...)):
    api_whatsapp._require_admin(request)
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="Informe se a agenda deve ficar ativada ou desativada.")
    config = api_whatsapp.get_whatsapp_config()
    config[SETTING_KEY] = enabled
    api_whatsapp.save_whatsapp_config(config)
    return {"success": True, "enabled": enabled}


@router.post("/appointments")
def create_appointment(request: Request, payload: dict = Body(...)):
    api_whatsapp._require_atendimento_access(request)
    _require_enabled()

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
    tenant_id = _tenant_id(request)
    with Session(engine) as session:
        local_slot = scheduled_at.astimezone(_local_timezone())
        available_slots = _available_slots(
            local_slot.date(),
            _booked_starts(session, local_slot.date(), tenant_id),
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
