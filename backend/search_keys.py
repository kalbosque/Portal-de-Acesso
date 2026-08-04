import os

print("SEARCHING AGENT_2.0.PY")
with open("agent_2.0.py", "r", encoding="utf-8", errors="ignore") as f:
    for i, line in enumerate(f, 1):
        if any(k in line for k in ["COFRE", "KEY", "SECRET", "Fernet", "cryptography"]):
            print(f"Line {i}: {line.strip()}")
