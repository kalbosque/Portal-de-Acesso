import os
import time
from sqlmodel import create_engine, Session, SQLModel

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

DB_HOST = os.getenv("DB_HOST", "db")
DB_NAME = os.getenv("DB_NAME", "sistema_impressao")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "root")

# Monta a URL diretamente a partir das variáveis de ambiente
# O healthcheck do docker-compose já garante que o DB está pronto antes
# de este container iniciar — não é necessário testar a conexão aqui.
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
print(f"[DB] Usando URL: postgresql://{DB_USER}:***@{DB_HOST}/{DB_NAME}")

engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5},
    echo=False
)

