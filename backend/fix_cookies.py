import os
import re

files_to_fix = [
    "api_tickets.py",
    "main.py"
]

for f in files_to_fix:
    if not os.path.exists(f): continue
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if "request.cookies.get" in content:
        new_content = re.sub(r'request\.cookies\.get\((.*?)\)', r'get_signed_cookie(request, \1)', content)
        if "get_signed_cookie" not in content:
            new_content = "from auth_utils import get_signed_cookie\n" + new_content
        with open(f, 'w', encoding='utf-8') as file:
            file.write(new_content)
        print(f"Fixed {f}")
    else:
        print(f"No match in {f}")
