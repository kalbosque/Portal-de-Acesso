from fastapi.testclient import TestClient
import backend.main as main
client = TestClient(main.app)
payload = {
    'event': 'messages.upsert',
    'instance': 'test',
    'data': [
        {
            'key': {'remoteJid': '5511999999999@s.whatsapp.net', 'fromMe': False},
            'pushName': 'Teste',
            'message': {'conversation': 'Ola'}
        }
    ]
}
r = client.post('/api/whatsapp/webhook', json=payload)
print(r.status_code)
print(r.json())
