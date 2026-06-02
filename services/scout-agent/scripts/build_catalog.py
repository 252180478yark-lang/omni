"""把 phase5 testcases jsonl + MASTER_ENDPOINTS_INVENTORY.md 构建成 catalog/*.json。

用法：python scripts/build_catalog.py
输出：catalog/{yuntu,compass,doudian}.json（覆盖写）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # omni 根
OMNI = ROOT
PHASE5 = OMNI / "docs" / "_phase5_live"
INVENTORY = OMNI / "docs" / "MASTER_ENDPOINTS_INVENTORY.md"
OUT = Path(__file__).resolve().parents[1] / "catalog"

HOSTS = {"yuntu": "yuntu.oceanengine.com", "compass": "compass.jinritemai.com",
         "doudian": "fxg.jinritemai.com"}
BIZ_FIELD = {"yuntu": "status", "compass": "st", "doudian": "code"}

# 每平台用最新一版 testcases
TESTCASE_FILES = {
    "yuntu": ["testcases_yuntu_v4.jsonl", "testcases_yuntu_v3.jsonl", "testcases_yuntu.jsonl"],
    "compass": ["testcases_compass_v4.jsonl", "testcases_compass_v3_fixed.jsonl", "testcases_compass.jsonl"],
    "doudian": ["testcases_doudian_v2.jsonl", "testcases_doudian.jsonl"],
}


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "ep"


def _key(platform: str, path: str, idx: int) -> str:
    tail = _slug(path.rstrip("/").split("/")[-1]) or f"ep{idx}"
    return f"{platform}.{tail}"


def from_testcases(platform: str) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    src = None
    for fn in TESTCASE_FILES[platform]:
        if (PHASE5 / fn).exists():
            src = PHASE5 / fn
            break
    if not src:
        return out
    for i, line in enumerate(src.read_text("utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        tc = json.loads(line)
        method = (tc.get("method") or "GET").upper()
        path = tc.get("url") or ""
        if not path.startswith("/"):
            continue
        host = tc.get("host") or HOSTS[platform]
        dedup = (platform, method, path.split("?")[0])
        out[dedup] = {
            "key": _key(platform, path, i),
            "platform": platform,
            "category": tc.get("category", ""),
            "aliases": [tc["desc"]] if tc.get("desc") else [],
            "host": host,
            "method": method,
            "path": path.split("?")[0],
            "params": tc.get("params") or {},
            "body": tc.get("body"),
            "biz_code_field": BIZ_FIELD[platform],
            "expected_fields": tc.get("expected_fields") or [],
            "verified": True,
            "verified_at": "2026-05-26",
            "notes": "from phase5 testcase",
        }
    return out


_HEADER_PREFIX = re.compile(r"`([a-zA-Z0-9_]+/[a-zA-Z0-9_./*]+)`")


def from_inventory(platform: str, seen: set[tuple]) -> list[dict]:
    """解析 inventory：跟踪域族前缀，端点短名拼全路径。仅补 testcases 没有的。"""
    if not INVENTORY.exists():
        return []
    lines = INVENTORY.read_text("utf-8").splitlines()
    # 平台分节：## 1. 云图 / ## 2. 罗盘 / ## 3. 抖店
    sect = {"yuntu": ("## 1.", "## 2."), "compass": ("## 2.", "## 3."),
            "doudian": ("## 3.", "## 4.")}[platform]
    start = next((i for i, l in enumerate(lines) if l.startswith(sect[0])), None)
    end = next((i for i, l in enumerate(lines) if l.startswith(sect[1])), len(lines))
    if start is None:
        return []
    block = lines[start:end]
    out: list[dict] = []
    prefix = ""
    for i, l in enumerate(block):
        if l.startswith("### ") or l.startswith("#### "):
            m = _HEADER_PREFIX.search(l)
            if m:
                prefix = m.group(1).rstrip("*").rstrip("/")
            continue
        if not l.startswith("| `"):
            continue
        cols = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cols) < 2:
            continue
        name = cols[0].strip("` ")
        method = cols[1].strip().upper().split()[0] if cols[1].strip() else "GET"
        if method not in ("GET", "POST"):
            method = "GET"
        if not name or " " in name:
            continue
        # 拼路径：name 已含 / 用 prefix 根；否则 prefix + name
        if "/" in name:
            base = prefix.split("/")[0] if prefix else ""
            path = f"/{base}/{name}" if base else f"/{name}"
        else:
            path = f"/{prefix}/{name}" if prefix else f"/{name}"
        path = re.sub(r"/+", "/", path)
        dedup = (platform, method, path)
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append({
            "key": _key(platform, path, i),
            "platform": platform,
            "category": prefix,
            "aliases": [cols[3]] if len(cols) > 3 and cols[3] else [],
            "host": HOSTS[platform],
            "method": method,
            "path": path,
            "params": {},
            "body": None,
            "biz_code_field": BIZ_FIELD[platform],
            "expected_fields": [],
            "verified": False,
            "verified_at": None,
            "notes": f"from inventory (候选路径, 待 sweep 验证); raw={cols[4] if len(cols) > 4 else ''}",
        })
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for platform in ("yuntu", "compass", "doudian"):
        tc = from_testcases(platform)
        seen = set(tc.keys())
        inv = from_inventory(platform, seen)
        # key 去重（同 tail 加序号）
        entries = list(tc.values()) + inv
        used: dict[str, int] = {}
        for e in entries:
            k = e["key"]
            if k in used:
                used[k] += 1
                e["key"] = f"{k}_{used[k]}"
            else:
                used[k] = 0
        (OUT / f"{platform}.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")
        summary[platform] = {"total": len(entries),
                             "verified": sum(1 for e in entries if e["verified"]),
                             "from_inventory": len(inv)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
