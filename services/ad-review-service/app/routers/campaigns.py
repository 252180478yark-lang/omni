from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.database import get_pool
from app.schemas import CampaignCreate, CampaignUpdate

router = APIRouter(prefix="/api/v1/ad-review/campaigns", tags=["ad-review-campaigns"])


async def _resolve_product_id(
    conn,
    product_id: str | None,
    product_name: str,
    sku: str | None = None,
    price: float | None = None,
    margin_rate: float | None = None,
) -> uuid.UUID:
    name = product_name.strip()
    if product_id:
        row = await conn.fetchrow("SELECT id FROM ad_review.products WHERE id = $1::uuid", product_id)
        if row:
            # Update product fields if provided
            if sku is not None or price is not None or margin_rate is not None:
                await conn.execute(
                    """
                    UPDATE ad_review.products SET
                      sku = COALESCE($2, sku),
                      price = COALESCE($3, price),
                      margin_rate = COALESCE($4, margin_rate)
                    WHERE id = $1::uuid
                    """,
                    row["id"], sku, price, margin_rate,
                )
            return row["id"]
    row = await conn.fetchrow(
        "SELECT id FROM ad_review.products WHERE LOWER(TRIM(name)) = LOWER(TRIM($1))",
        name,
    )
    if row:
        # Update product fields if provided
        if sku is not None or price is not None or margin_rate is not None:
            await conn.execute(
                """
                UPDATE ad_review.products SET
                  sku = COALESCE($2, sku),
                  price = COALESCE($3, price),
                  margin_rate = COALESCE($4, margin_rate)
                WHERE id = $1::uuid
                """,
                row["id"], sku, price, margin_rate,
            )
        return row["id"]
    new_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO ad_review.products (id, name, sku, price, margin_rate) VALUES ($1::uuid, $2, $3, $4, $5)",
        new_id, name, sku, price, margin_rate,
    )
    return new_id


def _row(d) -> dict[str, Any]:
    return dict(d)


@router.get("")
async def list_campaigns(
    product_id: str | None = None,
    status: str | None = None,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    pool = await get_pool()
    clauses: list[str] = ["1=1"]
    args: list[Any] = []
    idx = 1
    if product_id:
        clauses.append(f"c.product_id = ${idx}::uuid")
        args.append(product_id)
        idx += 1
    if status:
        clauses.append(f"c.status = ${idx}")
        args.append(status)
        idx += 1
    if date_from:
        clauses.append(f"c.end_date >= ${idx}")
        args.append(date_from)
        idx += 1
    if date_to:
        clauses.append(f"c.start_date <= ${idx}")
        args.append(date_to)
        idx += 1

    where_sql = " AND ".join(clauses)
    sql = f"""
        SELECT c.*, p.name AS product_name,
          (SELECT COUNT(*)::int FROM ad_review.audience_packs ap WHERE ap.campaign_id = c.id) AS audience_count,
          (SELECT COUNT(*)::int FROM ad_review.materials m WHERE m.campaign_id = c.id) AS material_count,
          (SELECT MAX(m.ctr) FROM ad_review.materials m WHERE m.campaign_id = c.id) AS best_ctr
        FROM ad_review.campaigns c
        JOIN ad_review.products p ON p.id = c.product_id
        WHERE {where_sql}
        ORDER BY c.start_date DESC, c.created_at DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return {"items": [_row(r) for r in rows]}


@router.post("")
async def create_campaign(body: CampaignCreate):
    pool = await get_pool()
    cid = uuid.uuid4()
    async with pool.acquire() as conn:
        async with conn.transaction():
            pid = await _resolve_product_id(
                conn, body.product_id, body.product_name,
                sku=body.product_sku, price=body.product_price,
                margin_rate=body.product_margin_rate,
            )
            await conn.execute(
                """
                INSERT INTO ad_review.campaigns
                  (id, product_id, name, start_date, end_date, total_budget, status)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, 'draft')
                """,
                cid,
                pid,
                body.name.strip(),
                body.start_date,
                body.end_date,
                body.total_budget,
            )
    return {"id": str(cid)}


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow(
            """
            SELECT c.*, p.name AS product_name, p.sku AS product_sku,
                   p.price AS product_price, p.margin_rate AS product_margin_rate
            FROM ad_review.campaigns c
            JOIN ad_review.products p ON p.id = c.product_id
            WHERE c.id = $1::uuid
            """,
            campaign_id,
        )
        if not camp:
            raise HTTPException(status_code=404, detail="批次不存在")
        audiences = await conn.fetch(
            "SELECT * FROM ad_review.audience_packs WHERE campaign_id = $1::uuid ORDER BY created_at",
            campaign_id,
        )
        materials = await conn.fetch(
            "SELECT * FROM ad_review.materials WHERE campaign_id = $1::uuid ORDER BY created_at",
            campaign_id,
        )
        groups = await conn.fetch(
            "SELECT * FROM ad_review.material_groups WHERE campaign_id = $1::uuid ORDER BY created_at",
            campaign_id,
        )
        review = await conn.fetchrow(
            "SELECT * FROM ad_review.review_logs WHERE campaign_id = $1::uuid ORDER BY updated_at DESC LIMIT 1",
            campaign_id,
        )
    aud_list = []
    for a in audiences:
        d = _row(a)
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except json.JSONDecodeError:
                d["tags"] = []
        aud_list.append(d)
    mat_list = []
    for m in materials:
        d = _row(m)
        if isinstance(d.get("change_tags"), str):
            try:
                d["change_tags"] = json.loads(d["change_tags"])
            except json.JSONDecodeError:
                d["change_tags"] = []
        mat_list.append(d)
    grp_list = [_row(g) for g in groups]
    rev = _row(review) if review else None
    if rev and isinstance(rev.get("experience_tags"), str):
        try:
            rev["experience_tags"] = json.loads(rev["experience_tags"])
        except json.JSONDecodeError:
            rev["experience_tags"] = []
    return {
        "campaign": _row(camp),
        "audiences": aud_list,
        "materials": mat_list,
        "groups": grp_list,
        "review_log": rev,
    }


@router.put("/{campaign_id}")
async def update_campaign(campaign_id: str, body: CampaignUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM ad_review.campaigns WHERE id = $1::uuid", campaign_id)
        if not row:
            raise HTTPException(status_code=404, detail="批次不存在")
        await conn.execute(
            """
            UPDATE ad_review.campaigns SET
              name = COALESCE($2, name),
              start_date = COALESCE($3, start_date),
              end_date = COALESCE($4, end_date),
              total_budget = COALESCE($5, total_budget),
              total_cost = COALESCE($6, total_cost),
              status = COALESCE($7, status),
              updated_at = NOW()
            WHERE id = $1::uuid
            """,
            campaign_id,
            body.name.strip() if body.name else None,
            body.start_date,
            body.end_date,
            body.total_budget,
            body.total_cost,
            body.status,
        )
    return {"ok": True}


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM ad_review.campaigns WHERE id = $1::uuid", campaign_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="批次不存在")
    return {"ok": True}
