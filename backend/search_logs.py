import os

logs = ["agent.log", "agent_debug.log", "agent_debug2.log", "agent_debug3.log", "agent_debug4.log", "agent_out.txt", "deploy_log.txt", "web_log.txt", "db_tables.txt"]

print("STARTING LOG SEARCH")
for log in logs:
    if os.path.exists(log):
        print("Searching log:", log)
        try:
            with open(log, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if "COFRE_SECRET_KEY" in line or "COFRE_SECRET" in line:
                        print(f"MATCH in {log}:{i} -> {line.strip()[:150]}")
        except Exception as e:
            print("Error reading:", log, e)
print("Search done.")
