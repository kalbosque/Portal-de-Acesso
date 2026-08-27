import os
import json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Header, HTTPException, Request, BackgroundTasks, Form, UploadFile, File
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.websockets import WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlmodel import Session, create_engine, select, func, SQLModel, desc
from models import Usuario, Impressora, Impressao, Licenca, Chamado, ChamadoInteracao, TipoProblema, EquipamentoTI, MarmitaCardapio, MarmitaPedido
import license_service
import api_printers
import api_reports
import api_users_monitor
import api_dashboard
import api_users_mgmt
import api_settings
import api_auth
import api_tickets
import api_finance
import api_avisos
import api_equipamentos_ti
import api_cofre
import api_whatsapp
from database import engine
from dotenv import load_dotenv
from websocket_manager import manager
from auth_utils import get_signed_cookie, normalize_permissions

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# FunÃ§Ã£o para carregar configuraÃ§Ãµes originais do PHP
def load_app_config():
    config_path = os.path.join(BASE_DIR, "public_html", "includes", "config.json")
    default_config = {
        "APP_NAME": "PrintDash",
        "APP_COLOR": "#6366f1",
        "APP_LOGO_URL": ""
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except: pass
    return default_config

APP_CONFIG = load_app_config()

# engine agora vem do database.py
app = FastAPI(title=APP_CONFIG.get("APP_NAME", "PrintDash"))

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Templates
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
def from_json_filter(value):
    try:
        if not value: return []
        return json.loads(value)
    except:
        return []
templates.env.filters["from_json"] = from_json_filter

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Respond to ping to keep connection alive
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


def include_router_if_available(module, module_name: str):
    """Inclui um router apenas quando o mÃ³dulo realmente expÃµe `router`."""
    router = getattr(module, "router", None)
    if router is None:
        print(f"[STARTUP] Ignorando {module_name}: nenhum router exportado.")
        return

    app.include_router(router)
    print(f"[STARTUP] Router carregado: {module_name}")


def ensure_schema_compatibility():
    """Aplica ajustes pequenos no schema sem apagar dados existentes."""
    from sqlalchemy import text

    statements = [
        "ALTER TABLE impressoras ADD COLUMN IF NOT EXISTS modelo VARCHAR(120)",
        "ALTER TABLE impressoras ADD COLUMN IF NOT EXISTS localizacao VARCHAR(120)",
        "ALTER TABLE tipos_problemas ADD COLUMN IF NOT EXISTS sla_horas INTEGER DEFAULT 24",
        "ALTER TABLE equipamentos_ti ADD COLUMN IF NOT EXISTS modelo_monitor VARCHAR(120)",
        "ALTER TABLE equipamentos_ti ADD COLUMN IF NOT EXISTS quantidade_monitores INTEGER",
        "ALTER TABLE equipamentos_ti ADD COLUMN IF NOT EXISTS nome_computador VARCHAR(120)",
        "ALTER TABLE equipamentos_ti ADD COLUMN IF NOT EXISTS data_registro TIMESTAMP NULL",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS ip_address TEXT",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS user_agent TEXT",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS unread_admin INTEGER DEFAULT 0",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS unread_user INTEGER DEFAULT 0",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS vencimento_sla TIMESTAMP NULL",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS avaliacao_estrelas INTEGER",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS avaliacao_comentario TEXT",
        "ALTER TABLE cofre_senhas ADD COLUMN IF NOT EXISTS setor VARCHAR(80) DEFAULT 'TI'",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_cliente VARCHAR(80)",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_instance VARCHAR(120)",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS origem VARCHAR(50) DEFAULT 'Web'",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS assigned_user VARCHAR(120)",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS visivel_suporte BOOLEAN DEFAULT TRUE",
        "ALTER TABLE chamados_interacoes ADD COLUMN IF NOT EXISTS whatsapp_status VARCHAR(20) DEFAULT 'sent'",
        "ALTER TABLE impressoes DROP CONSTRAINT IF EXISTS impressoes_tipo_impressao_check",
        "ALTER TABLE impressoes ADD CONSTRAINT impressoes_tipo_impressao_check CHECK (tipo_impressao IN ('Preto e Branco', 'Colorida', 'Digital', 'P&B', 'Colorido'))",
    ]

    # Cada ajuste usa sua própria transação. Assim, uma alteração opcional
    # que falhe não desfaz as colunas essenciais de chamados/WhatsApp.
    for statement in statements:
        try:
            with engine.begin() as conn:
                conn.execute(text(statement))
        except Exception as exc:
            print(f"[SCHEMA] Ajuste ignorado: {statement[:90]}... ({exc})")


def ensure_whatsapp_columns():
    statements = [
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_cliente VARCHAR(80)",
        "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_instance VARCHAR(120)"
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


@app.get("/chamados", response_class=HTMLResponse)
async def view_chamados(request: Request, success: str = None, error: str = None):
    print("[FORCE_CHAMADOS_ROUTE] Entering function")
    try:
        user_id = request.cookies.get("user_id")
        if not user_id: return RedirectResponse(url="/login")
        
        user_role = request.cookies.get("user_role")
        user_name = request.cookies.get("user_name")
        
        with Session(engine) as session:
            impressoras = session.exec(select(Impressora)).all()
            atalhos = session.exec(select(TipoProblema)).all()
            
            hoje = datetime.now().date()
            amanha = hoje + timedelta(days=1)
            quatro_horas_atras = datetime.now() - timedelta(hours=4)

            try:
                if user_role == "admin":
                    chamados = session.exec(select(Chamado).where(Chamado.visivel_suporte == True).order_by(desc(Chamado.data_abertura))).all()
                else:
                    chamados = session.exec(select(Chamado).where(Chamado.usuario == user_name, Chamado.visivel_suporte == True).order_by(desc(Chamado.data_abertura))).all()
            except ProgrammingError as pe:
                if "whatsapp_instance" in str(pe) or "whatsapp_cliente" in str(pe):
                    print(f"[STARTUP] Detectado erro de schema WhatsApp em chamados: {pe}. Aplicando correção de schema.")
                    # A consulta que falhou deixa a transação SQLAlchemy abortada.
                    # Sem rollback, a nova consulta falha mesmo após criar as colunas.
                    session.rollback()
                    ensure_whatsapp_columns()
                    if user_role == "admin":
                        chamados = session.exec(select(Chamado).where(Chamado.visivel_suporte == True).order_by(desc(Chamado.data_abertura))).all()
                    else:
                        chamados = session.exec(select(Chamado).where(Chamado.usuario == user_name, Chamado.visivel_suporte == True).order_by(desc(Chamado.data_abertura))).all()
                else:
                    raise

            total_tickets = len(chamados)
            abertos = sum(1 for c in chamados if c.status == "Aberto")
            atendimento = sum(1 for c in chamados if c.status == "Em Atendimento")
            resolvidos = sum(1 for c in chamados if c.status == "Resolvido")
            resolvidos_hoje = sum(1 for c in chamados if c.status == "Resolvido" and c.data_resolucao and hoje <= c.data_resolucao.date() < amanha)
            urgentes = sum(1 for c in chamados if c.status == "Aberto" and getattr(c, "data_abertura", datetime.now()) < quatro_horas_atras)

            saude_val = round((resolvidos / total_tickets * 100)) if total_tickets > 0 else 100

            msg = ""
            t_msg = ""
            if success == "1":
                msg = "Protocolo registrado com sucesso!"
                t_msg = "success"
            elif success == "resolved":
                msg = "Chamado encerrado!"
                t_msg = "success"
            elif error == "duplicado":
                msg = "SolicitaÃ§Ã£o jÃ¡ recebida."
                t_msg = "warning"

            render_context = {
                "request": request,
                "config": APP_CONFIG,
                "is_admin": user_role == "admin",
                "impressoras": [i.dict() for i in impressoras],
                "atalhos": [a.dict() for a in atalhos],
                "message": msg,
                "tipo_msg": t_msg,
                "estatisticas_tickets": {
                    "abertos": int(abertos),
                    "atendimento": int(atendimento),
                    "resolvidos": int(resolvidos),
                    "resolvidos_hoje": int(resolvidos_hoje),
                    "urgentes": int(urgentes),
                    "total": int(total_tickets),
                    "saude": int(saude_val)
                },
                "chamados": [c.dict() for c in chamados]
            }
            return templates.TemplateResponse(request, "chamados.html", render_context)
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print(f"CRITICAL ERROR IN VIEW_CHAMADOS:\n{err}")
        return HTMLResponse(content=f"<h1>DEBUG ERROR</h1><pre>{err}</pre>", status_code=500)

include_router_if_available(api_printers, "api_printers")
include_router_if_available(api_reports, "api_reports")
include_router_if_available(api_dashboard, "api_dashboard")
include_router_if_available(api_tickets, "api_tickets")
include_router_if_available(api_users_monitor, "api_users_monitor")
include_router_if_available(api_users_mgmt, "api_users_mgmt")
include_router_if_available(api_settings, "api_settings")
include_router_if_available(api_auth, "api_auth")
include_router_if_available(api_finance, "api_finance")
include_router_if_available(api_avisos, "api_avisos")
include_router_if_available(api_equipamentos_ti, "api_equipamentos_ti")
include_router_if_available(api_cofre, "api_cofre")
include_router_if_available(api_whatsapp, "api_whatsapp")

# ─────────────────────────────────────────────────────────────────────────────
# 🤖 Endpoint: Chat do Assistente Contador
# ─────────────────────────────────────────────────────────────────────────────
from fastapi.responses import JSONResponse
from pydantic import BaseModel as PydanticBaseModel

class ChatRequest(PydanticBaseModel):
    mensagem: str

RESPOSTAS_IA = [
    # ---- DÚVIDAS DO PORTAL / TI ----
    (["impressora","imprimir","impressão","toner","papel","offline","online","equipamento"],
     "🖨️ Para verificar o status das impressoras, acesse o menu **Impressoras**. Lá você vê quais estão online, nível de toner e os últimos trabalhos. Se uma impressora estiver offline, tente reiniciá-la ou abra um chamado!"),
    (["chamado","suporte","problema","ticket","abrir","atendimento","solicitação","reclamação"],
     "🎫 Abra um chamado de suporte clicando em **Chamados** no menu lateral. Descreva o problema detalhadamente (ex: 'Impressora RH atolou') para agilizar o atendimento. Nosso time técnico responde rápido!"),
    (["usuário","usuario","acesso","login","senha","perfil","permissão","cadastro","bloqueado"],
     "👤 Questões de usuários e acesso estão em **Usuários** no painel administrativo. Se alguém esqueceu a senha, há a opção de reset na tela de login ou você mesmo pode gerar uma nova pelo painel."),
    (["relatorio","relatório","gráfico","estatística","histórico","dados","exportar","excel"],
     "📊 Os relatórios completos de impressão e custos ficam na seção **Relatórios**. Você pode filtrar por data, departamento ou usuário, e depois exportar tudo para Excel!"),
    (["custo","valor","fatura","financeiro","pagamento","gasto","preço","dinheiro","real"],
     "💰 O controle financeiro e custos de impressão estão na seção **Financeiro**. Lá você acompanha os gastos totais e por departamento (Rateio) de cada período."),
    (["rede","maquina","máquina","computador","pc","monitor","conectado"],
     "🖥️ O **Monitor de Rede** mostra em tempo real quais máquinas e IPs estão conectados. Acesse pelo menu principal para ver o status da rede e tempo de inatividade."),
    (["cofre","senha","credencial","segurança","chave","secret"],
     "🔐 O **Cofre de Senhas** é o local seguro para guardar credenciais corporativas, senhas de roteadores e do certificado digital. Fica criptografado e apenas admins acessam."),
    (["dashboard","painel","inicio","início","resumo","geral"],
     "📈 O **Dashboard** é a tela inicial com os indicadores principais: máquinas online, impressoras ativas, páginas totais e custos. Ele atualiza automaticamente a cada 5 segundos!"),
    (["configuração","configuracoes","configurar","definição","logo","cor","tema"],
     "⚙️ As **Configurações** do sistema ficam no menu lateral (ícone de engrenagem). Lá você altera o nome do escritório, logo, paleta de cores e regras de negócio do Portal."),

    # ---- DÚVIDAS CONTÁBEIS / RH / FISCAL ----
    (["mei","microempreendedor","das","limite mei","desenquadramento"],
     "🏢 **MEI (Microempreendedor Individual)**:\n• O limite de faturamento atual é R$ 81.000,00 anuais (proporcional no ano de abertura).\n• O imposto (DAS) vence todo dia 20 e é um valor fixo mensal.\n• Pode ter no máximo 1 empregado registrado."),
    (["simples nacional","simples","anexo","das simples","alíquota","aliquota"],
     "📄 **Simples Nacional**:\n• Regime tributário simplificado que une federais, estaduais e municipais em 1 guia (DAS).\n• Vence no dia 20 do mês seguinte ao faturamento.\n• Possui 5 anexos (I: Comércio, II: Indústria, III a V: Serviços). A alíquota inicial varia de 4% a 15,5%."),
    (["férias","ferias","1/3","abono pecuniário","vender férias"],
     "🏖️ **Férias**:\n• O empregado tem direito a 30 dias após 12 meses trabalhados (período aquisitivo).\n• O pagamento deve ser feito até 2 dias ANTES do início das férias.\n• É acrescido do terço constitucional (1/3).\n• Pode vender até 10 dias (abono pecuniário)."),
    (["décimo terceiro","decimo terceiro","13","13º"],
     "🎄 **13º Salário**:\n• A 1ª parcela (50% sem descontos) deve ser paga até 30 de novembro.\n• A 2ª parcela (com descontos de INSS e IRRF) deve ser paga até 20 de dezembro.\n• Cada mês com 15 dias ou mais trabalhados dá direito a 1/12 avos."),
    (["rescisão","rescisao","demissão","demissao","aviso prévio","justa causa","seguro desemprego"],
     "🛑 **Rescisão de Contrato**:\n• Em dispensa *sem justa causa*, paga-se: saldo de salário, férias proporcionais + 1/3, 13º proporcional e multa de 40% do FGTS.\n• O aviso prévio pode ser trabalhado (30 a 90 dias) ou indenizado.\n• O pagamento da rescisão deve ser feito em até 10 dias após o término do contrato."),
    (["fgts","fundo de garantia","saque aniversário","multa fgts"],
     "🏗️ **FGTS**:\n• Recolhimento mensal de 8% do salário (2% para Jovem Aprendiz).\n• Vence até o dia 20 do mês seguinte (pelo eSocial/FGTS Digital).\n• Em caso de dispensa sem justa causa, a empresa paga 40% de multa sobre o saldo."),
    (["inss","previdência","aposentadoria","contribuição","desconto inss"],
     "👴 **INSS**:\n• As alíquotas de desconto para empregados são progressivas: 7,5%, 9%, 12% ou 14% de acordo com a faixa salarial.\n• O limite máximo de desconto segue o teto do INSS do ano vigente.\n• O vencimento da guia (DARF Previdenciário) é até o dia 20."),
    (["irpf","imposto de renda","malha fina","restituição","carnê leão"],
     "🦁 **Imposto de Renda Pessoa Física (IRPF)**:\n• O prazo de entrega anual geralmente vai de março a maio.\n• Fica obrigado a declarar quem obteve rendimentos tributáveis acima do limite isento no ano base.\n• O IRRF (retido na fonte) começa a descontar nos salários acima de R$ 2.824,00 (tabela de 2024), descontando a parcela a deduzir."),
    (["certidão","certidao","cnd","negativa","regularidade"],
     "📜 **Certidões (CND)**:\n• A Certidão Negativa de Débitos atesta que a empresa não tem dívidas.\n• **Receita Federal**: Dívidas tributárias e previdenciárias.\n• **FGTS**: Emitida pela Caixa Econômica.\n• **Trabalhista (CNDT)**: Emitida pelo TST."),
    (["esocial","e-social","folha","fechamento","dctfweb"],
     "💻 **eSocial & DCTFWeb**:\n• O eSocial unificou a entrega de informações trabalhistas e previdenciárias.\n• A folha de pagamento deve ser fechada e transmitida até o dia 15.\n• Os tributos (INSS) são gerados pelo DCTFWeb com vencimento para o dia 20."),

    # ---- BÁSICOS ----
    (["oi","olá","ola","bom dia","boa tarde","boa noite","tudo bem","tudo bom","hey","hello"],
     "😊 Olá! Tudo ótimo por aqui! Sou o Contadorzinho, seu assistente virtual de TI e Contabilidade. Pode me perguntar sobre impressoras, relatórios, MEI, rescisões, Simples Nacional... o que precisar!"),
    (["quem","você","voce","seu nome","nome","assistente","ajuda","o que faz","chatbot","ia","bot"],
     "🧑‍💼 Sou o **Contadorzinho**, o assistente oficial do Portal de Acesso! Fui treinado com dezenas de regras contábeis, trabalhistas e de TI para tirar suas dúvidas rápidas do dia a dia do escritório. Do Simples Nacional à impressora sem papel, é só mandar a dúvida!"),
    (["obrigado","obrigada","valeu","thanks","grato","grata","ajudou","top","perfeito"],
     "😄 Eu que agradeço! Se surgir mais alguma dúvida no escritório, é só me chamar. Bom trabalho! 👋"),
]

def responder_contador(mensagem: str) -> str:
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
            prompt = (
                "Você é o 'Contadorzinho', um assistente virtual super inteligente, experiente e simpático "
                "de um escritório de contabilidade (Portal de Acesso). "
                "Sua função é responder dúvidas sobre contabilidade (tributária, trabalhista, societária, MEI, Simples Nacional, etc), "
                "bem como funções de TI (impressoras, chamados, rede). "
                "Seja direto, prestativo e use alguns emojis para deixar o texto leve. "
                "Sempre formate em Markdown com listas e negrito quando facilitar a leitura."
            )
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": mensagem}
                ],
                max_tokens=600,
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ Ops, erro na conexão com o DeepSeek: {str(e)}"

    # Fallback local se não houver chave do DeepSeek
    texto = mensagem.lower().strip()
    for palavras, resposta in RESPOSTAS_IA:
        if any(p in texto for p in palavras):
            return resposta
    return ("🤔 Minha conexão com o **DeepSeek** ainda não está ativa (falta a variável `DEEPSEEK_API_KEY` no `.env`). "
            "Por enquanto só sei responder sobre: **impressoras**, **chamados**, **relatórios** ou **usuários**!")

@app.post("/api/contador-chat")
async def contador_chat(req: ChatRequest, request: Request):
    if not req.mensagem or len(req.mensagem.strip()) < 1:
        return JSONResponse({"ok": False, "error": "Mensagem vazia"})
    resposta = responder_contador(req.mensagem)
    return JSONResponse({"ok": True, "resposta": resposta})

# Montar Arquivos EstÃ¡ticos (CSS, JS, etc.)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
# Montar Pasta de Uploads (Logo, Documentos, etc.)
app.mount("/uploads", StaticFiles(directory=os.path.join(BASE_DIR, "public_html", "uploads")), name="uploads")

# Inicializar Banco
@app.on_event("startup")
def on_startup():
    import time
    last_error = None
    for attempt in range(30):
        try:
            SQLModel.metadata.create_all(engine)
            ensure_schema_compatibility()
            print("[STARTUP] Banco inicializado com sucesso.")
            return
        except Exception as e:
            last_error = e
            print(f"[STARTUP] Banco indisponÃ­vel (tentativa {attempt + 1}/30): {e}")
            time.sleep(2)

    print(f"[STARTUP] Seguindo sem criar tabelas apÃ³s falha persistente: {last_error}")



AGENT_API_KEY = os.getenv("AGENT_API_KEY")

@app.get("/api/agent/download_latest")
async def download_latest_agent(x_api_key: Optional[str] = Header(None)):
    """Entrega o executável atual para o auto-update do agente."""
    if not AGENT_API_KEY or x_api_key != AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="Não autorizado")

    candidates = [
        os.path.abspath(os.path.join(BASE_DIR, "..", "dist", "agent_2.0.exe")),
        os.path.abspath(os.path.join(BASE_DIR, "..", "agent_2.0.exe")),
    ]
    exe_path = next((path for path in candidates if os.path.isfile(path)), None)
    if not exe_path:
        raise HTTPException(status_code=404, detail="Executável do agente não encontrado")

    return FileResponse(
        exe_path,
        media_type="application/vnd.microsoft.portable-executable",
        filename="agent_2.0.exe",
    )

def update_status_files(maquina: str, ip: str, payload: dict, versao: str):
    """Atualiza os arquivos JSON de status exportando do DB para manter compatibilidade"""
    from models import StatusMaquina
    agora = datetime.now()
    status_file = "status_maquinas.json"
    
    with Session(engine) as session:
        # Atualizar no DB (Single Source of Truth)
        stat = session.get(StatusMaquina, ip)
        if not stat:
            stat = StatusMaquina(ip=ip)
        stat.nome = maquina
        stat.status = "Online"
        stat.windows_user = payload.get("windows_user", "Desconhecido")
        stat.timestamp = agora
        stat.versao_agente = versao
        session.add(stat)
        
        # Remove registros antigos da mesma máquina com IP diferente (evitar duplicação Offline/Online)
        old_stats = session.exec(select(StatusMaquina).where(StatusMaquina.nome == maquina).where(StatusMaquina.ip != ip)).all()
        for old in old_stats:
            session.delete(old)
            
        session.commit()
        
        # Gerar o JSON completo a partir do DB apenas a cada 5 segundos
        # Para evitar que mÃºltiplos workers destruam o disco, usaremos probabilidade simples 
        # ou apenas tentamos gravar e ignoramos erros. O DB Ã© a fonte confiÃ¡vel.
        import time
        global last_flush_time
        if 'last_flush_time' not in globals():
            last_flush_time = 0
            
        current_time = time.time()
        if current_time - last_flush_time > 5:
            last_flush_time = current_time
            try:
                all_stats = session.exec(select(StatusMaquina)).all()
                data = {"Maquinas": {}}
                for s in all_stats:
                    data["Maquinas"][s.ip] = {
                        "Nome": s.nome,
                        "Status": "Online" if (agora - s.timestamp).total_seconds() < 300 else "Offline",
                        "WindowsUser": s.windows_user,
                        "Timestamp": s.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                        "VersaoAgente": s.versao_agente
                    }
                data["UltimaAtualizacao"] = agora.strftime("%Y-%m-%d %H:%M:%S")
                with open(status_file, "w") as f:
                    json.dump(data, f, indent=4)
            except: pass

def classify_doc_type(doc_name: str, app_process: str) -> str:
    """Classifica o tipo de documento (mesma lÃ³gica do PHP)"""
    doc_lower = doc_name.lower()
    app_lower = app_process.lower()
    
    if any(x in app_lower for x in ["winword", "word"]): return "Word"
    if any(x in app_lower for x in ["excel", "xls"]): return "Excel"
    if any(x in app_lower for x in ["powerpnt", "powerpoint"]): return "PPT"
    if any(x in app_lower for x in ["acrord", "pdf"]): return "PDF"
    if any(x in app_lower for x in ["chrome", "msedge", "firefox"]): return "Web"
    
    # Fallback por extensÃ£o/nome
    if ".pdf" in doc_lower: return "PDF"
    if ".doc" in doc_lower or ".docx" in doc_lower: return "Word"
    if ".xls" in doc_lower or ".xlsx" in doc_lower: return "Excel"
    
    return "Sistema"

@app.post("/api/v1/agent")
@limiter.limit("60/minute")
async def agent_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None)
):
    if not AGENT_API_KEY or x_api_key != AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="NÃ£o autorizado")
    
    data = await request.json()
    maquina = data.get("maquina")
    ip = data.get("ip")
    versao = data.get("versao", "2.0")
    payload = data.get("dados", {})
    tipo = payload.get("tipo")
    
    if tipo == "heartbeat":
        background_tasks.add_task(update_status_files, maquina, ip, payload, versao)
        return {
            "success": True, 
            "latest_version": "2.4.3",
            "commands": []
        }
    
    if tipo == "impressoes":
        from notifications import send_alert
        with Session(engine) as session:
            for job in payload.get("jobs", []):
                # Busca impressora
                printer_name = job.get("PrinterName", "Padrao")
                statement = select(Impressora).where(Impressora.nome == printer_name)
                printer = session.exec(statement).first()
                
                if not printer:
                    printer = Impressora(nome=printer_name, ip=ip, status="Online")
                    session.add(printer)
                    session.commit()
                    session.refresh(printer)
                
                # Classifica e Salva
                doc_name = job.get("DocumentName", "Documento")
                app_proc = job.get("AppProcess", "")
                tipo_doc = classify_doc_type(doc_name, app_proc)
                paginas = int(job.get("TotalPages", 1))
                digital = bool(job.get("Digital", False))
                preco_unitario = 0.0 if digital else 0.10
                
                nova_imp = Impressao(
                    usuario=job.get("UserName", "Sistema"),
                    impressora_id=printer.id,
                    maquina=maquina,
                    documento=doc_name,
                    tipo_documento=tipo_doc,
                    paginas=paginas,
                    tipo_impressao="Digital" if digital else "Preto e Branco",
                    ip_maquina=ip,
                    preco_unitario=preco_unitario,
                    valor_total=paginas * preco_unitario
                )
                session.add(nova_imp)
                
                # Alerta de volume alto (ex: 50+ paginas)
                if paginas >= 50:
                    msg = (
                        f"⚠️ *ALERTA DE ALTO VOLUME*\n\n"
                        f"👤 Usuário: {nova_imp.usuario}\n"
                        f"🖨️ Impressora: {printer.nome}\n"
                        f"📝 Documento: {doc_name}\n"
                        f"📄 Páginas: {paginas}"
                    )
                    background_tasks.add_task(send_alert, msg)

            session.commit()
            
    return {"success": True}

# --- ROTA DE COMPATIBILIDADE: Agentes Antigos (v1/v2) ---
# Agentes instalados com API_URL="http://.../api_agente_v2.php" ainda chamam esta rota.
# Redirecionamos internamente para o mesmo handler sem exigir atualizaÃ§Ã£o do agente.
@app.post("/api_agente_v2.php")
@limiter.limit("60/minute")
async def agent_compat_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None)
):
    """Alias de compatibilidade para agentes legados."""
    return await agent_endpoint(request, background_tasks, x_api_key)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id: return RedirectResponse(url="/login")
    
    with Session(engine) as session:
        # Busca o usuÃ¡rio no banco para ter as permissÃµes REAIS e ATUAIS
        user = session.get(Usuario, int(user_id))
        if not user: return RedirectResponse(url="/login")

        # Redirecionamento forÃ§ado em tempo real
        try:
            user_perms = normalize_permissions(json.loads(user.permissoes or "[]"))
            print(f"[FORCE_REDIRECT_DEBUG] User: {user.username}, Role: {user.role}, Perms: {user_perms}")
            
            if user.role == "operator":
                # Se for operador, vamos ver se ele tem Dashboard. Se NÃƒO tiver, manda pra /meu_painel.
                if "Dashboard" not in user_perms:
                    print(f"[FORCE_REDIRECT_ACTION] Redirecting {user.username} to /meu_painel")
                    return RedirectResponse(url="/meu_painel")
        except Exception as e:
            print(f"[FORCE_REDIRECT_ERROR] {str(e)}")
            pass

        hoje = datetime.now().date()
        
        # EstatÃ­sticas do Dashboard Executivo
        total_paginas = session.exec(select(func.sum(Impressao.paginas))).one() or 0
        faturamento = session.exec(select(func.sum(Impressao.valor_total))).one() or 0
        paginas_hoje = session.exec(select(func.sum(Impressao.paginas)).where(func.date(Impressao.data_hora) == hoje)).one() or 0
        
        # MÃ¡quinas na Rede (Dados do Agente)
        from models import StatusMaquina
        try:
            total_maquinas = session.exec(select(func.count(StatusMaquina.ip))).one() or 0
            
            from datetime import timedelta
            limite_online = datetime.now() - timedelta(minutes=5)
            maquinas_online = session.exec(select(func.count(StatusMaquina.ip)).where(StatusMaquina.timestamp >= limite_online)).one() or 0
        except Exception as e:
            print("Erro ao carregar maquinas:", str(e))
            maquinas_online = 0
            total_maquinas = 0

        # EstatÃ­sticas de Chamados (TI)
        from models import Chamado
        total_chamados = session.exec(select(func.count(Chamado.id))).one() or 0
        urgentes_chamados = session.exec(
            select(func.count(Chamado.id)).where(
                Chamado.status == 'Aberto',
                Chamado.data_abertura < (datetime.now() - timedelta(hours=4))
            )
        ).one() or 0
        stats_chamados = {
            "abertos": session.exec(select(func.count(Chamado.id)).where(Chamado.status == 'Aberto')).one(),
            "atendimento": session.exec(select(func.count(Chamado.id)).where(Chamado.status == 'Em Atendimento')).one(),
            "resolvidos": session.exec(select(func.count(Chamado.id)).where(Chamado.status == 'Resolvido')).one(),
            "total": total_chamados,
            "urgentes": urgentes_chamados,
            "saude": round((session.exec(select(func.count(Chamado.id)).where(Chamado.status == 'Resolvido')).one() or 0) / total_chamados * 100) if total_chamados > 0 else 100
        }

        # Dados para GrÃ¡ficos
        # Top 5 Impressoras
        stmt_imp = select(Impressora.nome, func.sum(Impressao.paginas).label("total")).join(Impressao, Impressao.impressora_id == Impressora.id).group_by(Impressora.nome).order_by(desc(func.sum(Impressao.paginas))).limit(5)
        top_impressoras = session.exec(stmt_imp).all()
        
        # Top 5 UsuÃ¡rios
        stmt_usu = select(Impressao.usuario, func.sum(Impressao.paginas).label("total")).group_by(Impressao.usuario).order_by(desc(func.sum(Impressao.paginas))).limit(5)
        top_usuarios = session.exec(stmt_usu).all()

        # Atividade Recente Detalhada
        atividades_raw = session.exec(select(Impressao).order_by(desc(Impressao.data_hora)).limit(10)).all()
        atividades_fmt = []
        for imp in atividades_raw:
            # ProteÃ§Ã£o para valores do PHP (ex: "1,50" em vez de 1.50)
            try:
                v = float(str(imp.valor_total).replace(",", ".")) if imp.valor_total else 0.0
            except:
                v = 0.0
            
            # ProteÃ§Ã£o para datas que podem vir como string do SQLite
            try:
                if isinstance(imp.data_hora, str):
                    dt = datetime.strptime(imp.data_hora[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                else:
                    dt = imp.data_hora
                d_str = dt.strftime('%d/%m')
                h_str = dt.strftime('%H:%M')
            except:
                d_str = "--/--"
                h_str = "--:--"
                
            atividades_fmt.append({
                "data_str": d_str,
                "hora_str": h_str,
                "tipo_documento": imp.tipo_documento,
                "tipo_impressao": imp.tipo_impressao,
                "documento": imp.documento,
                "maquina": imp.maquina,
                "usuario": imp.usuario,
                "paginas": imp.paginas,
                "tipo_impressao": imp.tipo_impressao or "Preto e Branco",
                "valor_fmt": f"{v:.2f}".replace(".", ",")
            })

        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "config": APP_CONFIG,
                "user_perms_real": user_perms,
                "stats": {
                    "paginas_total": total_paginas,
                    "faturamento": faturamento,
                    "paginas_hoje": paginas_hoje,
                    "maquinas_online": maquinas_online,
                    "total_maquinas": total_maquinas,
                    "impressoras_online": session.exec(select(func.count(Impressora.id)).where(Impressora.status == "Online")).one(),
                    "chamados": stats_chamados
                },
                "top_impressoras": [{"nome": i[0] or "Local", "total": int(i[1] or 0)} for i in top_impressoras],
                "top_usuarios": [{"nome": u[0] or "Desconhecido", "total": int(u[1] or 0)} for u in top_usuarios],
                "atividades": atividades_fmt,
                "hoje": hoje.strftime('%d/%m/%Y')
            }
        )

# --- APIs COMPATÃVEIS COM O DASHBOARD ---

@app.get("/api/stats_impressao")
async def api_stats_impressao():
    with Session(engine) as session:
        # Top 5 Impressoras
        # Nota: JOIN com Impressora para pegar o nome
        results = session.exec(
            select(Impressora.nome, func.sum(Impressao.paginas).label("total"))
            .join(Impressao, Impressao.impressora_id == Impressora.id)
            .group_by(Impressora.nome)
            .order_by(func.sum(Impressao.paginas).desc())
            .limit(5)
        ).all()
        por_impressora = [{"nome": r[0], "total": int(r[1])} for r in results]

        # Top 5 UsuÃ¡rios
        results_u = session.exec(
            select(Impressao.usuario, func.sum(Impressao.paginas))
            .group_by(Impressao.usuario)
            .order_by(func.sum(Impressao.paginas).desc())
            .limit(5)
        ).all()
        por_usuario = [{"nome": r[0], "total": int(r[1])} for r in results_u]

        return {
            "success": True,
            "stats": {
                "impressoras": por_impressora,
                "usuarios": por_usuario
            }
        }

@app.get("/api/recent_activity")
async def api_recent_activity():
    with Session(engine) as session:
        # JOIN com Impressora para pegar o nome_impressora
        statement = select(Impressao, Impressora.nome).join(Impressora, isouter=True).order_by(Impressao.data_hora.desc()).limit(8)
        results = session.exec(statement).all()
        
        atividades = []
        for imp, nome_imp in results:
            atividades.append({
                "id": imp.id,
                "usuario": imp.usuario,
                "maquina": imp.maquina,
                "documento": imp.documento,
                "tipo_documento": imp.tipo_documento,
                "paginas": imp.paginas,
                "tipo_impressao": imp.tipo_impressao,
                "valor_total": imp.valor_total,
                "nome_impressora": nome_imp or "Local",
                "data_formatada": imp.data_hora.strftime("%d/%m"),
                "hora_formatada": imp.data_hora.strftime("%H:%M:%S")
            })

        return {
            "success": True,
            "atividades": atividades
        }

# --- FINANCEIRO ---

@app.get("/financeiro", response_class=HTMLResponse)
def view_financeiro(request: Request):
    user_id = get_signed_cookie(request, "user_id")
    user_role = get_signed_cookie(request, "user_role")
    if not user_id:
        return RedirectResponse(url="/login")
    if user_role not in ["admin", "gestor"]:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "financeiro.html", {"config": APP_CONFIG})

# --- ROTAS DE LICENCIAMENTO ---

@app.get("/ativar", response_class=HTMLResponse)
async def view_ativar(request: Request, error: str = None):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    if not user_id: return RedirectResponse(url="/login")
    if user_role != "admin": return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request=request,
        name="ativar.html",
        context={
            "hardware_id": license_service.get_hardware_id(),
            "error": error
        }
    )

@app.post("/ativar")
async def process_ativar(request: Request, token: str = Form(...)):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    if not user_id: return RedirectResponse(url="/login", status_code=303)
    if user_role != "admin": return RedirectResponse(url="/", status_code=303)
    if license_service.activate_token(token):
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/ativar?error=Token InvÃ¡lido ou jÃ¡ utilizado", status_code=303)

# --- OUTRAS TELAS MIGRADAS ---

@app.get("/impressoras", response_class=HTMLResponse)
async def view_impressoras(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    user_perms = request.cookies.get("user_perms") or "[]"
    if not user_id: return RedirectResponse(url="/login")
    try:
        perms = json.loads(user_perms)
    except:
        perms = []
    if user_role != "admin" and "Equipamentos" not in perms:
        return RedirectResponse(url="/")
    
    with Session(engine) as session:
        lista = session.exec(select(Impressora)).all()
        return templates.TemplateResponse(
            request=request,
            name="impressoras.html",
            context={
                "config": APP_CONFIG,
                "impressoras": lista
            }
        )

@app.get("/relatorios", response_class=HTMLResponse)
async def view_relatorios(request: Request, mes: Optional[str] = None, ano: Optional[str] = None, usuario: Optional[str] = None, impressora_id: Optional[str] = None, tipo: Optional[str] = None):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    user_perms = request.cookies.get("user_perms") or "[]"
    if not user_id: return RedirectResponse(url="/login")
    try:
        perms = json.loads(user_perms)
    except:
        perms = []
    if user_role != "admin" and "RelatÃ³rios" not in perms:
        return RedirectResponse(url="/")
    
    agora = datetime.now()
    mes = mes or agora.strftime("%m")
    ano = ano or agora.strftime("%Y")

    impressora_id_value = None
    if impressora_id:
        try:
            impressora_id_value = int(impressora_id)
        except (TypeError, ValueError):
            impressora_id_value = None
    
    with Session(engine) as session:
        # Filtro de data para o mÃªs selecionado
        start_date = datetime(int(ano), int(mes), 1)
        if int(mes) == 12:
            end_date = datetime(int(ano) + 1, 1, 1)
        else:
            end_date = datetime(int(ano), int(mes) + 1, 1)

        filtros = [Impressao.data_hora >= start_date, Impressao.data_hora < end_date]
        if usuario:
            filtros.append(Impressao.usuario == usuario)
        if impressora_id_value:
            filtros.append(Impressao.impressora_id == impressora_id_value)
        if tipo in ("Digital", "Fisica"):
            if tipo == "Digital":
                filtros.append(Impressao.tipo_impressao == "Digital")
            else:
                filtros.append(Impressao.tipo_impressao.in_(["Preto e Branco", "Colorida", "P&B", "Colorido"]))
        impressoras_filtro = session.exec(select(Impressora).order_by(Impressora.nome)).all()
        usuarios_filtro = session.exec(select(Impressao.usuario).distinct().order_by(Impressao.usuario)).all()

        # Resumo por Impressora
        stmt_imp = select(Impressora.nome, func.sum(Impressao.paginas), func.sum(Impressao.valor_total)).join(Impressao, Impressao.impressora_id == Impressora.id).where(*filtros).group_by(Impressora.nome).order_by(desc(func.sum(Impressao.paginas)))
        resumo_impressoras = session.exec(stmt_imp).all()
        
        # Resumo por UsuÃ¡rio
        stmt_usu = select(Impressao.usuario, func.sum(Impressao.paginas), func.sum(Impressao.valor_total)).where(*filtros).group_by(Impressao.usuario).order_by(desc(func.sum(Impressao.paginas)))
        resumo_usuarios = session.exec(stmt_usu).all()

        digital_pages = session.exec(
            select(func.sum(Impressao.paginas))
            .where(*filtros, Impressao.tipo_impressao == "Digital")
        ).one() or 0
        digital_jobs = session.exec(
            select(func.count(Impressao.id))
            .where(Impressao.tipo_impressao == "Digital")
            .where(*filtros)
        ).one() or 0
        physical_pages = session.exec(
            select(func.sum(Impressao.paginas))
            .where(*filtros, Impressao.tipo_impressao != "Digital")
        ).one() or 0
        physical_jobs = session.exec(
            select(func.count(Impressao.id))
            .where(Impressao.tipo_impressao != "Digital")
            .where(*filtros)
        ).one() or 0

        # EvoluÃ§Ã£o DiÃ¡ria (para o grÃ¡fico)
        stmt_evolu = select(func.date(Impressao.data_hora), func.sum(Impressao.paginas)).where(*filtros).group_by(func.date(Impressao.data_hora)).order_by(func.date(Impressao.data_hora))
        evolucao_diaria = session.exec(stmt_evolu).all()
        
        evolucao_fmt = []
        for e in evolucao_diaria:
            try:
                # e[0] Ã© uma string do SQLite date(), ex: "2026-05-11"
                d_obj = datetime.strptime(str(e[0]), "%Y-%m-%d")
                evolucao_fmt.append({"data": d_obj.strftime("%d/%m"), "paginas": int(e[1] or 0)})
            except:
                evolucao_fmt.append({"data": str(e[0]), "paginas": int(e[1] or 0)})

        # Auditoria Detalhada (200 registros)
        atividades_raw = session.exec(select(Impressao).where(*filtros).order_by(desc(Impressao.data_hora)).limit(200)).all()
        atividades_fmt = []
        for imp in atividades_raw:
            try:
                v = float(str(imp.valor_total).replace(",", ".")) if imp.valor_total else 0.0
            except:
                v = 0.0
                
            try:
                if isinstance(imp.data_hora, str):
                    dt = datetime.strptime(imp.data_hora[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                else:
                    dt = imp.data_hora
                d_str = dt.strftime('%d/%m/%Y %H:%M')
            except:
                d_str = "--/--"
                
            atividades_fmt.append({
                "data_hora_str": d_str,
                "tipo_documento": imp.tipo_documento,
                "documento": imp.documento,
                "usuario": imp.usuario,
                "paginas": imp.paginas,
                "valor_fmt": f"{v:.2f}".replace(".", ",")
            })

        equipamentos_ti = session.exec(
            select(EquipamentoTI).order_by(EquipamentoTI.colaborador, EquipamentoTI.id.desc())
        ).all()
        equipamentos_fmt = []
        for eq in equipamentos_ti:
            nome_computador = str(getattr(eq, "nome_computador", "") or "").strip()
            equipamentos_fmt.append({
                "id": eq.id,
                "colaborador": eq.colaborador,
                "nome_computador": nome_computador,
                "nome_computador_bruto": nome_computador,
                "nome_computador_display": nome_computador or "Não informado",
                "setor": eq.setor,
                "tipo_equipamento": eq.tipo_equipamento,
                "patrimonio": eq.patrimonio,
                "data_registro": eq.data_registro.strftime("%d/%m/%Y %H:%M") if eq.data_registro else "",
            })
        equipamentos_sem_nome = sum(
            1 for eq in equipamentos_ti if not str(getattr(eq, "nome_computador", "") or "").strip()
        )

        equipamentos_por_tipo = {}
        contagem_por_tipo = {}
        for eq in equipamentos_fmt:
            tipo_eq = (eq["tipo_equipamento"] or "Outros").strip()
            if tipo_eq not in equipamentos_por_tipo:
                equipamentos_por_tipo[tipo_eq] = []
                contagem_por_tipo[tipo_eq] = 0
            equipamentos_por_tipo[tipo_eq].append(eq)
            contagem_por_tipo[tipo_eq] += 1
        
        return templates.TemplateResponse(
            request=request,
            name="relatorios.html",
            context={
                "config": APP_CONFIG,
                "mes_atual": mes,
                "ano_atual": ano,
                "filtro_usuario": usuario or "",
                "filtro_impressora_id": impressora_id_value or "",
                "filtro_tipo": tipo or "",
                "usuarios_filtro": usuarios_filtro,
                "impressoras_filtro": impressoras_filtro,
                "resumo_impressoras": [{"nome": i[0] or "Local", "paginas": int(i[1] or 0), "valor": float(str(i[2] or 0).replace(",", "."))} for i in resumo_impressoras],
                "resumo_usuarios": [{"nome": u[0] or "Desconhecido", "paginas": int(u[1] or 0), "valor": float(str(u[2] or 0).replace(",", "."))} for u in resumo_usuarios],
                "resumo_fisico": {"trabalhos": int(physical_jobs), "paginas": int(physical_pages)},
                "resumo_digital": {"trabalhos": int(digital_jobs), "paginas": int(digital_pages), "valor": 0.0},
                "evolucao": evolucao_fmt,
                "atividades": atividades_fmt,
                "equipamentos_ti": equipamentos_fmt,
                "equipamentos_por_tipo": equipamentos_por_tipo,
                "contagem_por_tipo": contagem_por_tipo,
                "total_equipamentos_ti": len(equipamentos_ti),
                "equipamentos_sem_nome": equipamentos_sem_nome,
            }
        )

@app.get("/monitor_usuarios", response_class=HTMLResponse)
async def view_monitor_usuarios(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    user_perms = request.cookies.get("user_perms") or "[]"
    if not user_id: return RedirectResponse(url="/login")
    try:
        perms = json.loads(user_perms)
    except:
        perms = []
    if user_role != "admin" and "UsuÃ¡rios" not in perms:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request=request,
        name="monitor_usuarios.html",
        context={"config": APP_CONFIG}
    )

@app.get("/equipamentos_ti", response_class=HTMLResponse)
async def view_equipamentos_ti(request: Request):
    try:
        user_id = request.cookies.get("user_id")
        user_role = request.cookies.get("user_role")

        if not user_id:
            return RedirectResponse(url="/login")
        if user_role != "admin":
            return RedirectResponse(url="/")

        equipamentos = []
        equipamentos_sem_nome = 0
        equipamentos_fmt = []
        equipamentos_load_error = None

        try:
            with Session(engine) as session:
                equipamentos = session.exec(select(EquipamentoTI).order_by(EquipamentoTI.colaborador)).all()
                equipamentos_sem_nome = sum(
                    1 for eq in equipamentos if not str(getattr(eq, "nome_computador", "") or "").strip()
                )
                for eq in equipamentos:
                    nome_computador = str(getattr(eq, "nome_computador", "") or "").strip()
                    equipamentos_fmt.append({
                        "id": eq.id,
                        "colaborador": eq.colaborador,
                        "nome_computador": nome_computador,
                        "nome_computador_bruto": nome_computador,
                        "nome_computador_display": nome_computador or "Não informado",
                        "setor": eq.setor,
                        "tipo_equipamento": eq.tipo_equipamento,
                        "marca": eq.marca,
                        "modelo": eq.modelo,
                        "modelo_monitor": eq.modelo_monitor,
                        "quantidade_monitores": eq.quantidade_monitores,
                        "processador": eq.processador,
                        "memoria_ram": eq.memoria_ram,
                        "sistema_operacional": eq.sistema_operacional,
                        "armazenamento": eq.armazenamento,
                        "patrimonio": eq.patrimonio,
                        "observacoes": eq.observacoes,
                        "data_registro": eq.data_registro.strftime("%d/%m/%Y %H:%M") if eq.data_registro else "",
                    })
        except Exception as db_exc:
            print(f"[equipamentos_ti] Falha ao carregar equipamentos: {db_exc}")
            print(traceback.format_exc())
            equipamentos_load_error = "Nao foi possivel carregar os dados agora. A tela foi aberta sem os registros."

        render_context = {
            "request": request,
            "config": APP_CONFIG,
            "is_admin": True,
            "equipamentos": jsonable_encoder(equipamentos_fmt),
            "total_equipamentos_ti": len(equipamentos_fmt),
            "equipamentos_sem_nome": equipamentos_sem_nome,
            "equipamentos_load_error": equipamentos_load_error,
        }
        html = templates.get_template("equipamentos_ti.html").render(render_context)
        return HTMLResponse(content=html)
    except Exception:
        import traceback
        err = traceback.format_exc()
        print(f"CRITICAL ERROR IN VIEW_EQUIPAMENTOS_TI:\n{err}")
        return HTMLResponse(content=f"<h1>DEBUG ERROR</h1><pre>{err}</pre>", status_code=500)
@app.get("/marmitas", response_class=HTMLResponse)
async def view_marmitas(request: Request):
    return RedirectResponse(url="/")

@app.get("/usuarios", response_class=HTMLResponse)
async def view_usuarios(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    user_perms = request.cookies.get("user_perms") or "[]"
    if not user_id: return RedirectResponse(url="/login")
    try:
        perms = json.loads(user_perms)
    except:
        perms = []
    if user_role != "admin" and "UsuÃ¡rios" not in perms:
        return RedirectResponse(url="/")
    with Session(engine) as session:
        users = session.exec(select(Usuario).order_by(Usuario.created_at.desc())).all()
        lista_usuarios = []
        for u in users:
            d = u.dict()
            d["created_at"] = d["created_at"].strftime("%Y-%m-%d %H:%M:%S") if d["created_at"] else None
            # Pre-processa as permissÃµes para evitar erro no template
            try:
                d["permissoes_list"] = json.loads(d.get("permissoes", "[]"))
            except:
                d["permissoes_list"] = []
            lista_usuarios.append(d)
            
        return templates.TemplateResponse(
            request=request,
            name="usuarios.html",
            context={
                "config": APP_CONFIG,
                "usuarios": lista_usuarios
            }
        )

@app.get("/cofre", response_class=HTMLResponse)
async def view_cofre(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = get_signed_cookie(request, "user_role")
    if not user_id:
        return RedirectResponse(url="/login")
    if user_role != "admin":
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request=request,
        name="cofre_senhas.html",
        context={
            "config": APP_CONFIG
        }
    )

@app.get("/configuracoes", response_class=HTMLResponse)
async def view_configuracoes(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    user_perms = request.cookies.get("user_perms") or "[]"
    if not user_id: return RedirectResponse(url="/login")
    try:
        perms = json.loads(user_perms)
    except:
        perms = []
    if user_role != "admin" and "Ajustes" not in perms:
        return RedirectResponse(url="/")
    # Recarregar config para ter dados frescos
    fresh_config = load_app_config()
    return templates.TemplateResponse(
        request=request,
        name="configuracoes.html",
        context={"config": fresh_config, "message": "", "tipo_msg": ""}
    )

@app.post("/configuracoes", response_class=HTMLResponse)
async def save_configuracoes(
    request: Request,
    app_name: str = Form("PrintDash"),
    app_tagline: str = Form(""),
    app_color: str = Form("#6366f1"),
    app_price_bw: str = Form("0.50"),
    app_price_color: str = Form("1.00"),
    url_atendimento: str = Form(""),
    guia_suporte_url: str = Form(""),
    app_logo_url: str = Form(""),
    mod_impressao: Optional[str] = Form(None),
    mod_suporte: Optional[str] = Form(None),
    mod_atendimento: Optional[str] = Form(None),
    whatsapp_webhook_url: str = Form(""),
    whatsapp_webhook_token: str = Form(""),
    app_logo_upload: Optional[UploadFile] = File(None),
    guia_suporte_upload: Optional[UploadFile] = File(None)
):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    user_perms = request.cookies.get("user_perms") or "[]"
    if not user_id: return RedirectResponse(url="/login")
    try:
        perms = json.loads(user_perms)
    except:
        perms = []
    if user_role != "admin" and "Ajustes" not in perms:
        return RedirectResponse(url="/")
    
    import shutil
    message = ""
    tipo_msg = ""
    
    try:
        price_bw = float(str(app_price_bw).replace(",", "."))
        price_color = float(str(app_price_color).replace(",", "."))
        logo = app_logo_url
        guia_url = guia_suporte_url
        
        upload_dir = "public_html/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        
        # Upload de Logo
        if app_logo_upload and app_logo_upload.filename:
            ext = app_logo_upload.filename.split(".")[-1].lower()
            if ext in ["png", "jpg", "jpeg", "gif", "svg", "webp"]:
                new_name = f"logo_customizada.{ext}"
                file_path = os.path.join(upload_dir, new_name)
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(app_logo_upload.file, buffer)
                logo = f"uploads/{new_name}?v={int(datetime.now().timestamp())}"
        
        # Upload de Guia
        if guia_suporte_upload and guia_suporte_upload.filename:
            ext = guia_suporte_upload.filename.split(".")[-1].lower()
            if ext in ["pdf", "doc", "docx", "txt", "jpg", "png"]:
                new_name = f"guia_suporte_usuario.{ext}"
                file_path = os.path.join(upload_dir, new_name)
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(guia_suporte_upload.file, buffer)
                guia_url = f"uploads/{new_name}"
        
        new_config = {
            "APP_NAME": app_name,
            "APP_TAGLINE": app_tagline,
            "APP_LOGO_URL": logo,
            "APP_COLOR": app_color,
            "APP_PRICE_BW": price_bw,
            "APP_PRICE_COLOR": price_color,
            "MODULO_IMPRESSAO": mod_impressao is not None,
            "MODULO_SUPORTE": mod_suporte is not None,
            "MODULO_ATENDIMENTO": mod_atendimento is not None,
            "URL_ATENDIMENTO": url_atendimento,
            "GUIA_SUPORTE_URL": guia_url,
            "WHATSAPP_WEBHOOK_URL": whatsapp_webhook_url,
            "WHATSAPP_WEBHOOK_TOKEN": whatsapp_webhook_token
        }
        
        config_path = "public_html/includes/config.json"
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(new_config, f, indent=4)
        
        # Atualizar config global
        global APP_CONFIG
        APP_CONFIG = new_config
        
        message = "ConfiguraÃ§Ãµes atualizadas!"
        tipo_msg = "success"
    except Exception as e:
        message = f"Erro ao salvar: {str(e)}"
        tipo_msg = "error"
    
    fresh_config = load_app_config()
    return templates.TemplateResponse(
        request=request,
        name="configuracoes.html",
        context={"config": fresh_config, "message": message, "tipo_msg": tipo_msg}
    )



@app.get("/meu_painel", response_class=HTMLResponse)
async def view_meu_painel(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")
        
    with Session(engine) as session:
        user = session.get(Usuario, int(user_id))
        if not user:
            return RedirectResponse(url="/login")
            
        agora = datetime.now()
        
        # MÃªs atual
        inicio_mes = datetime(agora.year, agora.month, 1)
        if agora.month == 12:
            fim_mes = datetime(agora.year + 1, 1, 1)
        else:
            fim_mes = datetime(agora.year, agora.month + 1, 1)
            
        # MÃªs anterior
        if agora.month == 1:
            inicio_mes_ant = datetime(agora.year - 1, 12, 1)
            fim_mes_ant = datetime(agora.year, 1, 1)
        else:
            inicio_mes_ant = datetime(agora.year, agora.month - 1, 1)
            fim_mes_ant = inicio_mes

        # Dados do usuÃ¡rio no mÃªs atual
        paginas_mes = session.exec(
            select(func.sum(Impressao.paginas))
            .where(Impressao.usuario == user.username)
            .where(Impressao.data_hora >= inicio_mes, Impressao.data_hora < fim_mes)
        ).one() or 0
        
        custo_mes = session.exec(
            select(func.sum(Impressao.valor_total))
            .where(Impressao.usuario == user.username)
            .where(Impressao.data_hora >= inicio_mes, Impressao.data_hora < fim_mes)
        ).one() or 0
        
        jobs_mes = session.exec(
            select(func.count(Impressao.id))
            .where(Impressao.usuario == user.username)
            .where(Impressao.data_hora >= inicio_mes, Impressao.data_hora < fim_mes)
        ).one() or 0

        # Dados do mÃªs anterior
        custo_mes_ant = session.exec(
            select(func.sum(Impressao.valor_total))
            .where(Impressao.usuario == user.username)
            .where(Impressao.data_hora >= inicio_mes_ant, Impressao.data_hora < fim_mes_ant)
        ).one() or 0
        
        # VariaÃ§Ã£o em %
        c_mes = float(custo_mes)
        c_ant = float(custo_mes_ant)
        if c_ant > 0:
            variacao_custo = ((c_mes - c_ant) / c_ant) * 100
        elif c_mes > 0:
            variacao_custo = 100.0
        else:
            variacao_custo = 0.0

        # Chamados recentes do usuÃ¡rio
        chamados_raw = session.exec(
            select(Chamado)
            .where(Chamado.usuario == user.username)
            .order_by(desc(Chamado.data_abertura))
            .limit(5)
        ).all()
        chamados = []
        for c in chamados_raw:
            d = c.dict()
            d["created_at"] = d.get("data_abertura")
            chamados.append(d)
        
        stats = {
            "paginas_mes": int(paginas_mes),
            "custo_mes": c_mes,
            "jobs_mes": int(jobs_mes),
            "variacao_custo": variacao_custo
        }

        return templates.TemplateResponse(
            request=request,
            name="meu_painel.html",
            context={
                "config": APP_CONFIG,
                "current_user": user,
                "stats": stats,
                "chamados": chamados
            }
        )

@app.get("/executivo", response_class=HTMLResponse)

async def view_executivo(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    if not user_id:
        return RedirectResponse(url="/login")
    if user_role not in ("admin", "gestor"):
        return RedirectResponse(url="/")

    with Session(engine) as session:
        agora = datetime.now()
        hoje = agora.date()

        # --- MÃŠS ATUAL ---
        inicio_mes = datetime(agora.year, agora.month, 1)
        if agora.month == 12:
            fim_mes = datetime(agora.year + 1, 1, 1)
        else:
            fim_mes = datetime(agora.year, agora.month + 1, 1)

        paginas_mes = session.exec(
            select(func.sum(Impressao.paginas)).where(
                Impressao.data_hora >= inicio_mes, Impressao.data_hora < fim_mes
            )
        ).one() or 0
        custo_mes = session.exec(
            select(func.sum(Impressao.valor_total)).where(
                Impressao.data_hora >= inicio_mes, Impressao.data_hora < fim_mes
            )
        ).one() or 0
        custo_mes = float(custo_mes)

        # --- PROJEÃ‡ÃƒO ATÃ‰ FIM DO MÃŠS ---
        dia_atual = agora.day
        total_dias_mes = (fim_mes - inicio_mes).days
        custo_projetado = (custo_mes / dia_atual * total_dias_mes) if dia_atual > 0 else 0
        progresso_mes = round(dia_atual / total_dias_mes * 100)

        # --- MÃŠS ANTERIOR ---
        if agora.month == 1:
            inicio_mes_ant = datetime(agora.year - 1, 12, 1)
            fim_mes_ant = datetime(agora.year, 1, 1)
        else:
            inicio_mes_ant = datetime(agora.year, agora.month - 1, 1)
            fim_mes_ant = inicio_mes

        custo_mes_ant = session.exec(
            select(func.sum(Impressao.valor_total)).where(
                Impressao.data_hora >= inicio_mes_ant, Impressao.data_hora < fim_mes_ant
            )
        ).one() or 0
        custo_mes_ant = float(custo_mes_ant)

        paginas_mes_ant = session.exec(
            select(func.sum(Impressao.paginas)).where(
                Impressao.data_hora >= inicio_mes_ant, Impressao.data_hora < fim_mes_ant
            )
        ).one() or 0

        # --- VARIAÃ‡ÃƒO % ---
        if custo_mes_ant > 0:
            variacao_pct = round((custo_projetado - custo_mes_ant) / custo_mes_ant * 100, 1)
        else:
            variacao_pct = 0

        # --- TOTAL GERAL HISTÃ“RICO ---
        custo_total = float(session.exec(select(func.sum(Impressao.valor_total))).one() or 0)
        paginas_total = int(session.exec(select(func.sum(Impressao.paginas))).one() or 0)

        # --- TOP 8 USUÃRIOS DO MÃŠS ---
        top_usuarios_raw = session.exec(
            select(
                Impressao.usuario,
                func.sum(Impressao.paginas).label("paginas"),
                func.sum(Impressao.valor_total).label("custo"),
                func.count(Impressao.id).label("jobs")
            )
            .where(Impressao.data_hora >= inicio_mes, Impressao.data_hora < fim_mes)
            .group_by(Impressao.usuario)
            .order_by(func.sum(Impressao.valor_total).desc())
            .limit(8)
        ).all()
        top_usuarios = [
            {"nome": r[0] or "Desconhecido", "paginas": int(r[1] or 0),
             "custo": float(r[2] or 0), "jobs": int(r[3] or 0)}
            for r in top_usuarios_raw
        ]

        # --- EVOLUÃ‡ÃƒO DIÃRIA (Ãºltimos 30 dias) ---
        inicio_30 = agora - timedelta(days=30)
        evol_raw = session.exec(
            select(
                func.date(Impressao.data_hora).label("dia"),
                func.sum(Impressao.valor_total).label("custo")
            )
            .where(Impressao.data_hora >= inicio_30)
            .group_by(func.date(Impressao.data_hora))
            .order_by(func.date(Impressao.data_hora))
        ).all()
        evolucao = []
        for row in evol_raw:
            try:
                d = datetime.strptime(str(row[0]), "%Y-%m-%d")
                evolucao.append({"dia": d.strftime("%d/%m"), "custo": round(float(row[1] or 0), 2)})
            except:
                pass

        # --- RANKING POR TIPO DE IMPRESSÃƒO ---
        tipo_raw = session.exec(
            select(
                Impressao.tipo_impressao,
                func.sum(Impressao.paginas).label("paginas"),
                func.sum(Impressao.valor_total).label("custo")
            )
            .where(Impressao.data_hora >= inicio_mes, Impressao.data_hora < fim_mes)
            .group_by(Impressao.tipo_impressao)
        ).all()
        por_tipo = [
            {"tipo": r[0] or "Outro", "paginas": int(r[1] or 0), "custo": float(r[2] or 0)}
            for r in tipo_raw
        ]

        # --- NOME DO MÃŠS ATUAL E ANTERIOR ---
        MESES_PT = ["Janeiro","Fevereiro","MarÃ§o","Abril","Maio","Junho",
                    "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
        nome_mes = MESES_PT[agora.month - 1]
        nome_mes_ant = MESES_PT[inicio_mes_ant.month - 1]

        return templates.TemplateResponse(
            request=request,
            name="executivo.html",
            context={
                "config": APP_CONFIG,
                "nome_mes": nome_mes,
                "nome_mes_ant": nome_mes_ant,
                "ano": agora.year,
                "custo_mes": custo_mes,
                "paginas_mes": int(paginas_mes),
                "custo_projetado": round(custo_projetado, 2),
                "custo_mes_ant": custo_mes_ant,
                "paginas_mes_ant": int(paginas_mes_ant),
                "variacao_pct": variacao_pct,
                "progresso_mes": progresso_mes,
                "custo_total": custo_total,
                "paginas_total": paginas_total,
                "top_usuarios": top_usuarios,
                "evolucao": evolucao,
                "por_tipo": por_tipo,
                "hoje": hoje.strftime("%d/%m/%Y"),
            }
        )


@app.get("/login", response_class=HTMLResponse)
async def view_login(request: Request, intent: str = "suporte"):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"config": APP_CONFIG, "intent": intent, "only_atendimento": False}
    )

@app.get("/atendimento/login", response_class=HTMLResponse)
async def view_atendimento_login(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="atendimento_login.html",
        context={"config": APP_CONFIG}
    )

def _can_access_atendimento(request: Request) -> bool:
    """Permite a Central de Atendimento a administradores ou usuários autorizados."""
    if get_signed_cookie(request, "user_role") == "admin":
        return True
    try:
        raw_perms = get_signed_cookie(request, "user_perms", "[]") or "[]"
        perms = normalize_permissions(json.loads(raw_perms))
        return "Atendimento" in perms or "Suporte" in perms
    except Exception:
        return False


@app.get("/central-atendimento", response_class=HTMLResponse)
async def view_central_atendimento(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    user_name = request.cookies.get("user_name")

    config = load_app_config()
    if not config.get("MODULO_ATENDIMENTO", False):
        return RedirectResponse(url="/")

    if not user_id:
        return templates.TemplateResponse(
            request=request,
            name="atendimento_login.html",
            context={"config": config},
        )

    has_access = _can_access_atendimento(request)

    return templates.TemplateResponse(
        request=request,
        name="atendimento_whatsapp.html",
        context={
            "config": config,
            "is_admin": user_role == "admin",
            "user_role": user_role,
            "can_manage_atendimento": user_role in ("admin", "gestor", "gerente", "supervisor", "recepcao", "recepção", "recepcionista"),
            "user_name": user_name,
            "authenticated": True,
            "has_access": has_access,
        }
    )

@app.get("/atendimento")
async def redirect_atendimento():
    return RedirectResponse(url="/central-atendimento")

@app.get("/central-atendimento/contatos", response_class=HTMLResponse)
async def view_whatsapp_contacts(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    if not user_id:
        return RedirectResponse(url="/login")
    if user_role not in ("admin", "operator"):
        return RedirectResponse(url="/central-atendimento")
    return templates.TemplateResponse(
        request=request,
        name="whatsapp_contacts.html",
        context={
            "config": load_app_config(),
            "is_admin": user_role == "admin",
            "authenticated": True,
            "user_name": request.cookies.get("user_name", ""),
        },
    )

@app.get("/central-atendimento/configuracoes", response_class=HTMLResponse)
async def view_whatsapp_config(request: Request):
    user_id = request.cookies.get("user_id")
    user_role = request.cookies.get("user_role")
    if not user_id:
        return RedirectResponse(url="/login")

    if user_role != "admin":
        return RedirectResponse(url="/central-atendimento")

    config = load_app_config()
    return templates.TemplateResponse(
        request=request,
        name="whatsapp_config.html",
        context={
            "config": config,
            "is_admin": user_role == "admin",
            "authenticated": True,
            "user_name": request.cookies.get("user_name", ""),
        }
    )

@app.get("/central-atendimento/grupos", response_class=HTMLResponse)
async def view_whatsapp_groups(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")
    config = load_app_config()
    groups = []
    with Session(engine) as session:
        chamados = session.exec(select(Chamado).where(Chamado.origem == "WhatsApp", Chamado.whatsapp_cliente.like("%@g.us")).order_by(desc(Chamado.data_abertura))).all()
        seen = set()
        for chamado in chamados:
            if chamado.whatsapp_cliente in seen:
                continue
            seen.add(chamado.whatsapp_cliente)
            groups.append({"name": chamado.usuario or "Grupo WhatsApp", "jid": chamado.whatsapp_cliente, "last_activity": chamado.data_abertura.strftime("%d/%m/%Y %H:%M")})
    return templates.TemplateResponse(request=request, name="whatsapp_groups.html", context={"config": config, "groups": groups, "authenticated": True, "user_name": request.cookies.get("user_name", "")})

@app.get("/whatsapp_config")
async def redirect_whatsapp_config():
    return RedirectResponse(url="/central-atendimento/configuracoes")
