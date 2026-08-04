import win32print
import win32api
import requests
import json
import time
import socket
import sys

# --- CONFIGURAÇÕES ---
# IP do Servidor PrintDash
import os

API_URL = "http://192.168.1.230:3003/api/v1/agent"  # Endpoint FastAPI
API_KEY = os.environ.get("PRINTDASH_API_KEY", "")


def log_local(msg):
    with open("log_agente.txt", "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    print(msg)

NOME_MAQUINA = socket.gethostname()
# Tenta pegar o IP da rede local
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    IP_MAQUINA = s.getsockname()[0]
    s.close()
except:
    IP_MAQUINA = socket.gethostbyname(NOME_MAQUINA)

def obter_trabalhos_impressao():
    jobs_encontrados = []
    try:
        # Lista todas as impressoras locais e de rede conectadas
        for printer in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS):
            printer_name = printer[2]
            try:
                hPrinter = win32print.OpenPrinter(printer_name)
                # Nível 1: JobId, pDocument, pUserName, pPrinterName, TotalPages
                jobs = win32print.EnumJobs(hPrinter, 0, -1, 1)
                for job in jobs:
                    # Só capturamos se o job estiver sendo processado ou na fila
                    jobs_encontrados.append({
                        "id_job_windows": job['JobId'],
                        "DocumentName": job['pDocument'],
                        "UserName": job['pUserName'],
                        "PrinterName": printer_name,
                        "TotalPages": job['TotalPages'] if job['TotalPages'] > 0 else 1
                    })
                win32print.ClosePrinter(hPrinter)
            except:
                continue
    except Exception as e:
        print(f"Erro ao listar impressoras: {e}")
    return jobs_encontrados

def enviar_dados(tipo, payload_dados):
    payload = {
        "maquina": NOME_MAQUINA,
        "ip": IP_MAQUINA,
        "versao": "2.1-Final",
        "dados": {
            "tipo": tipo,
            **payload_dados
        }
    }
    
    headers = {
        "X-API-KEY": API_KEY,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            log_local(f"Sucesso: {tipo} enviado.")
            return response.json()
        else:
            log_local(f"Erro no Servidor ({response.status_code}): {response.text}")
            return None
    except Exception as e:
        log_local(f"Erro de Conexão: {e}")
        return None

# --- LOOP PRINCIPAL ---
ultimo_heartbeat = 0
# Usamos o ID interno do Windows para não duplicar
jobs_enviados = set()

while True:
    agora = time.time()

    # 1. Heartbeat a cada 60s
    if agora - ultimo_heartbeat > 60:
        enviar_dados("heartbeat", {"windows_user": win32api.GetUserName()})
        ultimo_heartbeat = agora

    # 2. Verificar Impressões
    lista_jobs = obter_trabalhos_impressao()
    
    if lista_jobs:
        novos_jobs = []
        ids_atuais = set()
        
        for job in lista_jobs:
            # Criamos uma chave única com ID do Job + Nome para segurança extra
            chave_job = f"{job['id_job_windows']}_{job['DocumentName']}"
            ids_atuais.add(chave_job)
            
            if chave_job not in jobs_enviados:
                novos_jobs.append(job)
                jobs_enviados.add(chave_job)

        if novos_jobs:
            enviar_dados("impressoes", {"jobs": novos_jobs})
            
        # Limpa do cache IDs que não estão mais na fila (trabalhos concluídos)
        # Isso permite que se o mesmo ID for reutilizado pelo Windows depois, ele seja capturado
        jobs_enviados = {jid for jid in jobs_enviados if jid in ids_atuais}
    else:
        jobs_enviados.clear()

    time.sleep(2)
