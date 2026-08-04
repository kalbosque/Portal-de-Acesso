import os
import sys
import time
import ctypes
import ctypes.util
import json
import socket
import platform
import subprocess
import threading
import requests
import configparser
import ctypes
import struct
import re
from ctypes import wintypes
import ctypes.util
# import psutil # Removido para evitar dependências externas
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

# ============================================================
#   CONFIGURAÇÕES DO AGENTE PRINTDASH v2.3.1
# ============================================================
def carregar_config():
    # Tenta ler config.ini na mesma pasta do executavel
    base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    config_path = os.path.join(base_dir, "config.ini")
    
    # Permite configurar sem recompilar o executável. A variável de ambiente
    # é útil para instalações automatizadas e o config.ini para instalações
    # manuais.
    padrao = os.environ.get("PRINTDASH_SERVER_URL", "http://192.168.1.230:3001")
    if os.path.exists(config_path):
        try:
            config = configparser.ConfigParser()
            config.read(config_path)
            if 'SERVIDOR' in config and 'URL' in config['SERVIDOR']:
                return config['SERVIDOR']['URL'].strip().rstrip('/')
        except Exception:
            pass
    return padrao

SERVER_URL      = carregar_config()  # API FastAPI do servidor
API_ENDPOINT    = f"{SERVER_URL}/api/v1/agent"
API_KEY         = os.environ.get("PRINTDASH_API_KEY", "")
HEARTBEAT_INTERVAL = 60   # segundos
ID_SERVER_PORT  = 5050
POLL_INTERVAL   = 1       # segundo — polling da fila do Spooler (como PaperCut)
EVENT_LOG_INTERVAL = 10   # segundos — verificação periódica do Event Log (método primário)

# Impressoras virtuais — NUNCA registrar custo para elas
VIRTUAL_PRINTERS = [
    'adobe pdf', 'cutepdf', 'microsoft print to pdf',
    'xps document writer', 'onenote', 'webex', 'fax',
    'anydesk', 'remote desktop easy print', 'remote desktop',
    'ts ', 'citrix', 'vmware', '(redirecionada)', 'redirected',
    'send to onenote', 'microsoft xps', 'redirecionada', 'redirected'
]
DIGITAL_PRINTERS = ['microsoft print to pdf', 'adobe pdf', 'cutepdf', 'microsoft xps', 'xps document writer']

def is_virtual_printer(name):
    """Identifica impressoras virtuais e sessões redirecionadas do Windows."""
    normalized = ' '.join((name or '').lower().split())
    return any(value in normalized for value in VIRTUAL_PRINTERS)

def is_digital_printer(name):
    normalized = ' '.join((name or '').lower().split())
    return any(value in normalized for value in DIGITAL_PRINTERS)

# Nomes genéricos que o Windows dá quando não sabe o nome real
GENERIC_DOC_NAMES = {
    "documento de impressão", "documento de impressao",
    "documento de impressæo", "documento de impressæo",
    "documento de impressã£o", "documento de impressã£o",
    "documento de impressÆo", "documento de impressaeo",
    "sem título", "sem titulo", "print document",
    "document", "página de teste", "pagina de teste", ""
}

# ============================================================
#   WIN32 SPOOLER API — Estruturas e Constantes
# ============================================================
# Carrega winspool.drv pelo nome completo — necessário para PyInstaller
try:
    winspool = ctypes.WinDLL('winspool.drv')
except OSError:
    winspool = None

PRINTER_ACCESS_USE    = 0x00000008
PRINTER_ENUM_LOCAL    = 0x00000002
PRINTER_ENUM_CONNECTIONS = 0x00000004

# JOB_STATUS flags
JOB_STATUS_PRINTING   = 0x0010
JOB_STATUS_PRINTED    = 0x0080
JOB_STATUS_COMPLETE   = 0x1000
JOB_STATUS_DELETING   = 0x0004
JOB_STATUS_DELETED    = 0x0100

class SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear",         wintypes.WORD),
        ("wMonth",        wintypes.WORD),
        ("wDayOfWeek",    wintypes.WORD),
        ("wDay",          wintypes.WORD),
        ("wHour",         wintypes.WORD),
        ("wMinute",       wintypes.WORD),
        ("wSecond",       wintypes.WORD),
        ("wMilliseconds", wintypes.WORD),
    ]

class JOB_INFO_2(ctypes.Structure):
    """Estrutura Win32 JOB_INFO_2 — contém pDocument com o nome real!"""
    _fields_ = [
        ("JobId",            wintypes.DWORD),
        ("pPrinterName",     wintypes.LPWSTR),
        ("pMachineName",     wintypes.LPWSTR),
        ("pUserName",        wintypes.LPWSTR),
        ("pDocument",        wintypes.LPWSTR),   # <<< Nome real do documento!
        ("pNotifyName",      wintypes.LPWSTR),
        ("pDatatype",        wintypes.LPWSTR),
        ("pPrintProcessor",  wintypes.LPWSTR),
        ("pParameters",      wintypes.LPWSTR),
        ("pDriverName",      wintypes.LPWSTR),
        ("pDevMode",         ctypes.c_void_p),
        ("pStatus",          wintypes.LPWSTR),
        ("pSecurityDescriptor", ctypes.c_void_p),
        ("Status",           wintypes.DWORD),
        ("Priority",         wintypes.DWORD),
        ("Position",         wintypes.DWORD),
        ("StartTime",        wintypes.DWORD),
        ("UntilTime",        wintypes.DWORD),
        ("TotalPages",       wintypes.DWORD),
        ("Size",             wintypes.DWORD),
        ("Submitted",        SYSTEMTIME),
        ("Time",             wintypes.DWORD),
        ("PagesPrinted",     wintypes.DWORD),
    ]

# ============================================================
#   CAPTURA DE JANELA ATIVA (Fallback de nome)
# ============================================================
user32 = ctypes.windll.user32

def get_active_window_title():
    """Captura o título da janela ativa para fallback de nome."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd: return None
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value or None
    except:
        return None

def clean_doc_name(doc):
    """Remove prefixos de aplicativo e retorna o nome limpo do documento."""
    if not doc:
        return None
    prefixes = [
        "Microsoft Word - ", "Microsoft Excel - ", "Microsoft PowerPoint - ",
        "Google Chrome - ", "Mozilla Firefox - ", "Adobe Acrobat - ",
        "Adobe Reader - ", "Foxit Reader - "
    ]
    for p in prefixes:
        if doc.startswith(p):
            doc = doc[len(p):]
    return doc.strip() or None

# ============================================================
#   SERVIDOR DE IDENTIFICAÇÃO LOCAL (porta 5050)
# ============================================================
class IdentificationHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/whoami':
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            hostname = socket.gethostname()
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except:
                local_ip = "127.0.0.1"
            self.wfile.write(json.dumps({
                "hostname": hostname,
                "ip": local_ip,
                "agent_version": "2.4.2"
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return  # Silencioso

def run_id_server():
    server = HTTPServer(('127.0.0.1', ID_SERVER_PORT), IdentificationHandler)
    server.serve_forever()

# ============================================================
#   AGENTE PRINCIPAL
# ============================================================
class PrintAgent:
    def __init__(self):
        self.hostname      = socket.gethostname()
        self.local_ip      = self.get_local_ip()
        self.current_user  = os.getlogin()
        self.os_info       = f"{platform.system()} {platform.release()}"
        self.version       = "2.4.3"  # Correção do processamento do Event Log
        self.base_dir      = os.path.dirname(os.path.abspath(
                                sys.executable if getattr(sys, 'frozen', False) else __file__))
        self.log_file      = os.path.join(self.base_dir, "agent.log")
        self.printers_found = [] # Armazena as impressoras que realmente estamos monitorando

        # Controle de deduplicação: guarda (printer, jobId) já registrados
        self.seen_jobs     = set()
        self.seen_lock     = threading.Lock()
        
        # Fallback Event Log: timestamp do último evento processado
        self.last_event_time = datetime.now() - timedelta(minutes=5)

    # ----------------------------------------------------------
    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            # if ip.startswith("172."):
            #     # Fallback para detectar IP 192.168 em ambientes de teste
            #     pass 
            return ip
        except:
            return "127.0.0.1"

    def log(self, message):
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        entry = f"{timestamp} | {message}"
        print(entry)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except:
            pass

    def is_duplicate_job(self, printer, job_id, doc_name, user, pages):
        """Verifica se o job já foi registrado nos últimos minutos."""
        clean_doc = (doc_name or "").strip().lower()
        clean_user = (user or "").strip().lower()
        
        # Chave 1: Por ID do Job
        key_id = f"ID:{printer}:{job_id}"
        # Chave 2: Por Conteúdo (Sem considerar a impressora, pois o nome pode mudar entre Spooler/EventLog)
        key_content = f"CONTENT:{printer}:{clean_user}:{clean_doc}:{pages}"
        
        now = time.time()
        
        with self.seen_lock:
            # Converte seen_jobs para dict se for um set (para compatibilidade caso já inicializado)
            if isinstance(self.seen_jobs, set):
                self.seen_jobs = {}
                
            # O ID do spooler/evento vale por 5 minutos. O conteúdo tem uma
            # janela curta para não bloquear duas impressões iguais legítimas.
            keys_to_delete = [
                k for k, v in self.seen_jobs.items()
                if now - v > (15 if k.startswith('CONTENT:') else 300)
            ]
            for k in keys_to_delete:
                del self.seen_jobs[k]

            if key_id in self.seen_jobs or key_content in self.seen_jobs:
                self.log(f"  [DEDUP] Ignorando duplicata: {key_content}")
                return True
            
            self.seen_jobs[key_id] = now
            self.seen_jobs[key_content] = now
            self.log(f"  [DEDUP] Novo job registrado: {key_content}")
            
            return False
    def send_to_server(self, data):
        try:
            payload = {
                "maquina": self.hostname,
                "ip":      self.local_ip,
                "versao":  self.version,
                "dados":   data
            }
            headers  = {'X-API-KEY': API_KEY}
            response = requests.post(API_ENDPOINT, json=payload,
                                     headers=headers, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                if data.get('tipo') == 'impressoes':
                    self.log(f"  -> Resposta do Servidor: {json.dumps(res_json)}")
                if data.get('tipo') == 'heartbeat':
                    self.process_server_response(res_json)
                return res_json
        except Exception as e:
            self.log(f"  -> Erro ao enviar dados: {e}")
        return None

    def process_server_response(self, res):
        latest = res.get('latest_version')
        if latest and latest > self.version:
            self.log(f"Nova versão: {latest}. Iniciando Auto-Update...")
            threading.Thread(target=self.perform_update, daemon=True).start()
        for cmd in res.get('commands', []):
            if cmd.get('action') == 'install_printer':
                self.install_printer(cmd)

    def perform_update(self):
        """Baixa nova versão do agente e a aplica por bat script."""
        try:
            url      = f"{SERVER_URL}/api/agent/download_latest"  # Endpoint FastAPI
            temp_exe = os.path.join(self.base_dir, "agent_new.exe")
            r = requests.get(url, headers={'X-API-KEY': API_KEY}, stream=True, timeout=30)
            if r.status_code != 200:
                self.log(f"Auto-update: servidor retornou {r.status_code}, abortando.")
                return
            with open(temp_exe, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            bat = (f'@echo off\ntimeout /t 2 /nobreak > nul\n'
                   f'move /y "{temp_exe}" "{sys.executable}"\n'
                   f'start "" "{sys.executable}"\ndel "%~f0"')
            bat_path = os.path.join(self.base_dir, "update.bat")
            with open(bat_path, "w") as f:
                f.write(bat)
            subprocess.Popen(["cmd.exe", "/c", bat_path], shell=True)
            os._exit(0)
        except Exception as e:
            self.log(f"Erro no auto-update: {e}")

    def install_printer(self, cmd):
        name, path = cmd.get('name'), cmd.get('path')
        try:
            subprocess.run(
                f'powershell.exe -Command "Add-Printer -Name \'{name}\' -ConnectionName \'{path}\'"',
                shell=True, check=True)
            self.log(f"Impressora {name} instalada via Deploy.")
        except Exception as e:
            self.log(f"Erro no deploy de impressora: {e}")

    # ----------------------------------------------------------
    #   NÚCLEO: Listar impressoras físicas via Spooler API
    # ----------------------------------------------------------
    def get_physical_printers(self):
        """Retorna lista de nomes de impressoras físicas instaladas via PowerShell."""
        printers = []
        try:
            # Força o uso de UTF-8 e ignora erros de saída
            ps_cmd = (
                'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "'
                '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
                'Get-Printer | Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"'
            )
            result = subprocess.run(ps_cmd, capture_output=True, text=True, shell=True, timeout=15)
            
            if result.stdout and result.stdout.strip():
                try:
                    raw = json.loads(result.stdout.strip())
                    names = raw if isinstance(raw, list) else [raw]
                    for name in names:
                        if name:
                            # Limpeza de caracteres nulos ou espaços extras
                            name_clean = name.strip()
                            if not is_virtual_printer(name_clean) or is_digital_printer(name_clean):
                                printers.append(name_clean)
                except json.JSONDecodeError:
                    # Fallback: Se o JSON falhar, tenta ler linha por linha
                    for line in result.stdout.splitlines():
                        line = line.strip().strip('"')
                        if line and (not is_virtual_printer(line) or is_digital_printer(line)):
                            printers.append(line)

        except Exception as e:
            self.log(f"PowerShell Get-Printer falhou ({e}), tentando Win32 API...")
            printers = self._get_physical_printers_win32()
        
        return list(set(printers)) # Remove duplicatas

    def _get_physical_printers_win32(self):
        """Método secundário via Win32 API direta."""
        if winspool is None:
            return []
        printers = []
        try:
            flags  = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
            level  = 2
            needed = wintypes.DWORD(0)
            count  = wintypes.DWORD(0)
            winspool.EnumPrintersW(flags, None, level, None, 0,
                                   ctypes.byref(needed), ctypes.byref(count))
            if needed.value == 0:
                return printers
            buf = ctypes.create_string_buffer(needed.value)
            winspool.EnumPrintersW(flags, None, level, buf, needed.value,
                                   ctypes.byref(needed), ctypes.byref(count))
            ptr_size = ctypes.sizeof(ctypes.c_void_p)
            struct_size = 9 * ptr_size + 8 * ctypes.sizeof(wintypes.DWORD)
            for i in range(count.value):
                offset = i * struct_size
                ptr_val = ctypes.c_void_p.from_buffer_copy(
                    buf[offset + ptr_size: offset + ptr_size * 2])
                if ptr_val.value:
                    name = ctypes.wstring_at(ptr_val.value)
                    if name and (not is_virtual_printer(name) or is_digital_printer(name)):
                        printers.append(name)
        except Exception as e:
            self.log(f"Win32 EnumPrintersW falhou: {e}")
        return printers

    # ----------------------------------------------------------
    #   NÚCLEO: Ler fila de jobs de uma impressora via EnumJobs
    # ----------------------------------------------------------
    def get_jobs_for_printer(self, printer_name):
        """
        Usa OpenPrinter + EnumJobs (Level 2) para ler a fila ao vivo.
        Retorna lista de dicts com os dados do job.
        """
        if winspool is None:
            return []
        jobs = []
        handle = wintypes.HANDLE()
        try:
            ok = winspool.OpenPrinterW(printer_name, ctypes.byref(handle), None)
            if not ok or not handle.value:
                return jobs

            needed = wintypes.DWORD(0)
            returned = wintypes.DWORD(0)
            # Primeira chamada para descobrir o tamanho
            winspool.EnumJobsW(handle, 0, 1000, 2, None, 0,
                               ctypes.byref(needed), ctypes.byref(returned))

            if needed.value == 0:
                return jobs

            buf = ctypes.create_string_buffer(needed.value)
            ok2 = winspool.EnumJobsW(handle, 0, 1000, 2, buf, needed.value,
                                     ctypes.byref(needed), ctypes.byref(returned))
            if not ok2:
                return jobs

            count = returned.value
            job_size = ctypes.sizeof(JOB_INFO_2)

            for i in range(count):
                offset = i * job_size
                job = JOB_INFO_2.from_buffer_copy(buf[offset: offset + job_size])

                # Só registra quando o job já foi impresso / está sendo impresso
                # Ignora jobs ainda enfileirados sem nenhuma página processada
                status = job.Status
                is_done = (
                    status & JOB_STATUS_PRINTED or
                    status & JOB_STATUS_COMPLETE or
                    status & JOB_STATUS_PRINTING or
                    job.TotalPages > 0
                )
                if not is_done:
                    continue

                doc_name  = job.pDocument  or ""
                user_name = job.pUserName  or self.current_user
                pages     = job.TotalPages or 1

                # Limpa prefixos de aplicativo
                doc_clean = clean_doc_name(doc_name)
                raw_title = doc_name

                # Se ainda for genérico, tenta a janela ativa
                if not doc_clean or doc_clean.lower() in GENERIC_DOC_NAMES:
                    wt = get_active_window_title()
                    if wt:
                        raw_title = wt
                        doc_clean = clean_doc_name(wt) or doc_clean or "Documento Capturado"
                    else:
                        doc_clean = doc_clean or "Documento Capturado"

                jobs.append({
                    "job_id":       job.JobId,
                    "printer_name": printer_name,
                    "DocumentName": doc_clean,
                    "UserName":     user_name,
                    "PrinterName":  printer_name,
                    "TotalPages":   pages,
                    "RawTitle":     raw_title
                })
        except Exception as e:
            pass
        finally:
            try:
                if handle.value:
                    winspool.ClosePrinter(handle)
            except:
                pass
        return jobs

    # ----------------------------------------------------------
    #   MONITOR PRINCIPAL: Polling via Win32 Spooler API
    # ----------------------------------------------------------
    def monitor_spooler(self):
        """Thread 1: Polling da fila Win32 (captura jobs ainda na fila — rápido)."""
        self.log(f"[v{self.version}] Monitor Spooler iniciado — Modo: Win32 EnumJobs.")
        printers_cache_time = 0
        cached_printers = []

        while True:
            try:
                # Atualiza a lista de impressoras a cada 5 minutos
                now = time.time()
                if now - printers_cache_time > 300:
                    new_list = self.get_physical_printers()
                    if set(new_list) != set(self.printers_found):
                        self.printers_found = new_list
                        self.log(f"Monitorando {len(self.printers_found)} impressoras: {', '.join(self.printers_found)}")
                    printers_cache_time = now

                new_jobs = []

                for printer in self.printers_found:
                    try:
                        jobs = self.get_jobs_for_printer(printer)
                        for job in jobs:
                            if self.is_duplicate_job(printer, job["job_id"], job["DocumentName"], job["UserName"], job["TotalPages"]):
                                continue

                            new_jobs.append({
                                "DocumentName": job["DocumentName"],
                                "UserName":     job["UserName"],
                                "PrinterName":  job["PrinterName"],
                                "TotalPages":   job["TotalPages"],
                                "AppProcess":   job.get("RawTitle"),
                                "Digital":      is_digital_printer(job["PrinterName"])
                            })
                    except Exception as e:
                        # Log discreto para não poluir
                        pass 

                if new_jobs:
                    self.send_to_server({"tipo": "impressoes", "jobs": new_jobs})

            except Exception as e:
                self.log(f"Erro no monitor Spooler: {e}")

            time.sleep(POLL_INTERVAL)

    def monitor_event_log(self):
        """Thread 2: Leitura periódica do Event Log (método primário e confiável).
        EventID 307 é gravado SEMPRE que uma impressão é concluída, independente
        de quanto tempo o job ficou na fila. Esta thread é a responsável principal
        por registrar impressões no sistema."""
        self.log(f"[v{self.version}] Monitor Event Log iniciado — verificando a cada {EVENT_LOG_INTERVAL}s.")
        while True:
            try:
                self._fallback_event_log()
            except Exception as e:
                self.log(f"Erro no monitor Event Log: {e}")
            time.sleep(EVENT_LOG_INTERVAL)

    # ----------------------------------------------------------
    #   FALLBACK: Event Log (caso a API Win32 não funcione)
    # ----------------------------------------------------------
    def _fallback_event_log(self):
        """Captura via Get-WinEvent como fallback de segurança."""
        try:
            ps_cmd = ('powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "'
                      '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
                      'Get-WinEvent -LogName \'Microsoft-Windows-PrintService/Operational\' '
                      '-FilterXPath \'*[System[(EventID=307)]]\' -MaxEvents 50 '
                      '-ErrorAction SilentlyContinue | ForEach-Object { $_.ToXml() } | ConvertTo-Json"')
            result = subprocess.run(ps_cmd, capture_output=True, text=True, shell=True, encoding='utf-8')
            if not result.stdout or not result.stdout.strip():
                return

            raw = json.loads(result.stdout)
            xmls = raw if isinstance(raw, list) else [raw]
            xmls.reverse()  # processa do mais velho ao mais novo

            def get_xml_param(xml, param_name):
                """Extrai o valor de um parâmetro do XML de forma robusta."""
                # Tenta formato <ParamX>valor</ParamX>
                m = re.search(f'<{param_name}>(.*?)</{param_name}>', xml, re.IGNORECASE)
                if m: return m.group(1).strip()
                
                # Tenta formato <Data Name="ParamX">valor</Data>
                m = re.search(f'Name=["\']{param_name}["\']>(.*?)</Data>', xml, re.IGNORECASE)
                if m: return m.group(1).strip()
                
                return None

            new_jobs = []
            for xml_str in xmls:
                try:
                    # Captura timestamp
                    m_time = re.search(r"SystemTime=['\"](.*?)['\"]", xml_str)
                    if not m_time: continue
                    
                    created_at = m_time.group(1)
                    ev_time = datetime.fromisoformat(created_at.replace('Z', ''))
                    if ev_time <= self.last_event_time:
                        continue

                    # Tenta capturar parâmetros de forma robusta
                    printer = get_xml_param(xml_str, 'Param5') or "Desconhecida"
                    if is_virtual_printer(printer) and not is_digital_printer(printer):
                        continue

                    doc   = get_xml_param(xml_str, 'Param2') or ""
                    user  = get_xml_param(xml_str, 'Param3') or self.current_user
                    pages = 1
                    try:
                        p_val = get_xml_param(xml_str, 'Param8')
                        if p_val: pages = int(p_val)
                    except: pass

                    # LIMPEZA CRUCIAL: Limpar o nome ANTES de verificar duplicata
                    # para que o nome vindo do EventLog bata com o do Spooler
                    raw_title = doc
                    doc_clean = clean_doc_name(doc)
                    
                    # Fallback simples de janela
                    wt = get_active_window_title()

                    if not doc_clean or doc_clean.lower() in GENERIC_DOC_NAMES:
                        if wt: 
                            raw_title = wt
                            doc_clean = clean_doc_name(wt) or "Documento Capturado"
                        else:
                            doc_clean = doc_clean or "Documento Capturado"

                    # DEDUPLICAÇÃO: Agora com nomes normalizados
                    job_id_ev = get_xml_param(xml_str, 'Param1') or "EV"
                    duplicate = self.is_duplicate_job(printer, job_id_ev, doc_clean, user, pages)
                    # Avança o cursor mesmo quando o job já foi visto pelo
                    # monitor do Spooler; evita reprocessar o mesmo evento a
                    # cada ciclo de 10 segundos.
                    if ev_time > self.last_event_time:
                        self.last_event_time = ev_time
                    if duplicate:
                        continue

                    new_jobs.append({
                        "DocumentName": doc_clean,
                        "UserName": user, 
                        "PrinterName": printer, 
                        "TotalPages": pages,
                        "AppProcess": raw_title,
                        "Digital": is_digital_printer(printer)
                    })
                except Exception:
                    continue

            if new_jobs:
                self.log(f"  -> {len(new_jobs)} capturado(s) via Fallback (Event Log).")
                self.send_to_server({"tipo": "impressoes", "jobs": new_jobs})

        except Exception as e:
            self.log(f"Erro no fallback Event Log: {e}")

    # ----------------------------------------------------------
    def heartbeat(self):
        while True:
            res = self.send_to_server({
                "tipo": "heartbeat",
                "status": "online",
                "windows_user": self.current_user
            })
            if res:
                self.log(f"  -> Sinal de vida enviado (Usuario: {self.current_user})")
            time.sleep(HEARTBEAT_INTERVAL)

    def run(self):
        self.log(f"========================================")
        self.log(f"  PRINTDASH AGENTE v{self.version} INICIADO")
        self.log(f"  Máquina : {self.hostname}")
        self.log(f"  IP      : {self.local_ip}")
        self.log(f"  Usuário : {self.current_user}")
        self.log(f"  Servidor: {SERVER_URL}")
        self.log(f"========================================")

        threads = [
            threading.Thread(target=self.heartbeat,          daemon=True, name="Heartbeat"),
            threading.Thread(target=self.monitor_spooler,    daemon=True, name="SpoolerMonitor"),
            threading.Thread(target=self.monitor_event_log,  daemon=True, name="EventLogMonitor"),
            threading.Thread(target=run_id_server,           daemon=True, name="IDServer"),
        ]
        for t in threads:
            t.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.log("Agente encerrado pelo usuário.")

if __name__ == "__main__":
    agent = PrintAgent()
    agent.run()
