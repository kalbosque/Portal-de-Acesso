import base64
import hashlib
from cryptography.fernet import Fernet
from sqlmodel import Session, select
from database import engine
from models import CofreSenha
import os

# Standard key deriving
def get_fernet(raw_key: str):
    key = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode()).digest())
    return Fernet(key)

candidate_key = os.environ.get("COFRE_KEY")
if not candidate_key:
    raise SystemExit("Defina COFRE_KEY no ambiente para executar este teste.")

with Session(engine) as session:
    items = session.exec(select(CofreSenha)).all()
    print(f"Found {len(items)} credentials.")
    if not items:
        exit()

    for item in items[:3]:
        print(f"\nItem: {item.titulo} ({item.login_email})")
        
        for raw_key in [candidate_key]:
            try:
                f = get_fernet(raw_key)
                plain = f.decrypt(item.senha_cifrada.encode("utf-8")).decode("utf-8")
                print(f"  SUCCESS with key '{raw_key}': {plain}")
            except Exception as e:
                pass
