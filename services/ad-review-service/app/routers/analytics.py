from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.database import get_pool

router = APIRouter(prefix="/api/v1/ad-review/analytics", tags=["ad-review-analytics"])


@router.get("/product-trend")
async def product_trend(product_id: str = Query(..., description="产品 UUID")):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.name, c.start_date, c.end_date, c.total_cost, c.status,
              (SELECT COALESCE(AVG(m.ctr), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_ctr,
              (SELECT COALESCE(AVG(m.cpm), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_cpm,
              (SELECT COALESCE(AVG(m.completion_rate), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_completion_rate
            FROM ad_review.campaigns c
            WHERE c.product_id = $1::uuid
            ORDER BY c.start_date ASC
            """,
            product_id,
        )
    return {"points": [dict(r) for r in rows]}


@router.get("/audience-compare")
async def audience_compare(cid: str = Query(..., alias="cid", description="投放批次 UUID")):
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow("SELECT id FROM ad_review.campaigns WHERE id = $1::uuid", cid)
        if not camp:
            raise HTTPException(status_code=404, detail="批次不存在")
        rows = await conn.fetch(
            """
            SELECT
              ap.id AS audience_pack_id,
              ap.name AS audience_name,
              COUNT(m.id)::int AS material_count,
              COALESCE(SUM(m.cost), 0) AS total_cost,
              COALESCE(AVG(m.ctr), 0) AS avg_ctr,
              COALESCE(AVG(m.completion_rate), 0) AS avg_completion_rate,
              COALESCE(AVG(m.play_3s_rate), 0) AS avg_play_3s_rate,
              COALESCE(AVG(m.cpm), 0) AS avg_cpm
            FROM ad_review.audience_packs ap
            LEFT JOIN ad_review.materials m ON m.audience_pack_id = ap.id
            WHERE ap.campaign_id = $1::uuid
            GROUP BY ap.id, ap.name
            ORDER BY ap.created_at
            """,
            cid,
        )
    return {"rows": [dict(r) for r in rows]}


@router.get("/flywheel")
async def flywheel_dashboard(product_id: str = Query(..., description="产品 UUID")):
    """飞轮仪表盘：同一产品多轮投放的核心指标对比，展示迭代改进效果。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              c.id,
              c.name,
              c.start_date,
              c.end_date,
              c.total_budget,
              c.total_cost,
              c.status,
              ROW_NUMBER() OVER (ORDER BY c.start_date ASC, c.created_at ASC) AS round_num,
              (SELECT COUNT(*)::int FROM ad_review.materials m WHERE m.campaign_id = c.id) AS material_count,
              (SELECT COUNT(*)::int FROM ad_review.audience_packs ap WHERE ap.campaign_id = c.id) AS audience_count,
              (SELECT COALESCE(AVG(m.ctr), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_ctr,
              (SELECT COALESCE(AVG(m.conversion_rate), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_cvr,
              (SELECT COALESCE(AVG(m.cpm), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_cpm,
              (SELECT COALESCE(AVG(m.completion_rate), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_completion_rate,
              (SELECT COALESCE(AVG(m.play_3s_rate), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_play_3s_rate,
              (SELECT COALESCE(AVG(m.interaction_rate), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS avg_interaction_rate,
              (SELECT COALESCE(SUM(m.cost), 0) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS sum_cost,
              (SELECT MAX(m.ctr) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS best_ctr,
              (SELECT MAX(m.conversion_rate) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS best_cvr,
              (SELECT COUNT(*)::int FROM ad_review.materials m WHERE m.campaign_id = c.id AND m.parent_material_id IS NOT NULL) AS iterated_material_count,
              rl.id AS review_id,
              rl.kb_synced_at,
              rl.kb_id,
              CASE WHEN rl.id IS NOT NULL THEN TRUE ELSE FALSE END AS has_review,
              CASE WHEN rl.kb_synced_at IS NOT NULL THEN TRUE ELSE FALSE END AS kb_synced
            FROM ad_review.campaigns c
            LEFT JOIN LATERAL (
              SELECT id, kb_synced_at, kb_id
              FROM ad_review.review_logs
              WHERE campaign_id = c.id
              ORDER BY updated_at DESC LIMIT 1
            ) rl ON TRUE
            WHERE c.product_id = $1::uuid
            ORDER BY c.start_date ASC, c.created_at ASC
            """,
            product_id,
        )
    points = [dict(r) for r in rows]

    # Compute round-over-round deltas
    for i, pt in enumerate(points):
        if i == 0:
            pt["ctr_delta"] = None
            pt["cvr_delta"] = None
            pt["cpm_delta"] = None
        else:
            prev = points[i - 1]
            prev_ctr = float(prev.get("avg_ctr") or 0)
            cur_ctr = float(pt.get("avg_ctr") or 0)
            pt["ctr_delta"] = ((cur_ctr - prev_ctr) / prev_ctr * 100) if prev_ctr > 0 else None

            prev_cvr = float(prev.get("avg_cvr") or 0)
            cur_cvr = float(pt.get("avg_cvr") or 0)
            pt["cvr_delta"] = ((cur_cvr - prev_cvr) / prev_cvr * 100) if prev_cvr > 0 else None

            prev_cpm = float(prev.get("avg_cpm") or 0)
            cur_cpm = float(pt.get("avg_cpm") or 0)
            pt["cpm_delta"] = ((cur_cpm - prev_cpm) / prev_cpm * 100) if prev_cpm > 0 else None

    return {"product_id": product_id, "rounds": points}


@router.get("/iteration-chain")
async def analytics_iteration(material_id: str = Query(..., description="素材 UUID")):
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow("SELECT * FROM ad_review.materials WHERE id = $1::uuid", material_id)
        if not cur:
            raise HTTPException(status_code=404, detail="素材不存在")
        chain_up: list = [dict(cur)]
        seen = {str(cur["id"])}
        while cur.get("parent_material_id"):
            pid = str(cur["parent_material_id"])
            if pid in seen:
                break
            parent = await conn.fetchrow("SELECT * FROM ad_review.materials WHERE id = $1::uuid", pid)
            if not parent:
                break
            chain_up.append(dict(parent))
            seen.add(pid)
            cur = parent
        chain_up.reverse()
    return {"chain": chain_up}
