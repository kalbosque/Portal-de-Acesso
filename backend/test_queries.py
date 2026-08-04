import sys
from sqlmodel import Session, select, func
from database import engine
from models import Impressao, Impressora
from sqlalchemy import desc

def test_query():
    try:
        with Session(engine) as session:
            print("Tentando Top 5 Impressoras...")
            stmt_imp = select(Impressora.nome, func.sum(Impressao.paginas).label("total")).join(Impressao, Impressao.impressora_id == Impressora.id).group_by(Impressora.nome).order_by(desc(func.sum(Impressao.paginas))).limit(5)
            session.exec(stmt_imp).all()
            
            print("Tentando Top 5 Usuarios...")
            stmt_usu = select(Impressao.usuario, func.sum(Impressao.paginas).label("total")).group_by(Impressao.usuario).order_by(desc(func.sum(Impressao.paginas))).limit(5)
            session.exec(stmt_usu).all()

            print("Todas as consultas passaram sem erro!")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_query()
