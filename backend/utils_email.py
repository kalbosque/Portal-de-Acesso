import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

def send_email_async(to_email: str, subject: str, body: str):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_from = os.getenv("SMTP_FROM")

    if not all([smtp_server, smtp_user, smtp_pass]):
        print("Configuração de e-mail incompleta no .env")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_from
        msg['To'] = to_email
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"E-mail enviado para {to_email}")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")

def notify_new_ticket(ticket_id: int, user: str, title: str, priority: str, description: str):
    admin_email = os.getenv("ADMIN_EMAIL")
    if not admin_email: return
    
    subject = f"🆕 Novo Chamado: #{ticket_id} - {title}"
    body = f"""
    <div style="font-family: sans-serif; max-width: 600px; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
        <h2 style="color: #6366f1;">Um novo chamado foi aberto!</h2>
        <p><b>Usuário:</b> {user}</p>
        <p><b>Assunto:</b> {title}</p>
        <p><b>Prioridade:</b> {priority}</p>
        <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
        <p style="color: #475569;">{description}</p>
        <br>
        <a href="http://seu-servidor:8000/chamados" style="background: #6366f1; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">Ver no Painel</a>
    </div>
    """
    send_email_async(admin_email, subject, body)

def notify_resolved_ticket(to_email: str, ticket_id: int, user: str, note: str):
    if not to_email: return
    
    subject = f"✅ Chamado Finalizado: #{ticket_id}"
    note_html = note.replace('\n', '<br>')
    body = f"""
    <div style="font-family: sans-serif; max-width: 600px; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
        <h2 style="color: #10b981;">Seu chamado foi concluído!</h2>
        <p>Olá <b>{user}</b>, o seu chamado foi finalizado pela equipe técnica.</p>
        <div style="background: #f8fafc; padding: 15px; border-radius: 10px; border: 1px solid #e2e8f0; color: #1e293b;">
            <b>Nota Técnica / Resolução:</b><br>
            {note_html}
        </div>
        <p>Agradecemos o contato.</p>
    </div>
    """
    send_email_async(to_email, subject, body)
