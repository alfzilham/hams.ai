import os
import sys

base_dir = r"d:\2026\Workspace\Website\.AI\.hams.ai"

# 1. Rename files
files_to_rename = [
    "agent/llm/hams_max_agent.py",
    "agent/llm/hams_max_base.py",
    "agent/llm/hams_max_chat.py",
    "agent/llm/hams_max_provider.py",
    "agent/llm/.hams_max_provider.py",
    "agent/llm/hams_max_thinking.py",
]

for old_rel in files_to_rename:
    old_full = os.path.join(base_dir, old_rel)
    new_rel = old_rel.replace("hams_max", "zilf_max")
    new_full = os.path.join(base_dir, new_rel)
    if os.path.exists(old_full):
        os.rename(old_full, new_full)
        print(f"Renamed {old_rel} -> {new_rel}")
    else:
        print(f"Skipped {old_rel} (not found)")

# 2. String replacements
replacements = [
    ("hams_max", "zilf_max"),
    ("HamsMax", "ZilfMax"),
    ("hams-max", "zilf-max"),
    ("HAMS_MAX", "ZILF_MAX")
]

files_to_update = [
    "agent/llm/zilf_max_agent.py",
    "agent/llm/zilf_max_base.py",
    "agent/llm/zilf_max_chat.py",
    "agent/llm/zilf_max_provider.py",
    "agent/llm/.zilf_max_provider.py",
    "agent/llm/zilf_max_thinking.py",
    "agent/api.py",
    "agent/llm/router.py",
    "agent/core/reasoning_loop.py",
    "agent/core/task_planner.py",
    "test_agent.py"
]

for fpath in files_to_update:
    full_path = os.path.join(base_dir, fpath)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        changed = False
        for old_str, new_str in replacements:
            if old_str in content:
                content = content.replace(old_str, new_str)
                changed = True
                
        if changed:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Updated content in {fpath}")
