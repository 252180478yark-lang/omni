import json
import os
import time
from pathlib import Path

import httpx

BASE_DIR = Path(r"C:\Users\Administrator\Desktop\1\exported_markdown")
API_BASE = "http://localhost/api/v1/knowledge"
KB_NAME = "巨量云图"


def read_text(folder: Path) -> str:
    c1 = folder / "content.md"
    c2 = folder / "content.md.bak"
    for p in (c1, c2):
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore").strip()
                if len(txt) >= 20:
                    return txt
            except Exception:
                pass
    return ""


def read_meta(folder: Path) -> dict:
    mp = folder / "meta.json"
    if not mp.exists():
        return {}
    try:
        return json.loads(mp.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


with httpx.Client(timeout=60.0) as client:
    bases = client.get(f"{API_BASE}/bases").json().get("data", [])
    kb = next((b for b in bases if b.get("name") == KB_NAME), None)
    if not kb:
        raise SystemExit(f"KB not found: {KB_NAME}")
    kb_id = kb["id"]

    tasks = client.get(f"{API_BASE}/tasks", params={"kb_id": kb_id, "limit": 200}).json().get("data", [])
    existing_titles = {t.get("title", "") for t in tasks}

    local_folders = [p for p in BASE_DIR.iterdir() if p.is_dir() and p.name not in {"_failed", "_state"}]
    local_titles = {p.name for p in local_folders}

    missing_titles = sorted(local_titles - existing_titles)

    print(f"KB: {KB_NAME} ({kb_id})")
    print(f"Existing tasks: {len(existing_titles)}")
    print(f"Local folders: {len(local_titles)}")
    print(f"Need import: {len(missing_titles)}")

    success = []
    failed = []

    for idx, title in enumerate(missing_titles, 1):
        folder = BASE_DIR / title
        text = read_text(folder)
        if not text:
            failed.append((title, "empty content.md"))
            print(f"[{idx}/{len(missing_titles)}] FAIL {title} -> empty content")
            continue

        meta = read_meta(folder)
        source_url = meta.get("source_url") if isinstance(meta, dict) else None
        source_type = (meta.get("original_type") if isinstance(meta, dict) else None) or "manual"

        payload = {
            "kb_id": kb_id,
            "title": title,
            "text": text,
            "source_url": source_url,
            "source_type": source_type,
        }

        try:
            r = client.post(f"{API_BASE}/ingest", json=payload)
            if r.status_code == 202:
                task_id = r.json().get("data", {}).get("task_id", "")
                success.append((title, task_id))
                print(f"[{idx}/{len(missing_titles)}] OK   {title} -> {task_id}")
            else:
                msg = r.text[:300]
                failed.append((title, f"HTTP {r.status_code}: {msg}"))
                print(f"[{idx}/{len(missing_titles)}] FAIL {title} -> HTTP {r.status_code}")
        except Exception as e:
            failed.append((title, str(e)))
            print(f"[{idx}/{len(missing_titles)}] FAIL {title} -> {e}")

        time.sleep(0.05)

    report = {
        "kb_id": kb_id,
        "kb_name": KB_NAME,
        "need_import": len(missing_titles),
        "success_count": len(success),
        "failed_count": len(failed),
        "success": [{"title": t, "task_id": tid} for t, tid in success],
        "failed": [{"title": t, "error": err} for t, err in failed],
    }

    out_path = Path(r"E:\agent\omni\import_yuntu_report.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. success={len(success)} failed={len(failed)}")
    print(f"Report: {out_path}")
