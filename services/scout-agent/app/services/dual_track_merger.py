"""
dual_track_merger.py — 双轨动作日志合并器

Track A: User manually submits change events via POST /api/v1/scout/change-events
         (takes ≤60s, structured fields: sku_id, action_type, description, etc.)
Track B: Passive scraping from shop-admin action logs (runbook: g-action-log.yaml)
         raw rows land in mvp_change_event with source='scrape', merge_status='pending'

Merge logic:
  1. For each pending Track-B event, look for a matching Track-A event in a ±4h window
     on the same sku_id + action_type.  If found → deduplicate (keep Track-A, discard B).
  2. Remaining unmatched Track-B events → auto-promote to merge_status='promoted',
     source stays 'scrape', verified=FALSE.
  3. New Track-A events that arrived after last merge run → set merge_status='confirmed'.
  4. Write mvp_merge_run log row with counts.

Called by scheduler (daily 03:00) and by runbook action "run_dual_track_merge".
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.database import get_pool

log = logging.getLogger(__name__)

_DEDUP_WINDOW_HOURS = 4
_BATCH_SIZE = 500


async def merge_pending() -> dict:
    """
    Main entry point.  Returns summary dict with counts.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        # ── 1. Load pending scrape events (Track B) ───────────────────────────
        scrape_rows = await conn.fetch(
            """
            SELECT id, sku_id, COALESCE(action_type, action_subtype) AS action_key, executed_at
            FROM mvp_change_event
            WHERE source = 'scrape' AND merge_status = 'pending'
            ORDER BY executed_at
            LIMIT $1
            """,
            _BATCH_SIZE,
        )

        dedup_count = 0
        promote_count = 0

        for row in scrape_rows:
            window_start = row["executed_at"] - timedelta(hours=_DEDUP_WINDOW_HOURS)
            window_end = row["executed_at"] + timedelta(hours=_DEDUP_WINDOW_HOURS)
            action_key = row["action_key"]

            # Look for a matching manual Track-A event in the window
            match = await conn.fetchrow(
                """
                SELECT id FROM mvp_change_event
                WHERE source = 'manual'
                  AND sku_id = $1
                  AND COALESCE(action_type, action_subtype) = $2
                  AND executed_at BETWEEN $3 AND $4
                  AND merge_status != 'discarded'
                ORDER BY ABS(EXTRACT(EPOCH FROM (executed_at - $5))) ASC
                LIMIT 1
                """,
                row["sku_id"],
                action_key,
                window_start,
                window_end,
                row["executed_at"],
            )

            if match:
                # Duplicate found: discard the scrape event, link it to the manual one
                await conn.execute(
                    """
                    UPDATE mvp_change_event
                    SET merge_status = 'discarded',
                        merged_into  = $2,
                        updated_at   = NOW()
                    WHERE id = $1
                    """,
                    row["id"],
                    match["id"],
                )
                dedup_count += 1
            else:
                # No matching manual event → promote
                await conn.execute(
                    """
                    UPDATE mvp_change_event
                    SET merge_status = 'promoted',
                        updated_at   = NOW()
                    WHERE id = $1
                    """,
                    row["id"],
                )
                promote_count += 1

        # ── 2. Confirm new manual (Track A) events ────────────────────────────
        confirm_result = await conn.execute(
            """
            UPDATE mvp_change_event
            SET merge_status = 'confirmed',
                updated_at   = NOW()
            WHERE source = 'manual'
              AND merge_status = 'pending'
            """,
        )
        # asyncpg returns "UPDATE N" string
        confirm_count = int(confirm_result.split()[-1]) if confirm_result else 0

        # ── 3. Log this merge run ─────────────────────────────────────────────
        await conn.execute(
            """
            INSERT INTO mvp_merge_run
                (id, started_at, ended_at,
                 scrape_total, dedup_count, promote_count, confirm_count)
            VALUES ($1, $2, NOW(), $3, $4, $5, $6)
            """,
            run_id,
            started_at,
            len(scrape_rows),
            dedup_count,
            promote_count,
            confirm_count,
        )

    summary = {
        "run_id": run_id,
        "scrape_total": len(scrape_rows),
        "dedup_count": dedup_count,
        "promote_count": promote_count,
        "confirm_count": confirm_count,
    }
    log.info("dual_track_merge done: %s", summary)
    return summary
