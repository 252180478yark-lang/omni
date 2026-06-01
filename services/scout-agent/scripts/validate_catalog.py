"""重放整个 catalog 验证哪些端点今天还活着，写回 verified 标 + 出报告。

用法（scout-agent 已起 + 已登录）：
    python scripts/validate_catalog.py [yuntu|compass|doudian|all]
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.catalog_loader import CatalogLoader  # noqa: E402
from app.services.live_fetch import LiveFetchExecutor  # noqa: E402

CAT = Path(__file__).resolve().parents[1] / "catalog"
SESSIONS = Path(__file__).resolve().parents[1] / "sessions"
TODAY = date.today().isoformat()
INTER_DELAY = 0.8  # 防限流（phase5 经验：避免 529）


async def validate(platform: str) -> dict:
    path = CAT / f"{platform}.json"
    entries = json.loads(path.read_text("utf-8"))
    context = json.loads((CAT / "context.json").read_text("utf-8"))
    loader = CatalogLoader(entries, context)
    ex = LiveFetchExecutor(loader, SESSIONS)
    if not ex.has_cookies(platform):
        return {"platform": platform, "error": "no_cookies",
                "hint": f"先去 /scout 扫码登录 {platform}"}

    counts: dict[str, int] = {}
    drift: list[dict] = []
    for e in entries:
        res = await ex.fetch(platform=platform, endpoint=e["key"])
        v = res.get("verdict", "EXCEPTION")
        counts[v] = counts.get(v, 0) + 1
        ok = v in ("PASS", "PASS_NODATA")
        e["verified"] = ok
        e["verified_at"] = TODAY
        if not ok:
            drift.append({"key": e["key"], "path": e["path"], "verdict": v,
                          "code": res.get("code"), "url": res.get("url")})
        await asyncio.sleep(INTER_DELAY)

    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")
    report = CAT / f"_validation_{platform}_{TODAY}.json"
    report.write_text(json.dumps(
        {"platform": platform, "date": TODAY, "counts": counts,
         "total": len(entries), "drift": drift}, ensure_ascii=False, indent=2), "utf-8")
    return {"platform": platform, "counts": counts, "total": len(entries),
            "drift_count": len(drift), "report": str(report)}


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    platforms = ["yuntu", "compass", "doudian"] if target == "all" else [target]
    for p in platforms:
        r = await validate(p)
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
