import sqlite3
conn = sqlite3.connect('/app/data/sistema.db')
cur = conn.cursor()
cur.execute("SELECT id, usuario, whatsapp_cliente FROM chamado WHERE whatsapp_cliente like '%@g.us' LIMIT 10")
rows = cur.fetchall()
print("Chamados de grupo:")
for row in rows:
    print(row)
conn.close()
