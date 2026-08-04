import os
import json
import time
import socket
import subprocess
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select, func
from models import Impressora, Impressao, StatusMaquina
from database import engine
from auth_utils import require_equipamentos
from notifications import send_alert
from websocket_manager import manager

router = APIRouter(prefix="/api/impressoras", tags=["Printers"])

# Arquivo de aliases de máquinas
ALIASES_FILE = "public_html/maquinas_aliases.json"

def normalize_name(name: str) -> str:
    return name.strip().upper()

def load_json_file(path: str) -> dict:
    """
    Carrega um arquivo JSON de forma robusta:
    - 3 tentativas com 50 ms de intervalo (tolera escrita simultânea pelo PowerShell)
    - Remove BOM UTF-8 se presente
    - Retorna {} em caso de falha
    """
    if not os.path.exists(path):
        return {}

    for attempt in range(3):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig remove BOM automaticamente
                content = f.read().strip()
            if not content:
                raise ValueError("Arquivo vazio")
            return json.loads(content)
        except Exception as e:
            if attempt < 2:
                time.sleep(0.05)  # 50 ms entre tentativas
            else:
                print(f"[load_json_file] Falha após 3 tentativas em '{path}': {e}")
    return {}

@router.get("/get_machines")
def get_machines():
    """Retorna lista de máquinas com status e dispara alertas Telegram se alguma ficar offline."""
    import asyncio
    with Session(engine) as session:
        # Busca estatísticas reais do banco (impresseções)
        # Mesma query do PHP
        results = session.exec(
            select(
                Impressao.maquina,
                func.max(Impressao.usuario).label("usuario"),
                func.max(Impressao.data_hora).label("ultima_acao"),
                func.count(Impressao.id).label("total_impressoes"),
                func.max(Impressao.ip_maquina).label("ip_maquina")
            )
            .where(Impressao.maquina != "")
            .group_by(Impressao.maquina)
            .order_by(func.max(Impressao.data_hora).desc())
        ).all()

        print_map = {}
        for row in results:
            name = row[0]
            print_map[normalize_name(name)] = {
                "nome_maquina": name,
                "usuario": row[1] or "Sem registro",
                "ultima_acao": row[2].strftime("%Y-%m-%d %H:%M:%S") if row[2] else None,
                "total_impressoes": row[3],
                "ip": row[4] or "-"
            }

        # Consulta DB StatusMaquina (Single Source of Truth)
        agora = datetime.now()
        aliases = load_json_file(ALIASES_FILE)
        
        all_stats = session.exec(select(StatusMaquina)).all()
        
        # Deduplicar por nome da máquina (mantendo apenas o registro mais recente)
        latest_stats = {}
        for s in all_stats:
            name = s.nome
            if not name or name in ["OFFLINE", "SEM-NOME"]: continue
            key = normalize_name(name)
            if key not in latest_stats or s.timestamp > latest_stats[key].timestamp:
                latest_stats[key] = s

        machines_list = []
        known_names = set()

        for key, s in latest_stats.items():
            name = s.nome
            p_info = print_map.get(key, {})
            active_user = p_info.get("usuario", s.windows_user)
            if name in aliases: active_user = aliases[name]

            # Considera Online se o último contato foi em menos de 5 minutos (300 segundos)
            calc_status = "Online" if (agora - s.timestamp).total_seconds() < 300 else "Offline"

            machines_list.append({
                "nome_maquina": name,
                "usuario": active_user,
                "status": calc_status,
                "ultima_acao": p_info.get("ultima_acao", s.timestamp.strftime("%Y-%m-%d %H:%M:%S")),
                "total_impressoes": p_info.get("total_impressoes", 0),
                "ip": s.ip,
                "fonte_status": "db",
                "has_alias": name in aliases
            })
            known_names.add(key)

        # ── Detectar máquinas Offline e enviar alerta se necessário ──
        offline_machines = [m for m in machines_list if m.get("status") in ["Offline", "OFFLINE", "Desconhecido"]]
        try:
            # Carrega registro de alertas já enviados para evitar spam
            alerta_file = "status_alertas_offline.json"
            alertas_enviados = {}
            if os.path.exists(alerta_file):
                with open(alerta_file) as f:
                    alertas_enviados = json.load(f)

            from datetime import timedelta
            agora_ts = datetime.now()
            alertas_mudaram = False
            for m in offline_machines:
                nm = m["nome_maquina"]
                ultimo = alertas_enviados.get(nm)
                # Envia alerta apenas se nunca enviou OU se passou mais de 30 min
                if not ultimo or (agora_ts - datetime.fromisoformat(ultimo)).seconds > 1800:
                    msg = (
                        f"⚠️ <b>MÁQUINA OFFLINE DETECTADA!</b>\n\n"
                        f"🖥️ Máquina: <b>{nm}</b>\n"
                        f"🌐 IP: {m.get('ip', 'desconhecido')}\n"
                        f"👤 Último usuário: {m.get('usuario', '?')}\n"
                        f"🕐 Detectado às: {agora_ts.strftime('%H:%M:%S')}"
                    )
                    send_alert(msg)
                    asyncio.run(manager.broadcast({"event": "machine_offline", "machine": nm}))
                    alertas_enviados[nm] = agora_ts.isoformat()
                    alertas_mudaram = True

            if alertas_mudaram:
                with open(alerta_file, "w") as f:
                    json.dump(alertas_enviados, f)
        except Exception as e:
            print(f"[api_printers] Erro ao checar offline: {e}")

        return {
            "success": True,
            "machines": machines_list,
            "total": len(machines_list)
        }

@router.get("/scan_ip")
async def scan_ip(ip: str):
    # Ping simples (compatível com Windows)
    try:
        res = subprocess.run(["ping", "-n", "1", "-w", "500", ip], capture_output=True, text=True)
        is_online = (res.returncode == 0)
    except:
        is_online = False

    device_name = "Desconhecido"
    if is_online:
        try:
            device_name = socket.gethostbyaddr(ip)[0]
        except:
            device_name = "Dispositivo IP: " + ip
    is_printer = False

    # Se estiver online, tenta pegar o nome via SNMP (Simulado por enquanto, ou use pysnmp)
    if is_online:
        # Futuro: Implementar SNMP real aqui com pysnmp
        pass

    return {
        "success": True,
        "ip": ip,
        "online": is_online,
        "is_printer": is_printer,
        "device_name": device_name
    }

@router.post("/add_printer")
async def add_printer(request: Request, _user=Depends(require_equipamentos)):
    data = await request.json()
    nome = data.get("nome", "").strip()
    ip   = data.get("ip", "").strip()
    modelo      = data.get("modelo", "").strip() or None
    localizacao = data.get("localizacao", "").strip() or None

    if not nome or not ip:
        raise HTTPException(status_code=400, detail="Nome e IP são obrigatórios")

    with Session(engine) as session:
        statement = select(Impressora).where(Impressora.ip == ip)
        printer = session.exec(statement).first()

        if printer:
            printer.nome = nome
            if modelo      is not None: printer.modelo      = modelo
            if localizacao is not None: printer.localizacao = localizacao
        else:
            printer = Impressora(
                nome=nome, ip=ip, status="Desconhecido",
                modelo=modelo, localizacao=localizacao
            )
            session.add(printer)

        session.commit()
    return {"success": True}

@router.delete("/delete_printer")
@router.get("/delete_printer")  # mantém compat. com o JS do template
async def delete_printer(id: int, request: Request, _user=Depends(require_equipamentos)):
    with Session(engine) as session:
        printer = session.get(Impressora, id)
        if printer:
            session.delete(printer)
            session.commit()
    return {"success": True}

@router.post("/update_name")
async def update_name(request: Request, _user=Depends(require_equipamentos)):
    data = await request.json()
    printer_id  = data.get("id")
    nome        = data.get("nome", "").strip() or None
    modelo      = data.get("modelo", "").strip() or None
    localizacao = data.get("localizacao", "").strip() or None

    with Session(engine) as session:
        printer = session.get(Impressora, printer_id)
        if printer:
            if nome        is not None: printer.nome        = nome
            if modelo      is not None: printer.modelo      = modelo
            if localizacao is not None: printer.localizacao = localizacao
            session.commit()
    return {"success": True}

@router.get("/get_toner_level")
async def get_toner_level(ip: str):
    # Por enquanto retornando mock, integraremos pysnmp em breve
    return {"success": True, "toner": 85}
