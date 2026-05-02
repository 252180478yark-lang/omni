import os
import subprocess
import json

base = r"C:\Users\Administrator\Desktop\1\exported_markdown"
local = {n for n in os.listdir(base) if os.path.isdir(os.path.join(base, n)) and n not in {"_failed", "_state"}}

sql = "SELECT DISTINCT title FROM knowledge.tasks WHERE kb_id = '608807ec-29ff-4fc0-b15b-73d0609c93a8';"
cmd = ["docker", "exec", "omni-postgres", "psql", "-U", "omni_user", "-d", "omni_vibe_db", "-At", "-c", sql]
out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="ignore")
kb = {line.strip() for line in out.splitlines() if line.strip()}

missing = sorted(local - kb)
only_kb = sorted(kb - local)

result = {
    "local_count": len(local),
    "kb_count": len(kb),
    "missing_from_kb_count": len(missing),
    "only_in_kb_count": len(only_kb),
    "missing_from_kb": missing,
}

print(json.dumps(result, ensure_ascii=False, indent=2))
