WHATSAPP Multi-Instance — Testes e Migração
=========================================

1) Aplicar migração ao banco (Postgres)
--------------------------------------
Execute no servidor do banco de dados (ou numa máquina com acesso `psql`):

```bash
psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -c "ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_instance VARCHAR;"
psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -c "CREATE INDEX IF NOT EXISTS idx_chamados_whatsapp_instance ON chamados (whatsapp_instance);"
```

Ou use o arquivo de migração gerado:

```bash
psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -f db/migrations/001_add_whatsapp_instance.sql
```

2) Simular um webhook (gera/atualiza chamado)
---------------------------------------------
Requer Python 3 e `requests` instalado (`pip install requests`).

```bash
python scripts/simulate_webhook.py --instance minha_instancia1 --phone 5511999999999 --name "Teste" --text "Olá via webhook"
```

3) Verificar o banco se o chamado foi criado e tem `whatsapp_instance`
----------------------------------------------------------------------
Use `psql`:

```bash
psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -c "SELECT id, whatsapp_cliente, whatsapp_instance, status FROM chamados ORDER BY id DESC LIMIT 5;"
```

4) Verificar instâncias e números conectados
--------------------------------------------
No navegador (requer sessão autenticada como usuário com permissão Atendimento): abra a página de Configuração do WhatsApp no app.

Ou chamar o endpoint (requer sessão/cookies do app):

```bash
curl -b "<cookies>" http://localhost:8000/api/whatsapp/instances
```

5) Gerar QR e verificar status por instância
--------------------------------------------
Recomendo usar a UI: `Configuração do WhatsApp` no painel de administração.

Com `curl` (requer sessão autenticada):

```bash
curl -b "<cookies>" "http://localhost:8000/api/whatsapp/status?instance=minha_instancia1"
curl -b "<cookies>" "http://localhost:8000/api/whatsapp/qrcode?instance=minha_instancia1"
```

6) Notas importantes
--------------------
- Endpoints administrativos exigem usuário `admin` autenticado.
- Se a Evolution API não estiver acessível, as chamadas de status/qrcode/logout retornarão erro.
- O script `scripts/simulate_webhook.py` envia um JSON simplificado compatível com o webhook esperado pelo backend.

Se quiser, eu posso:
- Gerar um script PowerShell equivalente para Windows.
- Rodar uma checagem de sintaxe Python nos scripts (se desejar).
- Criar um pequeno endpoint de teste que aceite um token para simular webhooks com segurança.
