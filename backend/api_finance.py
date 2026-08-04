"""
api_finance.py - Dashboard Financeiro de Custos (ROI)
Calcula custos de impressão por usuário, maquina e período.
"""
import os
import json
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func, col

from models import Impressao, Impressora
from database import engine
from auth_utils import get_signed_cookie

router = APIRouter(prefix="/api/finance", tags=["Finance"])
templates = Jinja2Templates(directory="templates")

# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_prices():
    """Lê preços do config.json do PHP (P&B e Cor)."""
    config_path = "public_html/includes/config.json"
    defaults = {"APP_PRICE_BW": 0.50, "APP_PRICE_COLOR": 1.00, "APP_NAME": "PrintDash"}
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def _period_range(period: str):
    """Retorna (data_inicio, data_fim) com base no período solicitado."""
    today = date.today()
    if period == "today":
        return datetime.combine(today, datetime.min.time()), datetime.now()
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        return datetime.combine(start, datetime.min.time()), datetime.now()
    elif period == "year":
        return datetime(today.year, 1, 1), datetime.now()
    else:  # month (padrão)
        return datetime(today.year, today.month, 1), datetime.now()


# ─── Endpoint: Stats gerais ──────────────────────────────────────────────────

@router.get("/stats")
def get_finance_stats(period: str = Query("month")):
    """Retorna totais financeiros consolidados para o período."""
    cfg = _load_prices()
    price_bw = float(cfg.get("APP_PRICE_BW", 0.50))
    price_color = float(cfg.get("APP_PRICE_COLOR", 1.00))
    start, end = _period_range(period)

    with Session(engine) as session:
        # Totais P&B
        bw_result = session.exec(
            select(func.count(Impressao.id), func.sum(Impressao.paginas))
            .where(Impressao.tipo_impressao.in_(["Preto e Branco", "P&B"]))
            .where(col(Impressao.data_hora) >= start)
            .where(col(Impressao.data_hora) <= end)
        ).first()

        # Totais Colorido
        color_result = session.exec(
            select(func.count(Impressao.id), func.sum(Impressao.paginas))
            .where(Impressao.tipo_impressao.in_(["Colorida", "Colorido"]))
            .where(col(Impressao.data_hora) >= start)
            .where(col(Impressao.data_hora) <= end)
        ).first()

        bw_jobs = bw_result[0] or 0
        bw_pages = bw_result[1] or 0
        color_jobs = color_result[0] or 0
        color_pages = color_result[1] or 0

        digital_result = session.exec(
            select(func.count(Impressao.id), func.sum(Impressao.paginas))
            .where(Impressao.tipo_impressao == "Digital")
            .where(col(Impressao.data_hora) >= start)
            .where(col(Impressao.data_hora) <= end)
        ).first()
        digital_jobs = digital_result[0] or 0
        digital_pages = digital_result[1] or 0

        total_cost = (bw_pages * price_bw) + (color_pages * price_color)
        total_pages = bw_pages + color_pages + digital_pages
        total_jobs = bw_jobs + color_jobs + digital_jobs

        # Custo diário (últimos 30 dias para o gráfico)
        daily = session.exec(
            select(
                func.to_char(Impressao.data_hora, "YYYY-MM-DD").label("day"),
                func.sum(Impressao.valor_total).label("total")
            )
            .where(col(Impressao.data_hora) >= (datetime.now() - timedelta(days=30)))
            .group_by(func.to_char(Impressao.data_hora, "YYYY-MM-DD"))
            .order_by(func.to_char(Impressao.data_hora, "YYYY-MM-DD"))
        ).all()

    daily_labels = [str(d[0]) for d in daily]
    daily_values = [round(float(d[1] or 0), 2) for d in daily]

    return {
        "period": period,
        "bw_jobs": bw_jobs,
        "bw_pages": bw_pages,
        "bw_cost": round(bw_pages * price_bw, 2),
        "color_jobs": color_jobs,
        "color_pages": color_pages,
        "color_cost": round(color_pages * price_color, 2),
        "digital_jobs": digital_jobs,
        "digital_pages": digital_pages,
        "digital_cost": 0.0,
        "total_jobs": total_jobs,
        "total_pages": total_pages,
        "total_cost": round(total_cost, 2),
        "price_bw": price_bw,
        "price_color": price_color,
        "daily_labels": daily_labels,
        "daily_values": daily_values,
    }


# ─── Endpoint: Ranking de usuários por custo ────────────────────────────────

@router.get("/ranking")
def get_ranking(period: str = Query("month"), limit: int = Query(10)):
    """Retorna os top N usuários com maior custo no período."""
    start, end = _period_range(period)

    with Session(engine) as session:
        results = session.exec(
            select(
                Impressao.usuario,
                func.sum(Impressao.paginas).label("paginas"),
                func.sum(Impressao.valor_total).label("custo"),
                func.count(Impressao.id).label("jobs"),
            )
            .where(col(Impressao.data_hora) >= start)
            .where(col(Impressao.data_hora) <= end)
            .group_by(Impressao.usuario)
            .order_by(func.sum(Impressao.valor_total).desc())
            .limit(limit)
        ).all()

    return [
        {
            "usuario": r[0],
            "paginas": r[1] or 0,
            "custo": round(float(r[2] or 0), 2),
            "jobs": r[3] or 0,
        }
        for r in results
    ]


# ─── Endpoint: Ranking por impressora ───────────────────────────────────────

@router.get("/ranking_impressoras")
def get_ranking_impressoras(period: str = Query("month")):
    """Retorna as impressoras com maior custo no período."""
    start, end = _period_range(period)

    with Session(engine) as session:
        results = session.exec(
            select(
                Impressao.maquina,
                func.sum(Impressao.paginas).label("paginas"),
                func.sum(Impressao.valor_total).label("custo"),
            )
            .where(col(Impressao.data_hora) >= start)
            .where(col(Impressao.data_hora) <= end)
            .group_by(Impressao.maquina)
            .order_by(func.sum(Impressao.valor_total).desc())
            .limit(10)
        ).all()

    return [
        {"maquina": r[0], "paginas": r[1] or 0, "custo": round(float(r[2] or 0), 2)}
        for r in results
    ]


# ─── Endpoint: Previsão de suprimentos (Toner) ──────────────────────────────

@router.get("/supply_forecast")
def get_supply_forecast():
    """
    Calcula a previsão de fim de toner para cada impressora cadastrada.
    Usa a média de páginas/dia dos últimos 7 dias e uma capacidade padrão de toner.
    """
    TONER_CAPACITY = 2000  # Páginas por cartucho (padrão genérico)

    with Session(engine) as session:
        impressoras = session.exec(select(Impressora)).all()
        forecasts = []

        for imp in impressoras:
            # Páginas nos últimos 7 dias (usa nome da máquina como chave)
            seven_days_ago = datetime.now() - timedelta(days=7)
            pages_7d = session.exec(
                select(func.sum(Impressao.paginas))
                .where(Impressao.maquina == imp.nome)
                .where(col(Impressao.data_hora) >= seven_days_ago)
            ).first()
            pages_7d = int(pages_7d[0] or 0)

            # Total histórico para estimar % restante
            total_historico = session.exec(
                select(func.sum(Impressao.paginas)).where(Impressao.maquina == imp.nome)
            ).first()
            total_historico = int(total_historico[0] or 0)

            avg_per_day = pages_7d / 7 if pages_7d > 0 else 0
            pages_since_refill = total_historico % TONER_CAPACITY
            pages_remaining = TONER_CAPACITY - pages_since_refill
            pct_remaining = round((pages_remaining / TONER_CAPACITY) * 100, 1)
            days_left = round(pages_remaining / avg_per_day, 1) if avg_per_day > 0 else None

            alert_level = "ok"
            if pct_remaining <= 10:
                alert_level = "critical"
            elif pct_remaining <= 25:
                alert_level = "warning"

            forecasts.append({
                "impressora": imp.nome,
                "ip": imp.ip,
                "id": imp.id,
                "avg_per_day": round(avg_per_day, 1),
                "pct_remaining": pct_remaining,
                "pages_remaining": pages_remaining,
                "days_left": days_left,
                "alert_level": alert_level,
            })

        # Ordena por % restante crescente (mais crítico primeiro)
        forecasts.sort(key=lambda x: x["pct_remaining"])
        return forecasts
