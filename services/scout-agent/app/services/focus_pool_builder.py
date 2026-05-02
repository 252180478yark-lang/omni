"""
focus_pool_builder.py — T11c

Rebuilds the focus pool every Sunday at 23:00.
Rules:
  - GMV TOP 5 (last 30 days gmv_paid)
  - Declining TOP 2 (3 consecutive days decline + 30-day YoY down)
  - New products TOP 2 (created_on_platform_at ≤ 30 days, ranked by today's traffic)
  - User-locked ≤ 5 (locked_by_user=TRUE, always included)

Writes in_focus_pool + focus_reason to mvp_sku.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.database import get_pool

log = logging.getLogger(__name__)


async def rebuild_focus_pool() -> None:
    pool = await get_pool()
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    async with pool.acquire() as conn:
        # 1. GMV TOP 5
        top_gmv = await conn.fetch(
            """
            SELECT dm.sku_id, SUM(dm.value) AS total_gmv
            FROM mvp_daily_metric dm
            JOIN mvp_sku s ON s.id = dm.sku_id
            WHERE dm.metric_name = 'gmv_paid'
              AND dm.date >= $1
              AND s.status = 'active'
            GROUP BY dm.sku_id
            ORDER BY total_gmv DESC
            LIMIT 5
            """,
            thirty_days_ago,
        )
        top_gmv_ids = {r["sku_id"]: "top_gmv" for r in top_gmv}

        # 2. Declining TOP 2
        declining = await conn.fetch(
            """
            SELECT id FROM mvp_sku
            WHERE growth_class = 'declining' AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 2
            """
        )
        declining_ids = {r["id"]: "declining" for r in declining}

        # 3. New products TOP 2
        new_skus = await conn.fetch(
            """
            SELECT s.id
            FROM mvp_sku s
            LEFT JOIN mvp_daily_metric dm
                   ON dm.sku_id = s.id AND dm.metric_name = 'uv' AND dm.date = $1
            WHERE s.created_on_platform_at >= $2
              AND s.status = 'active'
            ORDER BY COALESCE(dm.value, 0) DESC
            LIMIT 2
            """,
            today - timedelta(days=1), thirty_days_ago,
        )
        new_ids = {r["id"]: "new" for r in new_skus}

        # 4. User-locked (max 5)
        locked = await conn.fetch(
            "SELECT id FROM mvp_sku WHERE locked_by_user = TRUE AND status = 'active' LIMIT 5"
        )
        locked_ids = {r["id"]: "locked" for r in locked}

        # Merge (locked can overlap with others, keep 'locked' label if so)
        pool_map: dict[str, str] = {**top_gmv_ids, **declining_ids, **new_ids, **locked_ids}

        # Fallback: if no rule fired (cold start — gmv_paid not yet collected
        # at SKU level, no declining/new tags, no user lock), seed the pool with
        # SKUs flagged 'excellent' by 抖店后台 g-list growth diagnosis. This
        # unblocks foreach_focus_skus runbooks on day 1.
        if not pool_map:
            excellent = await conn.fetch(
                """
                SELECT id FROM mvp_sku
                WHERE growth_class = 'excellent' AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 5
                """
            )
            pool_map = {r["id"]: "excellent_seed" for r in excellent}

        # Reset all
        await conn.execute("UPDATE mvp_sku SET in_focus_pool=FALSE, focus_reason=NULL")

        # Set focus pool
        for sku_id, reason in pool_map.items():
            await conn.execute(
                "UPDATE mvp_sku SET in_focus_pool=TRUE, focus_reason=$2 WHERE id=$1",
                sku_id, reason,
            )

    log.info("focus_pool rebuilt: %d SKUs  (%s)", len(pool_map), list(pool_map.items())[:5])
