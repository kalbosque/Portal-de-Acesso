import socket
from datetime import datetime, timedelta
from sqlmodel import Session, select, create_engine
from models import Licenca
import os
import psycopg2

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME", "sistema_impressao")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "root")


def _build_database_url() -> str:
    candidates = []
    if DB_HOST:
        candidates.append(DB_HOST)
    candidates.extend(["db", "localhost", "127.0.0.1"])

    seen = set()
    for host in candidates:
        if host in seen:
            continue
        seen.add(host)
        try:
            conn = psycopg2.connect(
                host=host,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASS,
                connect_timeout=1,
            )
            conn.close()
            print(f"[LICENSE_DB] Conectando em {host}")
            return f"postgresql://{DB_USER}:{DB_PASS}@{host}/{DB_NAME}"
        except Exception as exc:
            print(f"[LICENSE_DB] Host indisponivel ({host}): {exc}")

    fallback = DB_HOST or "db"
    print(f"[LICENSE_DB] Nenhum host respondeu. Usando fallback {fallback}")
    return f"postgresql://{DB_USER}:{DB_PASS}@{fallback}/{DB_NAME}"


DATABASE_URL = _build_database_url()
engine = create_engine(DATABASE_URL)

def get_hardware_id():
    """Gera um ID único baseado no nome da máquina (servidor)"""
    return socket.gethostname().upper()

def is_license_valid() -> bool:
    """Verifica se existe uma licença ativa e dentro do prazo"""
    with Session(engine) as session:
        hw_id = get_hardware_id()
        statement = select(Licenca).where(
            Licenca.hardware_id == hw_id, 
            Licenca.status == "ativo"
        ).order_by(Licenca.data_expiracao.desc())
        
        licenca = session.exec(statement).first()
        
        if not licenca:
            return False
            
        # Verifica se expirou
        if datetime.now() > licenca.data_expiracao:
            licenca.status = "expirado"
            session.add(licenca)
            session.commit()
            return False
            
        return True

def activate_token(token: str) -> bool:
    """Ativa um novo token por 30 dias"""
    token = token.strip()
    if not token.startswith("PD-"):
        return False
        
    with Session(engine) as session:
        hw_id = get_hardware_id()
        
        # Verifica se este token já foi ativado para evitar erro de duplicidade
        statement = select(Licenca).where(Licenca.token == token)
        existente = session.exec(statement).first()
        if existente:
            return True # Já está ativado, apenas libera o acesso
            
        try:
            # Cria a licença de 30 dias
            nova_licenca = Licenca(
                token=token,
                data_ativacao=datetime.now(),
                data_expiracao=datetime.now() + timedelta(days=30),
                hardware_id=hw_id,
                status="ativo"
            )
            session.add(nova_licenca)
            session.commit()
            return True
        except Exception as e:
            print(f"Erro ao ativar: {e}")
            return False
