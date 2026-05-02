"""
benchmark_loader.py — T11

Writes industry benchmark values to mvp_industry_benchmark.
Called by Compass and Yuntu runbooks after downloading comparison data.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.database import get_pool

log = logging.getLogger(__name__)


async def upsert_benchmark(
    benchmark_date: date,
    category_id: str,
    metric_name: str,
    *,
    industry_avg: float | None = None,
    industry_top: float | None = None,
    shop_value: float | None = None,
    percentile: float | None = None,
    industry_rank: int | None = None,
    source: str = "compass",
    raw: dict[str, Any] | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mvp_industry_benchmark
                (date, category_id, metric_name,
                 industry_avg, industry_top, shop_value, percentile, industry_rank, source, raw)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (date, category_id, metric_name) DO UPDATE SET
                industry_avg   = EXCLUDED.industry_avg,
                industry_top   = EXCLUDED.industry_top,
                shop_value     = EXCLUDED.shop_value,
                percentile     = EXCLUDED.percentile,
                industry_rank  = EXCLUDED.industry_rank,
                raw            = EXCLUDED.raw
            """,
            benchmark_date, category_id, metric_name,
            industry_avg, industry_top, shop_value, percentile, industry_rank,
            source, raw or {},
        )


async def upsert_batch(rows: list[dict[str, Any]]) -> int:
    """Bulk upsert. Each dict must have date, category_id, metric_name keys."""
    count = 0
    for row in rows:
        try:
            await upsert_benchmark(
                row["date"],
                row["category_id"],
                row["metric_name"],
                industry_avg=row.get("industry_avg"),
                industry_top=row.get("industry_top"),
                shop_value=row.get("shop_value"),
                percentile=row.get("percentile"),
                industry_rank=row.get("industry_rank"),
                source=row.get("source", "compass"),
                raw=row.get("raw"),
            )
            count += 1
        except Exception as exc:
            log.warning("benchmark upsert failed for %s/%s: %s",
                        row.get("category_id"), row.get("metric_name"), exc)
    return count
