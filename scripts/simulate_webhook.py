"""
Simula um webhook da Evolution API para testes locais.
Uso:
  python simulate_webhook.py --instance minha_instancia1 --phone 5511999999999 --name "Teste" --text "Olá"
"""
import argparse
import json
import requests

def simulate(instance, phone, name, text, url):
    payload = {
        "event": "messages.upsert",
        "instance": instance,
        "data": [
            {
                "key": {
                    "remoteJid": f"{phone}@s.whatsapp.net",
                    "fromMe": False
                },
                "pushName": name,
                "message": { "conversation": text }
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        print(f"Status: {r.status_code}")
        try:
            print(r.json())
        except Exception:
            print(r.text[:1000])
    except Exception as e:
        print(f"Falha ao enviar webhook: {e}")

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--instance', default='printdash')
    p.add_argument('--phone', default='5511999999999')
    p.add_argument('--name', default='Teste Usuario')
    p.add_argument('--text', default='Mensagem de teste via webhook')
    p.add_argument('--url', default='http://localhost:8000/api/whatsapp/webhook')
    args = p.parse_args()
    simulate(args.instance, args.phone, args.name, args.text, args.url)
