import os
import re

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # We will split by "async def ", then check if the function block has "await "
    parts = content.split("async def ")
    if len(parts) == 1: return # no async def

    new_content = parts[0]
    for i in range(1, len(parts)):
        block = parts[i]
        
        # Where does the next definition start? It's not perfect but we can just check if "await " is in the block before the next "def "
        # A simpler way is to just look if "await " exists in the file, if not, we can replace all "async def "
        pass

    # Actually simpler: if "await " not in content, just replace all "async def " with "def "
    if "await " not in content:
        new_content = content.replace("async def ", "def ")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Fixed {filepath} completely")
        return

    # If it contains await, let's use regex to find each function.
    # It's easier to just do it line by line for functions we know don't have await.
    # We know api_printers, api_settings, api_users_mgmt, main.py have await.
    # For those, we can just leave them or manually replace specific ones.
    
    # Actually, let's just let it be for now and do manual replacement for main.py.

if __name__ == "__main__":
    for f in os.listdir("."):
        if f.endswith(".py"):
            fix_file(f)
