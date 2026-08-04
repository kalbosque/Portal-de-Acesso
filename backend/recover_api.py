import json
import re

log_path1 = r'C:\Users\Servidor-XML\.gemini\antigravity\brain\ef5be3a0-b6b8-42de-8632-f64c9b61616e\.system_generated\logs\transcript.jsonl'
log_path2 = r'C:\Users\Servidor-XML\.gemini\antigravity\brain\6e092dd0-b09f-4dad-bd30-eec2a9a29b05\.system_generated\logs\transcript.jsonl'

def find_file(log_path):
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            if 'view_file' in line and 'api_tickets.py' in line:
                try:
                    data = json.loads(line)
                    # if it's a tool response
                    if data.get('type') == 'TOOL_RESPONSE':
                        output = data.get('content', '')
                        if 'Total Lines' in output:
                            # Parse out the file lines
                            lines = output.split('\n')
                            clean_lines = []
                            for l in lines:
                                m = re.match(r'^\d+:\s(.*)', l)
                                if m:
                                    clean_lines.append(m.group(1))
                            
                            if clean_lines:
                                with open('api_tickets.py', 'w', encoding='utf-8') as out:
                                    out.write('\n'.join(clean_lines))
                                return True
                except:
                    pass
    return False

if find_file(log_path1) or find_file(log_path2):
    print("Recovered!")
else:
    print("Not found")
