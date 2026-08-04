import os

base_dir = r"C:\Users\Servidor-XML\.gemini\config"
print(f"Searching in config: {base_dir}")

for root, dirs, files in os.walk(base_dir):
    for file in files:
        if file.endswith((".jsonl", ".json", ".log", ".txt", ".md", ".env", ".cfg", ".ini")):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if any(k in line.lower() for k in ["cofre", "fernet", "secret_key"]):
                            print(f"MATCH: {path}:{i} -> {line.strip()[:150]}")
            except Exception as e:
                pass
print("Config search done.")
