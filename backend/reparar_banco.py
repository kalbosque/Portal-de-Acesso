from database import engine
from sqlalchemy import text
import json

def fix_all_permissions():
    with engine.connect() as conn:
        # 1. Limpar todos os operadores para ["Suporte"]
        print("Limpando permissões de operadores...")
        perms_op = json.dumps(["Suporte"])
        conn.execute(text("UPDATE usuarios SET permissoes = :p WHERE role = 'operator'"), {"p": perms_op})
        
        # 2. Restaurar acesso total para Administradores
        print("Restaurando acesso total para Administradores...")
        perms_admin = json.dumps(["Dashboard", "Equipamentos", "Relatórios", "Suporte", "Usuários", "Ajustes"])
        conn.execute(text("UPDATE usuarios SET role = 'admin', permissoes = :p WHERE role = 'admin' OR username IN ('admin', 'renatovd', 'ti@atual-rnc.com.br')"), {"p": perms_admin})
        
        conn.commit()
        print("Faxina concluída com sucesso!")

if __name__ == "__main__":
    fix_all_permissions()
