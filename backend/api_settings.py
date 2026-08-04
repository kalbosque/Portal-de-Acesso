import os
import json
import shutil
import zipfile
import subprocess
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Query, Depends
from fastapi.responses import JSONResponse, FileResponse
from database import engine
from sqlmodel import Session, text
from auth_utils import get_current_admin

router = APIRouter(prefix="/api/settings", tags=["Settings"], dependencies=[Depends(get_current_admin)])

# Caminho absoluto relativo ao diretório do script — garante leitura/escrita no arquivo correto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "public_html", "includes", "config.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "public_html", "uploads")
BACKUP_DIR = os.path.join(BASE_DIR, "public_html", "backups")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {}

def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

@router.get("/get")
async def get_settings():
    return {"success": True, "config": load_config()}

@router.post("/save")
async def save_settings(
    app_name: str = Form(...),
    app_tagline: str = Form(""),
    app_color: str = Form("#6366f1"),
    app_price_bw: str = Form("0.50"),
    app_price_color: str = Form("1.00"),
    url_atendimento: str = Form(""),
    guia_suporte_url: str = Form(""),
    app_logo_url: str = Form(""),
    mod_impressao: Optional[str] = Form(None),
    mod_suporte: Optional[str] = Form(None),
    mod_atendimento: Optional[str] = Form(None),
    whatsapp_webhook_url: str = Form(""),
    whatsapp_webhook_token: str = Form(""),
    app_logo_upload: Optional[UploadFile] = File(None),
    guia_suporte_upload: Optional[UploadFile] = File(None)
):
    """Salva configurações — clone exato da lógica do PHP"""
    config = load_config()
    
    # Processar preços (aceitar vírgula ou ponto)
    price_bw = float(str(app_price_bw).replace(",", "."))
    price_color = float(str(app_price_color).replace(",", "."))
    
    # Logo URL atual (pode ser atualizada pelo upload)
    logo = app_logo_url
    guia_url = guia_suporte_url
    
    # Upload de Logo
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if app_logo_upload and app_logo_upload.filename:
        ext = app_logo_upload.filename.split(".")[-1].lower()
        if ext in ["png", "jpg", "jpeg", "gif", "svg", "webp"]:
            new_name = f"logo_customizada.{ext}"
            file_path = os.path.join(UPLOAD_DIR, new_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(app_logo_upload.file, buffer)
            logo = f"uploads/{new_name}?v={int(datetime.now().timestamp())}"
    
    # Upload de Guia de Suporte
    if guia_suporte_upload and guia_suporte_upload.filename:
        ext = guia_suporte_upload.filename.split(".")[-1].lower()
        if ext in ["pdf", "doc", "docx", "txt", "jpg", "png"]:
            new_name = f"guia_suporte_usuario.{ext}"
            file_path = os.path.join(UPLOAD_DIR, new_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(guia_suporte_upload.file, buffer)
            guia_url = f"uploads/{new_name}"
    
    new_config = {
        "APP_NAME": app_name,
        "APP_TAGLINE": app_tagline,
        "APP_LOGO_URL": logo,
        "APP_COLOR": app_color,
        "APP_PRICE_BW": price_bw,
        "APP_PRICE_COLOR": price_color,
        "MODULO_IMPRESSAO": mod_impressao is not None,
        "MODULO_SUPORTE": mod_suporte is not None,
        "MODULO_ATENDIMENTO": mod_atendimento is not None,
        "URL_ATENDIMENTO": url_atendimento,
        "GUIA_SUPORTE_URL": guia_url,
        "WHATSAPP_WEBHOOK_URL": whatsapp_webhook_url,
        "WHATSAPP_WEBHOOK_TOKEN": whatsapp_webhook_token
    }
    
    save_config(new_config)
    return {"success": True, "message": "Configurações atualizadas!"}

@router.post("/upload_logo")
async def upload_logo(file: UploadFile = File(...)):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.split(".")[-1].lower()
    if ext not in ["png", "jpg", "jpeg", "gif", "svg", "webp"]:
        raise HTTPException(status_code=400, detail="Formato inválido")
    file_path = os.path.join(UPLOAD_DIR, f"logo_customizada.{ext}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    config = load_config()
    config["APP_LOGO_URL"] = f"uploads/logo_customizada.{ext}"
    save_config(config)
    return {"success": True, "logo_url": config["APP_LOGO_URL"]}

# =============================================
# BACKUP COMPLETO — Clone do admin_backup.php
# =============================================

@router.get("/backups/list")
async def list_backups():
    if not os.path.exists(BACKUP_DIR):
        return []
    backups = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith(".zip") or f.endswith(".sql"):
            path = os.path.join(BACKUP_DIR, f)
            stat = os.stat(path)
            size_mb = stat.st_size / (1024 * 1024)
            backups.append({
                "name": f,
                "date": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
                "size": f"{size_mb:.2f} MB",
                "type": f.split(".")[-1].upper()
            })
    return sorted(backups, key=lambda x: x['date'], reverse=True)

@router.get("/backups/generate")
async def generate_backup():
    """Gera backup completo do banco PostgreSQL + arquivos em ZIP"""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        sql_file = f"db_backup_{date_str}.sql"
        zip_file = f"FULL_BACKUP_{date_str}.zip"
        sql_path = os.path.join(BACKUP_DIR, sql_file)
        zip_path = os.path.join(BACKUP_DIR, zip_file)
        
        # 1. Gerar SQL do banco
        sql_content = f"-- Backup Total com Sequências - {date_str}\n\n"
        
        with Session(engine) as session:
            # Exportar Sequências
            seqs = session.exec(text(
                "SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public'"
            )).all()
            for seq_row in seqs:
                seq = seq_row[0]
                sql_content += f'DROP SEQUENCE IF EXISTS "{seq}" CASCADE;\n'
                sql_content += f'CREATE SEQUENCE "{seq}";\n'
            sql_content += "\n"
            
            # Exportar Tabelas
            tables = session.exec(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )).all()
            
            for table_row in tables:
                table = table_row[0]
                
                # Estrutura da tabela
                cols = session.exec(text(
                    f"SELECT column_name, data_type, is_nullable, column_default "
                    f"FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position"
                )).all()
                
                sql_content += f'DROP TABLE IF EXISTS "{table}" CASCADE;\nCREATE TABLE "{table}" (\n'
                col_defs = []
                has_id = False
                for col in cols:
                    col_name, data_type, is_nullable, col_default = col
                    if col_name == "id":
                        has_id = True
                    defn = f'  "{col_name}" {data_type}'
                    if is_nullable == "NO":
                        defn += " NOT NULL"
                    if col_default:
                        defn += f" DEFAULT {col_default}"
                    col_defs.append(defn)
                sql_content += ",\n".join(col_defs) + "\n);\n"
                
                # Dados da tabela
                rows = session.exec(text(f'SELECT * FROM "{table}"')).all()
                if rows:
                    # Pegar nomes das colunas
                    col_names = [c[0] for c in cols]
                    for row in rows:
                        vals = []
                        for v in row:
                            if v is None:
                                vals.append("NULL")
                            elif isinstance(v, (int, float)):
                                vals.append(str(v))
                            elif isinstance(v, bool):
                                vals.append("true" if v else "false")
                            else:
                                escaped = str(v).replace("'", "''")
                                vals.append(f"'{escaped}'")
                        quoted_cols = '", "'.join(col_names)
                        sql_content += f'INSERT INTO "{table}" ("{quoted_cols}") VALUES ({", ".join(vals)});\n'
                
                # Sincronizar sequência do ID
                if has_id:
                    sql_content += f"SELECT setval(pg_get_serial_sequence('\"{table}\"', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM \"{table}\";\n\n"
        
        # Salvar SQL
        with open(sql_path, "w", encoding="utf-8") as f:
            f.write(sql_content)
        
        # 2. Criar ZIP com SQL + arquivos do sistema
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Adicionar o SQL
            zf.write(sql_path, sql_file)
            
            # Adicionar arquivos do sistema (incluindo o novo frontend em templates/ e static/)
            paths_to_backup = ["public_html", "templates", "static", "main.py", "api_settings.py"]
            for root_path in paths_to_backup:
                full_root_path = os.path.join(BASE_DIR, root_path)
                if os.path.exists(full_root_path):
                    if os.path.isdir(full_root_path):
                        for dirpath, dirnames, filenames in os.walk(full_root_path):
                            # Ignorar pastas de backup, cache e git
                            dirnames[:] = [d for d in dirnames if d not in ["backups", ".git", "__pycache__"]]
                            for fname in filenames:
                                file_full = os.path.join(dirpath, fname)
                                arcname = os.path.relpath(file_full, BASE_DIR)
                                try:
                                    zf.write(file_full, arcname)
                                except:
                                    pass
                    else:
                        arcname = os.path.relpath(full_root_path, BASE_DIR)
                        try:
                            zf.write(full_root_path, arcname)
                        except:
                            pass
        
        # Remover SQL avulso (já está dentro do ZIP)
        if os.path.exists(sql_path):
            os.remove(sql_path)
        
        return {"success": True, "file": zip_file}
    
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.get("/backups/download/{filename}")
async def download_backup(filename: str):
    """Download de um arquivo de backup"""
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(BACKUP_DIR, safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Backup não encontrado")
    return FileResponse(file_path, filename=safe_filename)

@router.get("/backups/restore")
async def restore_backup(file: str = Query(...)):
    """Restaura um backup SQL ou ZIP"""
    try:
        safe_file = os.path.basename(file)
        file_path = os.path.join(BACKUP_DIR, safe_file)
        if not os.path.exists(file_path):
            return {"success": False, "message": "Arquivo não encontrado"}
        
        sql_content = ""
        if file.endswith(".zip"):
            with zipfile.ZipFile(file_path, "r") as zf:
                for name in zf.namelist():
                    if name.endswith(".sql"):
                        sql_content = zf.read(name).decode("utf-8")
                        break
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                sql_content = f.read()
        
        if not sql_content:
            return {"success": False, "message": "Conteúdo SQL não encontrado no arquivo"}
        
        with Session(engine) as session:
            # Executar cada statement separadamente
            statements = [s.strip() for s in sql_content.split(";") if s.strip()]
            for stmt in statements:
                try:
                    session.exec(text(stmt))
                except Exception as e:
                    print(f"Aviso ao restaurar: {e}")
                    continue
            session.commit()
        
        return {"success": True}
    
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/backups/upload")
async def upload_backup(backup_file: UploadFile = File(...)):
    """Upload e restauração de backup externo"""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ext = backup_file.filename.split(".")[-1].lower()
        new_name = f"UPLOAD_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        file_path = os.path.join(BACKUP_DIR, new_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(backup_file.file, buffer)
        
        # Restaurar automaticamente após upload
        result = await restore_backup(file=new_name)
        return result
    
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.get("/backups/delete")
async def delete_backup(file: str = Query(...)):
    """Exclui um backup"""
    safe_file = os.path.basename(file)
    file_path = os.path.join(BACKUP_DIR, safe_file)
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"success": True}
    return {"success": False, "message": "Arquivo não encontrado"}
