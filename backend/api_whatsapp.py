import os
import json
import time
import requests
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from sqlmodel import Session, select, desc

from models import Chamado, ChamadoInteracao
from database import engine
from auth_utils import get_signed_cookie
from websocket_manager import manager

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

# Caminho absoluto relativo ao diretório do script — garante leitura do config correto
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_BASE_DIR, "public_html", "includes", "config.json")

# ─── Helpers para Configuração e Integração com Evolution API ────────────────

def get_whatsapp_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            print(f"[api_whatsapp] Erro ao ler config.json: {e}")
    return {}


def get_evolution_api_endpoints():
    config = get_whatsapp_config()
    wa_url = config.get("WHATSAPP_WEBHOOK_URL", "")
    wa_token = config.get("WHATSAPP_WEBHOOK_TOKEN", "")
    
    if not wa_url:
        return None, None, None
        
    instance = "printdash"
    base_url = wa_url.rstrip("/")
    
    # Se configurou a URL de envio direto, extrai a URL base e a instância
    if "/message/sendText/" in base_url:
        parts = base_url.split("/message/sendText/")
        base_url = parts[0]
        if len(parts) > 1 and parts[1]:
            instance = parts[1].split("?")[0]
            
    return base_url, wa_token, instance


def send_whatsapp_text(number: str, text: str) -> bool:
    base_url, wa_token, instance = get_evolution_api_endpoints()
    if not base_url:
        print("[WhatsApp API] URL da API não configurada.")
        return False
        
    url = f"{base_url}/message/sendText/{instance}"
    headers = {"Content-Type": "application/json"}
    if wa_token:
        headers["apikey"] = wa_token
        
    payload = {
        "number": number,
        "text": text,
        "delay": 1200
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=8)
        if resp.status_code in [200, 201]:
            print(f"[WhatsApp API] Mensagem enviada para {number}")
            return True
        else:
            print(f"[WhatsApp API] Erro ao enviar: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"[WhatsApp API] Erro ao conectar com Evolution API: {e}")
        return False


def _get_user(request: Request):
    name = get_signed_cookie(request, "user_name", "Desconhecido")
    role = get_signed_cookie(request, "user_role", "operator")
    return name, role


# ─── Endpoints de Estado e QR Code ───────────────────────────────────────────

@router.get("/status")
def get_whatsapp_status(request: Request):
    base_url, wa_token, instance = get_evolution_api_endpoints()
    if not base_url:
        return {"status": "unconfigured", "message": "Evolution API não configurada em Configurações."}
        
    url = f"{base_url}/instance/connectionState/{instance}"
    headers = {}
    if wa_token:
        headers["apikey"] = wa_token
        
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Evolution API pode retornar {"instance": {"state": "open"}} ou {"state": "open"}
            state = data.get("instance", {}).get("state") or data.get("state", "disconnected")
            return {"status": "configured", "state": state}
        elif resp.status_code in [404, 400]:
            # Instância não existe — cria automaticamente
            _create_instance(base_url, wa_token, instance)
            return {"status": "configured", "state": "disconnected"}
        else:
            return {"status": "error", "message": f"Evolution API respondeu status {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"status": "error", "message": f"Falha de conexão com a API: {str(e)}"}


def _create_instance(base_url: str, wa_token: str, instance: str):
    """Cria a instância na Evolution API se ela não existir e configura o webhook de retorno."""
    create_url = f"{base_url}/instance/create"
    payload = {
        "instanceName": instance,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
        # Webhook para receber mensagens de volta no nosso sistema
        "webhook": {
            "url": "http://web:8000/api/whatsapp/webhook",
            "byEvents": False,
            "base64": False,
            "events": [
                "MESSAGES_UPSERT",
                "MESSAGES_UPDATE",
                "CONNECTION_UPDATE"
            ]
        }
    }
    # Só inclui o token se não for vazio
    if wa_token:
        payload["token"] = wa_token

    c_headers = {"Content-Type": "application/json"}
    if wa_token:
        c_headers["apikey"] = wa_token

    try:
        resp = requests.post(create_url, json=payload, headers=c_headers, timeout=8)
        print(f"[WhatsApp] Instância '{instance}' criada: {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        print(f"[WhatsApp] Aviso ao criar instância: {e}")



@router.get("/qrcode")
def get_whatsapp_qrcode(request: Request):
    """
    Garante que a instância existe e busca o QR Code para autenticação.
    Caso a instância não exista, cria-a antes de buscar o QR.
    """
    base_url, wa_token, instance = get_evolution_api_endpoints()
    if not base_url:
        raise HTTPException(status_code=400, detail="Evolution API não configurada.")

    headers = {}
    if wa_token:
        headers["apikey"] = wa_token

    # 1. Verifica se a instância existe — se não, cria
    state_url = f"{base_url}/instance/connectionState/{instance}"
    try:
        state_resp = requests.get(state_url, headers=headers, timeout=5)
        if state_resp.status_code in [404, 400]:
            print(f"[WhatsApp] Instância '{instance}' não existe. Criando...")
            _create_instance(base_url, wa_token, instance)
            # Aguarda um instante para a instância inicializar
            time.sleep(1)
    except Exception as e:
        print(f"[WhatsApp] Aviso ao verificar instância: {e}")

    # 2. Busca o QR Code via /instance/connect/{instance}
    url = f"{base_url}/instance/connect/{instance}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            # Evolution API retorna {"code": "...", "base64": "data:image/png;base64,..."}
            data = resp.json()
            if not data.get("base64") and not data.get("code"):
                raise HTTPException(status_code=502, detail="Evolution API retornou resposta vazia para o QR Code. A instância pode já estar conectada.")
            return data
        elif resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Instância não encontrada na Evolution API. Verifique a URL configurada.")
        else:
            raise HTTPException(status_code=resp.status_code, detail=f"Erro Evolution: {resp.text[:300]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha de rede com Evolution API: {str(e)}")


@router.post("/disconnect")
def disconnect_whatsapp(request: Request):
    _, user_role = _get_user(request)
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado")
        
    base_url, wa_token, instance = get_evolution_api_endpoints()
    if not base_url:
        raise HTTPException(status_code=400, detail="Evolution API não configurada.")
        
    url = f"{base_url}/instance/logout/{instance}"
    headers = {}
    if wa_token:
        headers["apikey"] = wa_token
        
    try:
        resp = requests.post(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            return {"success": True}
        else:
            raise HTTPException(status_code=resp.status_code, detail=f"Erro Evolution: {resp.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha de conexão: {str(e)}")


# ─── Listagem de Chats (com regras de permissão) ───────────────────────────

@router.get("/chats")
def get_whatsapp_chats(request: Request):
    user_name, user_role = _get_user(request)
    
    with Session(engine) as session:
        # Query base para chamados vindos do WhatsApp
        stmt = select(Chamado).where(Chamado.origem == "WhatsApp")
        
        # Filtro de visibilidade baseado em privilégio
        if user_role != "admin":
            # Operador: Vê chamados não atribuídos OU atribuídos a ele mesmo
            stmt = stmt.where(
                (Chamado.assigned_user == user_name) | 
                ((Chamado.assigned_user == None) & (Chamado.status != "Resolvido"))
            )
            
        stmt = stmt.order_by(desc(Chamado.data_abertura))
        chamados = session.exec(stmt).all()
        
        resultado = []
        for c in chamados:
            # Busca a última mensagem do chamado
            last_msg_stmt = select(ChamadoInteracao).where(
                ChamadoInteracao.chamado_id == c.id
            ).order_by(desc(ChamadoInteracao.data_hora)).limit(1)
            
            last_msg = session.exec(last_msg_stmt).first()
            
            resultado.append({
                "id": c.id,
                "usuario": c.usuario,
                "whatsapp_cliente": c.whatsapp_cliente,
                "status": c.status,
                "prioridade": c.prioridade,
                "assigned_user": c.assigned_user,
                "unread_admin": c.unread_admin if user_role == "admin" else (c.unread_admin if c.assigned_user == user_name else 0),
                "data_abertura": c.data_abertura.strftime("%d/%m/%Y %H:%M"),
                "ultima_mensagem": last_msg.mensagem if last_msg else c.descricao,
                "data_ultima_mensagem": (last_msg.data_hora if last_msg else c.data_abertura).strftime("%d/%m %H:%M")
            })
            
        return resultado


@router.post("/assumir/{ticket_id}")
def assumir_chat(ticket_id: int, request: Request, background_tasks: BackgroundTasks):
    user_name, _ = _get_user(request)
    
    with Session(engine) as session:
        chamado = session.get(Chamado, ticket_id)
        if not chamado:
            raise HTTPException(status_code=404, detail="Chamado não encontrado")
            
        if chamado.origem != "WhatsApp":
            raise HTTPException(status_code=400, detail="Este chamado não é de origem WhatsApp")
            
        # Atribui o chamado ao operador logado e atualiza status se estiver em Aberto
        chamado.assigned_user = user_name
        if chamado.status == "Aberto":
            chamado.status = "Em Atendimento"
            
        session.commit()
        
        # Envia mensagem automática para o WhatsApp avisando quem assumiu
        if chamado.whatsapp_cliente:
            msg_wa = f"Seu atendimento foi iniciado. Você está conversando com o(a) atendente *{user_name}*."
            background_tasks.add_task(send_whatsapp_text, chamado.whatsapp_cliente, msg_wa)
        
        # Avisa todos via WebSocket sobre a alteração de atribuição
        background_tasks.add_task(
            manager.broadcast,
            {
                "event": "whatsapp_chat_assigned",
                "ticket_id": ticket_id,
                "assigned_user": user_name,
                "status": chamado.status
            }
        )
        return {"success": True, "assigned_user": user_name}


# ─── Webhook Receptor de Mensagens da Evolution API ──────────────────────────

@router.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "detail": "Corpo da requisição não é um JSON válido."}

    event = (payload.get("event") or "").lower().replace("_", ".").replace("-", ".")
    print(f"[Webhook] Evento recebido: '{event}' | Payload keys: {list(payload.keys())}")

    if event != "messages.upsert":
        return {"status": "ignored", "reason": f"evento nao mapeado: {event}"}

    # A Evolution API v2 pode enviar data como objeto único OU como lista de mensagens
    raw_data = payload.get("data", {})
    if isinstance(raw_data, list):
        messages_list = raw_data
    else:
        messages_list = [raw_data]

    last_ticket_id = None

    for data in messages_list:
        key = data.get("key", {})
        from_me = key.get("fromMe", False)

        # Ignora mensagens enviadas pelo próprio número para evitar loops
        if from_me:
            print(f"[Webhook] Mensagem própria ignorada (fromMe=True)")
            continue

        remote_jid = key.get("remoteJid", "")
        print(f"[Webhook] remoteJid recebido: {remote_jid}")

        # Aceita qualquer número pessoal — exclui apenas grupos (@g.us)
        if not remote_jid or remote_jid.endswith("@g.us"):
            print(f"[Webhook] JID ignorado (grupo ou vazio): {remote_jid}")
            continue

        # Extrai o número limpo
        if remote_jid.endswith("@lid"):
            phone_number = remote_jid
        else:
            phone_number = remote_jid.split("@")[0]
            # Remove o sufixo :XX que aparece em alguns JIDs de dispositivos múltiplos
            phone_number = phone_number.split(":")[0]

        customer_name = data.get("pushName") or phone_number

        # Extrai o texto de acordo com o tipo da mensagem (Baileys/Evolution v2)
        message_obj = data.get("message", {})
        msg_text = ""
        if "conversation" in message_obj:
            msg_text = message_obj["conversation"]
        elif "extendedTextMessage" in message_obj:
            msg_text = message_obj["extendedTextMessage"].get("text", "")
        elif "imageMessage" in message_obj:
            caption = message_obj["imageMessage"].get("caption", "")
            msg_text = f"[Foto]{': ' + caption if caption else ''}"
        elif "videoMessage" in message_obj:
            caption = message_obj["videoMessage"].get("caption", "")
            msg_text = f"[Vídeo]{': ' + caption if caption else ''}"
        elif "documentMessage" in message_obj:
            fname = message_obj["documentMessage"].get("fileName", "")
            msg_text = f"[Documento]{': ' + fname if fname else ''}"
        elif "audioMessage" in message_obj:
            msg_text = "[Áudio]"
        elif "stickerMessage" in message_obj:
            msg_text = "[Sticker]"
        elif "locationMessage" in message_obj:
            msg_text = "[Localização]"
        elif "contactMessage" in message_obj:
            msg_text = "[Contato]"
        elif "reactionMessage" in message_obj:
            # Reações não criam chamado
            print(f"[Webhook] Reação ignorada de {phone_number}")
            continue
        else:
            # Tipo desconhecido — loga para diagnóstico mas cria registro
            print(f"[Webhook] Tipo de mensagem desconhecido: {list(message_obj.keys())}")
            msg_text = "[Mensagem]"

        if not msg_text:
            msg_text = "[Mensagem]"

        print(f"[Webhook] Processando: {customer_name} ({phone_number}) -> '{msg_text}'")

        with Session(engine) as session:
            # Procura chamado ativo (não resolvido) com esse número
            stmt = select(Chamado).where(
                Chamado.whatsapp_cliente == phone_number,
                Chamado.status != "Resolvido"
            ).order_by(desc(Chamado.data_abertura))

            chamado = session.exec(stmt).first()

            if chamado:
                # Chamado ativo: adiciona interação
                interacao = ChamadoInteracao(
                    chamado_id=chamado.id,
                    usuario=customer_name,
                    mensagem=msg_text,
                    data_hora=datetime.now()
                )
                session.add(interacao)
                chamado.unread_admin = (chamado.unread_admin or 0) + 1
                session.commit()
                session.refresh(interacao)
                ticket_id = chamado.id
                print(f"[Webhook] Mensagem adicionada ao chamado #{ticket_id}")

                background_tasks.add_task(
                    manager.broadcast,
                    {
                        "event": "new_whatsapp_message",
                        "ticket_id": ticket_id,
                        "msg_id": interacao.id,
                        "usuario": customer_name,
                        "mensagem": msg_text,
                        "data_hora": interacao.data_hora.strftime("%d/%m/%Y %H:%M:%S")
                    }
                )
            else:
                # Abre novo chamado
                chamado = Chamado(
                    usuario=customer_name,
                    titulo="Atendimento WhatsApp",
                    categoria="WhatsApp",
                    descricao=msg_text,
                    origem="WhatsApp",
                    whatsapp_cliente=phone_number,
                    status="Aberto",
                    prioridade="Media",
                    unread_admin=1
                )
                session.add(chamado)
                session.commit()
                session.refresh(chamado)
                ticket_id = chamado.id
                print(f"[Webhook] Novo chamado criado: #{ticket_id} para {customer_name}")

                interacao = ChamadoInteracao(
                    chamado_id=ticket_id,
                    usuario=customer_name,
                    mensagem=msg_text,
                    data_hora=datetime.now()
                )
                session.add(interacao)
                session.commit()

                background_tasks.add_task(
                    manager.broadcast,
                    {
                        "event": "new_whatsapp_chat",
                        "ticket_id": ticket_id,
                        "usuario": customer_name,
                        "mensagem": msg_text,
                        "prioridade": chamado.prioridade,
                        "data_hora": chamado.data_abertura.strftime("%d/%m/%Y %H:%M:%S")
                    }
                )

                # Auto-resposta de boas-vindas
                welcome_msg = f"Olá, {customer_name}! Seu atendimento foi registrado sob o chamado #{ticket_id}. Um de nossos operadores irá atendê-lo em breve."
                background_tasks.add_task(send_whatsapp_text, phone_number, welcome_msg)

            last_ticket_id = ticket_id

    return {"status": "success", "ticket_id": last_ticket_id}
