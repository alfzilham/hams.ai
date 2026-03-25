import os
import re

base_dir = r"d:\2026\Workspace\Website\.AI\.hams.ai"

# Ignore these directories
ignore_dirs = {".git", ".venv", "node_modules", "__pycache__", "chroma_db", ".claude", ".github"}

# Ignored file extensions
ignore_exts = {".db", ".pyc", ".png", ".jpg", ".jpeg", ".ico", ".log", ".sqlite3", ".mp3", ".wav"}

# File Rename mapping
file_renames = [
    (os.path.join("cli", "bin", "hams.js"), os.path.join("cli", "bin", "zilf.js")),
    (os.path.join("agent", "static", "chat.js"), os.path.join("agent", "static", "chat.js")), # Placeholder if need to rename more
]

for old, new in file_renames:
    try:
        old_full = os.path.join(base_dir, old)
        new_full = os.path.join(base_dir, new)
        if os.path.exists(old_full) and old_full != new_full:
            os.rename(old_full, new_full)
            print(f"Renamed {old} -> {new}")
    except Exception as e:
        print(f"Error renaming {old}: {e}")

# Content replacements in order of safety (longest match first)
content_replacements = [
    ("@hams-ai/", "@zilf-ai/"),
    ("Hams AI", "Zilf AI"),
    ("Hams.ai", "Zilf.ai"),
    ("HAMS.AI", "ZILF.AI"),
    ("hams.ai", "zilf.ai"),
    ("hams-ai", "zilf-ai"),
    ("HAMS_AI", "ZILF_AI"),
    ("hams_ai", "zilf_ai"),
    ("HAMS_", "ZILF_"),
    ("hams_", "zilf_"),
    ("hams.js", "zilf.js"),
    ("hams.db", "zilf.db"),
    ("Hams ", "Zilf "),
]

def should_process(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ignore_exts:
        return False
    parts = file_path.split(os.sep)
    for part in parts:
        if part in ignore_dirs:
            return False
        if part.endswith(".db") or part.endswith(".pyc") or part == "package-lock.json":
            return False
    return True

changed_count = 0
for root, dirs, files in os.walk(base_dir):
    # filter dirs
    dirs[:] = [d for d in dirs if d not in ignore_dirs]
    for filename in files:
        if filename in ["tmp_global_rename.py", "tmp_rename_max.py", "test_out.txt"]:
            continue
        full_path = os.path.join(root, filename)
        if not should_process(full_path):
            continue
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            new_content = content
            # Apply explicit replacements
            for old_str, new_str in content_replacements:
                new_content = new_content.replace(old_str, new_str)
            
            # Global word-boundary replacements for standalone "hams"
            new_content = re.sub(r'\bhams\b', 'zilf', new_content)
            new_content = re.sub(r'\bHams\b', 'Zilf', new_content)
            new_content = re.sub(r'\bHAMS\b', 'ZILF', new_content)

            if new_content != content:
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                rel_path = os.path.relpath(full_path, base_dir)
                print(f"Updated content in {rel_path}")
                changed_count += 1
        except Exception as e:
            pass # Ignore binary files or decoding errors

print(f"\nFinished sweeping. Modified {changed_count} files.")
