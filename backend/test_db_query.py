import sys
import os

print("Starting script...")

try:
    sys.path.append('c:/sistema-impressao/backend')
    from database import engine
    from sqlmodel import Session, select
    from models import EstudoPlano, EstudoSessao

    with Session(engine) as session:
        planos = session.exec(select(EstudoPlano)).all()
        sessoes = session.exec(select(EstudoSessao)).all()
        print(f"Total Planos: {len(planos)}")
        print(f"Total Sessoes: {len(sessoes)}")
        for p in planos[:10]:
            print(f"Plano: {p}")
except Exception as e:
    print(f"Error: {e}")
