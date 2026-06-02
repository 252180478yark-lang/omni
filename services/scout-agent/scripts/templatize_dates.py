"""把 catalog 里硬编码的日期参数值替换成模板占位符（按 key 角色 + 值格式）。

让 shipped catalog 在任意未来日期都解析成当前日期（executor build_render_context 提供占位符）。
角色：key 含 begin/start → 窗口起；含 end → 窗口止；否则 → 单点参考日。
用法：python scripts/templatize_dates.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CAT = Path(__file__).resolve().parents[1] / "catalog"

YYYYMMDD = re.compile(r"^\d{8}$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLASHDT = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$")
YM = re.compile(r"^\d{4}-\d{2}$")
YYYYMM = re.compile(r"^\d{6}$")


def _role(key: str) -> str:
    k = key.lower()
    if "begin" in k or "start" in k:
        return "begin"
    if "end" in k:
        return "end"
    return "ref"


def _placeholder(key: str, val: str) -> str | None:
    role = _role(key)
    if YYYYMMDD.match(val):
        return {"begin": "{win_begin_yyyymmdd}", "end": "{win_end_yyyymmdd}",
                "ref": "{ref_yyyymmdd}"}[role]
    if ISO.match(val):
        return {"begin": "{win_begin_iso}", "end": "{win_end_iso}", "ref": "{ref_iso}"}[role]
    if SLASHDT.match(val):
        return {"begin": "{win_begin_slashdt}", "end": "{win_end_slashdt}",
                "ref": "{win_end_slashdt}"}[role]
    if YM.match(val):
        return "{last_month}"
    if YYYYMM.match(val):
        return "{this_month_compact}"
    return None


def main():
    summary = {}
    for f in sorted(CAT.glob("*.json")):
        if f.name.startswith("_") or f.name == "context.json":
            continue
        entries = json.loads(f.read_text("utf-8"))
        n = 0
        for e in entries:
            params = e.get("params") or {}
            for k, v in list(params.items()):
                if isinstance(v, str):
                    ph = _placeholder(k, v)
                    if ph:
                        params[k] = ph
                        n += 1
        f.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")
        summary[f.stem] = n
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
