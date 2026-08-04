import os
import zipfile

backup_dir = "public_html/backups"
print("SEARCHING BACKUPS")

if not os.path.exists(backup_dir):
    print("No backups folder found")
    exit()

for file in os.listdir(backup_dir):
    if file.endswith(".zip"):
        path = os.path.join(backup_dir, file)
        try:
            with zipfile.ZipFile(path, 'r') as z:
                for name in z.namelist():
                    # We are looking for .env, docker-compose.yml or python files that might contain the key
                    if ".env" in name or "docker-compose" in name or name.endswith((".py", ".json", ".php", ".sh", ".ps1")):
                        try:
                            content = z.read(name).decode("utf-8", errors="ignore")
                            for line in content.splitlines():
                                if "COFRE_SECRET_KEY" in line or "cofre-default" in line:
                                    print(f"MATCH in {file} -> {name}: {line.strip()[:150]}")
                                elif "COFRE" in line and ("key" in line.lower() or "secret" in line.lower() or "=" in line):
                                    print(f"MATCH in {file} -> {name}: {line.strip()[:150]}")
                        except Exception as e:
                            pass
        except Exception as e:
            print(f"Error reading zip {file}: {e}")
print("Search done.")
