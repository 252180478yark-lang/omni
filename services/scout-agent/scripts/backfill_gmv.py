"""一次性回填 gmv_paid 日序列（2026-05-01 ~ 昨天）。

罗盘 core_trend_v3 支持自定义窗口；常规 ingest 只抓 8 天窗，5/13-5/19 等历史缺口
永远补不回来 → 30 天卡片少算一周（老板报"支付金额不对"的主因之一）。
用法: docker exec omni-scout-agent python scripts/backfill_gmv.py
"""
import asyncio
import json
from datetime import timedelta
from pathlib import Path

from app.config import settings
from app.services.catalog_loader import CatalogLoader
from app.services.live_fetch import LiveFetchExecutor
from app.services.metric_ingest import _mmdd, _yuan, _upsert_metrics, _ensure_shop_sentinel
from app.database import get_pool


async def main():
    cat_dir = Path("/app/catalog") if Path("/app/catalog").exists() else Path(__file__).resolve().parent.parent / "catalog"
    files = {p: cat_dir / f"{p}.json" for p in ("yuntu", "compass", "doudian") if (cat_dir / f"{p}.json").exists()}
    context = json.loads((cat_dir / "context.json").read_text("utf-8")) if (cat_dir / "context.json").exists() else {}
    sessions_root = Path(getattr(settings, "sessions_dir", "./sessions"))
    ex = LiveFetchExecutor(CatalogLoader.from_files(files, context), sessions_root)
    from datetime import date as date_cls
    yest = ex._today - timedelta(days=1)
    rows = []
    win_start = date_cls(2026, 5, 12)
    while win_start <= yest:
        win_end = min(win_start + timedelta(days=7), yest)
        r = await ex.fetch_raw(
            "compass", "compass.core_trend_v3",
            params={"begin_date": win_start.strftime("%Y/%m/%d 00:00:00"),
                    "end_date": win_end.strftime("%Y/%m/%d 00:00:00")},
        )
        parsed = r.get("parsed") or {}
        node = parsed.get("data") if isinstance(parsed.get("data"), dict) else None
        if not node or "module_data" not in node:
            print(f"window {win_start}..{win_end} FAILED:", str(parsed)[:200])
            win_start = win_end + timedelta(days=1)
            continue
        arr = node["module_data"]["trade_core_index_trend"]["unify_chart_info"]["axis_data"]["income_amt"]
        pts = [( _mmdd(p["x_str"], ex._today), _yuan(p["y"]) ) for p in arr]
        print(f"window {win_start}..{win_end}: {len(pts)} points")
        for dt, v in pts:
            print(" ", dt, v)
            rows.append({"metric": "gmv_paid", "date": dt, "value": v})
        win_start = win_end + timedelta(days=1)
    # 去重 (重叠窗以后值为准)
    dedup = {}
    for row in rows:
        dedup[row["date"]] = row
    rows = sorted(dedup.values(), key=lambda r: r["date"])
    print(f"total {len(rows)} unique dates")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_shop_sentinel(conn)
            n = await _upsert_metrics(conn, rows)
    print(f"upserted {n} rows")


asyncio.run(main())
