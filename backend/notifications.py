import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER") # Numero destino

def get_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def send_alert(message: str) -> bool:
    """
    Envia uma mensagem de alerta via Telegram e/ou WhatsApp.
    Retorna True se sucesso, False caso contrário.
    """
    sucesso = False

    # 1. Enviar pelo Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 200:
                sucesso = True
            else:
                print(f"[Notifications] Falha no Telegram. HTTP {resp.status_code}")
        except Exception as e:
            print(f"[Notifications] Erro Telegram: {e}")

    # 2. Enviar pelo WhatsApp (via webhook config)
    config = get_config()
    wa_url = config.get("WHATSAPP_WEBHOOK_URL", "")
    wa_token = config.get("WHATSAPP_WEBHOOK_TOKEN", "")

    if wa_url and WHATSAPP_NUMBER:
        # Tenta formatar a mensagem para a Evolution API (padrão mais usado)
        # Adaptar o payload conforme a documentação da API real se for diferente.
        headers = {}
        if wa_token:
            headers["apikey"] = wa_token
            headers["Authorization"] = f"Bearer {wa_token}"

        # Remover tags HTML para o WhatsApp (já que ele usa *negrito* ou texto plano)
        msg_limpa = message.replace("<b>", "*").replace("</b>", "*")
        msg_limpa = msg_limpa.replace("<i>", "_").replace("</i>", "_")

        payload_wa = {
            "number": WHATSAPP_NUMBER,
            "options": {
                "delay": 1200,
                "presence": "composing"
            },
            "textMessage": {
                "text": msg_limpa
            }
        }
        
        # Fallback genérico caso a API espere apenas number e text ou message
        payload_wa_generic = {
            "number": WHATSAPP_NUMBER,
            "text": msg_limpa,
            "message": msg_limpa
        }

        try:
            # Envia o padrão (Evolution API / Z-API etc)
            resp = requests.post(wa_url, json=payload_wa_generic, headers=headers, timeout=5)
            if resp.status_code in [200, 201]:
                sucesso = True
            else:
                print(f"[Notifications] Falha WhatsApp genérico. HTTP {resp.status_code}")
                # Tenta o payload estruturado (Evolution API textMessage)
                requests.post(wa_url, json=payload_wa, headers=headers, timeout=5)
        except Exception as e:
            print(f"[Notifications] Erro WhatsApp: {e}")

    return sucesso
