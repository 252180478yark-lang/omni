"""
SKU / change-event / decision-log endpoints.

GET  /skus                             — list all SKUs (with focus_pool filter)
GET  /skus/{sku_id}                    — single SKU detail
GET  /skus/{sku_id}/metrics            — daily metrics (last N days)
PATCH /skus/{sku_id}/lock              — toggle locked_by_user
GET  /change-events                    — list change events
POST /change-events                    — create Track-A event
GET  /decisions                        — list decision logs
PATCH /decisions/{id}                  — adopt / reject
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_pool

router = APIRouter()
log = logging.getLogger(__name__)


# ── SKUs ──────────────────────────────────────────────────────────────────────

@router.get("/skus")
async def list_skus(
    status: Optional[str] = None,
    focus_only: bool = False,
    growth_class: Optional[str] = None,
):
    pool = await get_pool()
    wheres = []
    params: list = []
    if status:
        params.append(status)
        wheres.append(f"status = ${len(params)}")
    if focus_only:
        wheres.append("in_focus_pool = TRUE")
    if growth_class:
        params.append(growth_class)
        wheres.append(f"growth_class = ${len(params)}")

    where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, name, category, douyin_product_id, status, growth_class,
                   platform_status, in_focus_pool, focus_reason, locked_by_user,
                   total_stock, available_stock, created_at, updated_at
            FROM mvp_sku
            {where_clause}
            ORDER BY in_focus_pool DESC, updated_at DESC
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.get("/skus/{sku_id}")
async def get_sku(sku_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM mvp_sku WHERE id=$1", sku_id)
    if not row:
        raise HTTPException(status_code=404, detail="SKU not found")
    return dict(row)


@router.get("/skus/{sku_id}/metrics")
async def get_sku_metrics(sku_id: str, days: int = 14, metric_names: Optional[str] = None):
    pool = await get_pool()
    params: list = [sku_id, days]
    name_filter = ""
    if metric_names:
        names = [n.strip() for n in metric_names.split(",") if n.strip()]
        if names:
            params.append(names)
            name_filter = f"AND metric_name = ANY(${len(params)})"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT date, metric_name, value, source_runbook
            FROM mvp_daily_metric
            WHERE sku_id = $1
              AND date >= CURRENT_DATE - ($2::int * INTERVAL '1 day')
              {name_filter}
            ORDER BY date DESC, metric_name
            """,
            *params,
        )
    return [dict(r) for r in rows]


class SkuLockRequest(BaseModel):
    locked: bool


@router.patch("/skus/{sku_id}/lock")
async def lock_sku(sku_id: str, body: SkuLockRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE mvp_sku SET locked_by_user=$2, updated_at=NOW() WHERE id=$1",
            sku_id, body.locked,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="SKU not found")
    return {"id": sku_id, "locked_by_user": body.locked}


class SkuOwnerInfoRequest(BaseModel):
    """老板视角字段：手填卖点 / 备注 / 价格区间 / 规格。"""
    owner_selling_points: Optional[list] = None  # [{text, category, priority}]
    owner_notes: Optional[str] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    specifications: Optional[str] = None  # 自由文本：500ml*2 / 外卖小包 10ml*10 ...


@router.patch("/skus/{sku_id}/owner-info")
async def update_owner_info(sku_id: str, body: SkuOwnerInfoRequest):
    """老板手填的卖点/备注/价格区间/规格——给内容编排器作为输入种子。"""
    import json as _json
    sets: list[str] = []
    vals: list = [sku_id]
    if body.owner_selling_points is not None:
        vals.append(_json.dumps(body.owner_selling_points, ensure_ascii=False))
        sets.append(f"owner_selling_points = ${len(vals)}::jsonb")
    if body.owner_notes is not None:
        vals.append(body.owner_notes)
        sets.append(f"owner_notes = ${len(vals)}")
    if body.price_min is not None:
        vals.append(body.price_min)
        sets.append(f"price_min = ${len(vals)}")
    if body.price_max is not None:
        vals.append(body.price_max)
        sets.append(f"price_max = ${len(vals)}")
    if body.specifications is not None:
        vals.append(body.specifications)
        sets.append(f"specifications = ${len(vals)}")
    if not sets:
        raise HTTPException(status_code=400, detail="empty payload")
    sets.append("updated_at = NOW()")

    sql = f"UPDATE mvp_sku SET {', '.join(sets)} WHERE id = $1 RETURNING *"
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *vals)
    if not row:
        raise HTTPException(status_code=404, detail="SKU not found")
    return dict(row)


# ── Change events (Track A) ───────────────────────────────────────────────────

class ChangeEventCreate(BaseModel):
    sku_id: Optional[str] = None
    asset_type: str
    action_type: Optional[str] = None
    action_subtype: Optional[str] = None
    change_description: str
    optimization_intent: Optional[str] = None
    expected_kpis: list = []
    executed_at: Optional[datetime] = None
    screenshot_path: Optional[str] = None
    notes: Optional[str] = None


@router.get("/change-events")
async def list_change_events(
    sku_id: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
):
    pool = await get_pool()
    wheres = ["ce.merge_status != 'discarded'"]
    params: list = []
    if sku_id:
        params.append(sku_id)
        wheres.append(f"ce.sku_id = ${len(params)}")
    if source:
        params.append(source)
        wheres.append(f"ce.source = ${len(params)}")
    params.append(limit)
    where_clause = "WHERE " + " AND ".join(wheres)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT ce.*, s.name AS sku_name
            FROM mvp_change_event ce
            LEFT JOIN mvp_sku s ON s.id = ce.sku_id
            {where_clause}
            ORDER BY executed_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/change-events", status_code=201)
async def create_change_event(body: ChangeEventCreate):
    pool = await get_pool()
    import json as _json
    executed_at = body.executed_at or datetime.utcnow()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mvp_change_event
                (sku_id, asset_type, action_type, action_subtype,
                 change_description, optimization_intent, expected_kpis,
                 executed_at, screenshot_path, notes,
                 source, merge_status, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'manual','pending',NOW())
            RETURNING id, executed_at
            """,
            body.sku_id, body.asset_type, body.action_type, body.action_subtype,
            body.change_description, body.optimization_intent,
            _json.dumps(body.expected_kpis),
            executed_at, body.screenshot_path, body.notes,
        )
    return {"id": row["id"], "executed_at": row["executed_at"], "source": "manual"}


# ── Decision logs ─────────────────────────────────────────────────────────────

@router.get("/decisions")
async def list_decisions(
    sku_id: Optional[str] = None,
    status: Optional[str] = None,
    source_module: Optional[str] = None,
    limit: int = 100,
):
    pool = await get_pool()
    wheres = []
    params: list = []
    if sku_id:
        params.append(sku_id)
        wheres.append(f"d.sku_id = ${len(params)}")
    if status:
        params.append(status)
        wheres.append(f"d.status = ${len(params)}")
    if source_module:
        params.append(source_module)
        wheres.append(f"d.source_module = ${len(params)}")
    params.append(limit)
    where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT d.*, s.name AS sku_name
            FROM mvp_decision_log d
            LEFT JOIN mvp_sku s ON s.id = d.sku_id
            {where_clause}
            ORDER BY d.created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [dict(r) for r in rows]


class DecisionCreate(BaseModel):
    source_module: str  # roundtable / chat / scout_anomaly / manual_diagnosis / ad_review / other
    source_run_id: Optional[str] = None
    sku_id: Optional[str] = None
    type: Optional[str] = None  # diagnosis / suggestion / anomaly / experiment
    title: str
    summary: Optional[str] = None
    full_content: Optional[str] = None
    status: str = "pending"
    meta: Optional[dict] = None


@router.post("/decisions", status_code=201)
async def create_decision(body: DecisionCreate):
    """Persist a decision record from chat / roundtable / manual diagnosis."""
    if body.source_module not in (
        "roundtable", "chat", "scout_anomaly", "manual_diagnosis",
        "ad_review", "strategy_archive", "other",
    ):
        raise HTTPException(status_code=400, detail="invalid source_module")
    if body.status not in (
        "pending", "adopted", "rejected", "postponed", "executing", "verified",
    ):
        raise HTTPException(status_code=400, detail="invalid status")

    import json as _json
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mvp_decision_log
                (source_module, source_run_id, sku_id, type,
                 title, summary, full_content, status, meta, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
            RETURNING id, created_at
            """,
            body.source_module, body.source_run_id, body.sku_id, body.type,
            body.title, body.summary, body.full_content, body.status,
            _json.dumps(body.meta or {}),
        )
    return {"id": row["id"], "created_at": row["created_at"], "status": body.status}


class DecisionPatch(BaseModel):
    status: str  # adopted / rejected / postponed / pending / executing / verified
    rejected_reason: Optional[str] = None
    postponed_until: Optional[str] = None  # YYYY-MM-DD
    linked_change_event_id: Optional[int] = None


@router.patch("/decisions/{decision_id}")
async def update_decision(decision_id: int, body: DecisionPatch):
    if body.status not in (
        "pending", "adopted", "rejected", "postponed", "executing", "verified",
    ):
        raise HTTPException(
            status_code=400,
            detail="status must be one of pending/adopted/rejected/postponed/executing/verified",
        )
    if body.status == "postponed" and not body.postponed_until:
        raise HTTPException(
            status_code=400,
            detail="postponed_until (YYYY-MM-DD) is required when status='postponed'",
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE mvp_decision_log
            SET status                 = $2,
                adopted_at             = CASE WHEN $2='adopted'   THEN NOW() ELSE adopted_at END,
                rejected_reason        = CASE WHEN $2='rejected'  THEN $3   ELSE rejected_reason END,
                postponed_until        = CASE WHEN $2='postponed' THEN $4::date ELSE postponed_until END,
                linked_change_event_id = COALESCE($5, linked_change_event_id),
                updated_at             = NOW()
            WHERE id=$1
            """,
            decision_id, body.status, body.rejected_reason,
            body.postponed_until, body.linked_change_event_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Decision not found")
    return {"id": decision_id, "status": body.status}


# ── Verification detail ───────────────────────────────────────────────────────

@router.get("/change-events/{event_id}/verification")
async def get_verification(event_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM mvp_verification WHERE change_event_id=$1", event_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Verification not available yet")
    return dict(row)


# ── Weekly review ─────────────────────────────────────────────────────────────

@router.get("/weekly-review")
async def get_weekly_review(weeks_ago: int = 0):
    """
    Returns aggregated data for the weekly review page:
    - verified events sorted by delta (this week or weeks_ago weeks back)
    - decision counts by status
    - AI hit rate breakdown
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Week boundaries (Mon–Sun)
        week_start_row = await conn.fetchrow(
            "SELECT DATE_TRUNC('week', NOW() - ($1 * INTERVAL '1 week'))::date AS ws",
            weeks_ago,
        )
        week_start = week_start_row["ws"]

        # Verified events this week with their verification results
        verified = await conn.fetch(
            """
            SELECT
                ce.id, ce.sku_id, ce.asset_type, ce.action_type,
                ce.change_description, ce.executed_at,
                s.name AS sku_name,
                v.verdict, v.kpi_deltas, v.summary AS verify_summary, v.verified_at
            FROM mvp_change_event ce
            JOIN mvp_verification v ON v.change_event_id = ce.id
            LEFT JOIN mvp_sku s ON s.id = ce.sku_id
            WHERE ce.executed_at >= $1
              AND ce.merge_status != 'discarded'
            ORDER BY
                CASE v.verdict WHEN 'positive' THEN 0 WHEN 'neutral' THEN 1
                               WHEN 'negative' THEN 2 ELSE 3 END,
                ce.executed_at DESC
            """,
            week_start,
        )

        # Decision counts
        counts = await conn.fetch(
            """
            SELECT status, COUNT(*) AS cnt
            FROM mvp_decision_log
            WHERE created_at >= $1
            GROUP BY status
            """,
            week_start,
        )

        # Anomaly count
        anomaly_count = await conn.fetchval(
            "SELECT COUNT(*) FROM mvp_anomaly WHERE detected_at >= $1", week_start
        )

    verdict_counts = {"positive": 0, "negative": 0, "neutral": 0, "inconclusive": 0}
    for row in verified:
        v = row["verdict"] or "inconclusive"
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    total_verified = len(verified)
    hit_rate = round(verdict_counts["positive"] / total_verified * 100, 1) if total_verified else 0

    status_counts = {r["status"]: r["cnt"] for r in counts}

    return {
        "week_start": str(week_start),
        "verified_events": [dict(r) for r in verified],
        "verdict_counts": verdict_counts,
        "hit_rate": hit_rate,
        "status_counts": status_counts,
        "anomaly_count": anomaly_count or 0,
        "total_verified": total_verified,
    }


# ── SKU 5A asset ─────────────────────────────────────────────────────────────

@router.get("/skus/{sku_id}/5a")
async def get_sku_5a(sku_id: str, days: int = 7):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date,
                   o_count, a1_aware, a2_appeal, a3_ask, a4_act, a5_advocate, total_5a,
                   a1_outperform_pct, a2_outperform_pct, a3_outperform_pct,
                   a4_outperform_pct, a5_outperform_pct,
                   o_industry_avg, a1_industry_avg, a2_industry_avg,
                   a3_industry_avg, a4_industry_avg, a5_industry_avg,
                   ai_summary
            FROM mvp_5a_asset_daily
            WHERE sku_id = $1
            ORDER BY date DESC
            LIMIT $2
            """,
            sku_id, days,
        )
    return [dict(r) for r in rows]


@router.get("/skus/{sku_id}/brand-mind")
async def get_sku_brand_mind(sku_id: str, days: int = 7):
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Try SKU-level first, fall back to brand-level
        rows = await conn.fetch(
            """
            SELECT date, brand_assoc_count, industry_share, industry_rank,
                   reputation, preference
            FROM mvp_brand_mind_daily
            WHERE sku_id = $1
            ORDER BY date DESC
            LIMIT $2
            """,
            sku_id, days,
        )
        if not rows:
            rows = await conn.fetch(
                """
                SELECT date, brand_assoc_count, industry_share, industry_rank,
                       reputation, preference
                FROM mvp_brand_mind_daily
                WHERE sku_id = ''
                ORDER BY date DESC
                LIMIT $1
                """,
                days,
            )
    return [dict(r) for r in rows]


# ── Strategy archive ──────────────────────────────────────────────────────────

class StrategyArchive(BaseModel):
    change_event_id: int
    label: str = "可复用策略"


@router.post("/strategies", status_code=201)
async def archive_strategy(body: StrategyArchive):
    """Mark a successful verified action as a reusable strategy in decision_log."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        event = await conn.fetchrow(
            "SELECT * FROM mvp_change_event WHERE id=$1", body.change_event_id
        )
        if not event:
            raise HTTPException(status_code=404, detail="Change event not found")
        row = await conn.fetchrow(
            """
            INSERT INTO mvp_decision_log
                (source_module, sku_id, type, title, summary, status, meta)
            VALUES ('strategy_archive', $1, 'strategy', $2, $3, 'adopted', $4)
            RETURNING id
            """,
            event["sku_id"],
            f"可复用策略：{event['change_description'][:80]}",
            body.label,
            {"change_event_id": body.change_event_id},
        )
    return {"strategy_id": row["id"]}
