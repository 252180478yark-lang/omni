"""
7-day post/pre window verification — runs nightly at 02:00.

For each change_event with verification_status='pending' that is ≥7 days old:
  1. Aggregate 4 core KPIs (gmv_paid, ctr, cvr, uv) in pre/post 7-day windows.
  2. Compute delta_pct per KPI.
  3. Determine verdict: positive / negative / neutral.
  4. Write mvp_verification row.
  5. Update change_event.verification_status = 'completed'.
  6. Update linked decision_log.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.database import get_pool

log = logging.getLogger(__name__)

KPI_METRICS = ["gmv_paid", "ctr", "cvr", "uv"]
DELTA_THRESHOLD = 10.0  # % change needed to count as improved/declined


async def run_pending_verifications() -> None:
    pool = await get_pool()
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=7)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, sku_id, executed_at, source_decision_log_id
            FROM mvp_change_event
            WHERE verification_status = 'pending'
              AND executed_at <= $1
            ORDER BY executed_at
            LIMIT 50
            """,
            cutoff,
        )

    log.info("verification: %d pending events to process", len(rows))
    for row in rows:
        try:
            await verify_one(dict(row))
        except Exception as exc:
            log.warning("verify_one failed for event %s: %s", row["id"], exc)


async def verify_one(event: dict) -> None:
    pool = await get_pool()
    executed_at: datetime = event["executed_at"]
    sku_id: str = event["sku_id"]
    event_id: int = event["id"]

    pre_start = executed_at - timedelta(days=7)
    pre_end = executed_at
    post_start = executed_at
    post_end = executed_at + timedelta(days=7)

    async with pool.acquire() as conn:
        # Check for confounding events in the post window
        other_events = await conn.fetchval(
            """
            SELECT COUNT(*) FROM mvp_change_event
            WHERE sku_id = $1
              AND id <> $2
              AND executed_at BETWEEN $3 AND $4
            """,
            sku_id, event_id, post_start, post_end,
        )

        pre_metrics = await _aggregate_window(conn, sku_id, pre_start, pre_end)
        post_metrics = await _aggregate_window(conn, sku_id, post_start, post_end)

    deltas: dict[str, dict] = {}
    for kpi in KPI_METRICS:
        pre_v = pre_metrics.get(kpi, 0.0)
        post_v = post_metrics.get(kpi, 0.0)
        delta_abs = post_v - pre_v
        delta_pct = (delta_abs / pre_v * 100) if pre_v else 0.0
        deltas[kpi] = {
            "pre": pre_v,
            "post": post_v,
            "delta_abs": delta_abs,
            "delta_pct": delta_pct,
        }

    if other_events > 0:
        verdict = "inconclusive"
    else:
        improved = sum(1 for d in deltas.values() if d["delta_pct"] >= DELTA_THRESHOLD)
        declined = sum(1 for d in deltas.values() if d["delta_pct"] <= -DELTA_THRESHOLD)
        if improved >= 3:
            verdict = "positive"
        elif declined >= 3:
            verdict = "negative"
        else:
            verdict = "neutral"

    summary = _build_summary(deltas, verdict)

    async with (await get_pool()).acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mvp_verification
                (change_event_id, pre_window_start, pre_window_end,
                 post_window_start, post_window_end, kpi_deltas, verdict, summary, confidence)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (change_event_id) DO UPDATE
            SET kpi_deltas=$6, verdict=$7, summary=$8, verified_at=NOW()
            """,
            event_id, pre_start, pre_end, post_start, post_end,
            deltas, verdict, summary, 0.8,
        )
        await conn.execute(
            "UPDATE mvp_change_event SET verification_status='completed' WHERE id=$1",
            event_id,
        )
        if event.get("source_decision_log_id"):
            await conn.execute(
                """
                UPDATE mvp_decision_log
                SET verification_result=$2, verified_at=NOW(), status='verified', updated_at=NOW()
                WHERE id=$1
                """,
                event["source_decision_log_id"],
                {"verdict": verdict, "deltas": deltas, "summary": summary},
            )

    log.info("verified event %d: verdict=%s", event_id, verdict)


async def _aggregate_window(conn, sku_id: str, start: datetime, end: datetime) -> dict[str, float]:
    rows = await conn.fetch(
        """
        SELECT metric_name, AVG(value)::float AS avg_val
        FROM mvp_daily_metric
        WHERE sku_id=$1 AND metric_name=ANY($2)
          AND date >= $3::date AND date < $4::date
          AND platform = 'douyin'
        GROUP BY metric_name
        """,
        sku_id, KPI_METRICS, start.date(), end.date(),
    )
    return {r["metric_name"]: r["avg_val"] for r in rows}


def _build_summary(deltas: dict, verdict: str) -> str:
    parts = []
    for kpi, d in deltas.items():
        sign = "+" if d["delta_pct"] >= 0 else ""
        parts.append(f"{kpi}: {sign}{d['delta_pct']:.1f}%")
    label = {"positive": "改善", "negative": "恶化", "neutral": "持平", "inconclusive": "不可归因"}
    return f"验证结论: {label.get(verdict, verdict)}  |  " + "  ".join(parts)
