import time
import schedule
from datetime import datetime, timedelta
from sqlmodel import Session, select
from database import engine
from models import StatusMaquina
from utils_email import send_email_async
import os
from dotenv import load_dotenv

load_dotenv()

def check_offline_machines():
    print(f"[{datetime.now()}] Iniciando verificação de máquinas offline...")
    try:
        with Session(engine) as session:
            limite_offline = datetime.now() - timedelta(minutes=15)
            
            # Pega máquinas que passaram do limite e que ainda não receberam alerta
            maquinas_offline = session.exec(
                select(StatusMaquina).where(
                    StatusMaquina.timestamp < limite_offline,
                    StatusMaquina.alerta_enviado == False
                )
            ).all()

            admin_email = os.getenv("ADMIN_EMAIL")

            for maq in maquinas_offline:
                print(f"Máquina offline detectada: {maq.nome} ({maq.ip})")
                if admin_email:
                    subject = f"⚠️ ALERTA: Máquina {maq.nome} OFFLINE"
                    body = f"""
                    <h2>Alerta de Conectividade</h2>
                    <p>A máquina <b>{maq.nome}</b> (IP: {maq.ip}) parou de enviar sinais para o servidor de impressão.</p>
                    <p><b>Último contato:</b> {maq.timestamp.strftime('%d/%m/%Y %H:%M:%S')}</p>
                    <p><b>Usuário Logado:</b> {maq.windows_user}</p>
                    <br>
                    <p>Verifique o equipamento ou se há problemas de rede no setor.</p>
                    """
                    send_email_async(admin_email, subject, body)
                
                # Marca como enviado para não alertar de novo a mesma máquina
                maq.alerta_enviado = True
                session.add(maq)

            session.commit()
    except Exception as e:
        print(f"Erro na verificação de máquinas: {e}")

def cleanup_old_records():
    print(f"[{datetime.now()}] Iniciando limpeza de registros antigos...")
    try:
        with Session(engine) as session:
            # Remove status de máquinas que não se comunicam há mais de 30 dias
            limite_remocao = datetime.now() - timedelta(days=30)
            maquinas_velhas = session.exec(
                select(StatusMaquina).where(StatusMaquina.timestamp < limite_remocao)
            ).all()
            for m in maquinas_velhas:
                session.delete(m)
            
            session.commit()
            print(f"{len(maquinas_velhas)} registros antigos removidos da tabela StatusMaquina.")
    except Exception as e:
        print(f"Erro na limpeza: {e}")

if __name__ == "__main__":
    print("Iniciando Background Worker...")
    
    # Roda a checagem de máquinas a cada 10 minutos
    schedule.every(10).minutes.do(check_offline_machines)
    
    # Roda a limpeza aos domingos às 03:00 da manhã
    schedule.every().sunday.at("03:00").do(cleanup_old_records)
    
    # Roda a primeira verificação imediatamente no boot
    check_offline_machines()
    
    while True:
        schedule.run_pending()
        time.sleep(60)
