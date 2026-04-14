from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.database import get_pool
from app.schemas import MaterialGroupCreate, MaterialGroupUpdate

router = APIRouter(prefix="/api/v1/ad-review", tags=["ad-review-groups"])


@router.get("/campaigns/{campaign_id}/groups")
async def list_groups(campaign_id: str, audience_pack_id: str | None = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if audience_pack_id:
            rows = await conn.fetch(
                "SELECT * FROM ad_review.material_groups WHERE campaign_id = $1::uuid AND audience_pack_id = $2::uuid ORDER BY created_at",
                campaign_id, audience_pack_id,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM ad_review.material_groups WHERE campaign_id = $1::uuid ORDER BY created_at",
                campaign_id,
            )
    return {"items": [dict(r) for r in rows]}


@router.post("/audiences/{audience_id}/groups")
async def create_group(audience_id: str, body: MaterialGroupCreate):
    pool = await get_pool()
    gid = uuid.uuid4()
    async with pool.acquire() as conn:
        aud = await conn.fetchrow(
            "SELECT id, campaign_id FROM ad_review.audience_packs WHERE id = $1::uuid",
            audience_id,
        )
        if not aud:
            raise HTTPException(status_code=404, detail="人群包不存在")
        await conn.execute(
            """
            INSERT INTO ad_review.material_groups (id, audience_pack_id, campaign_id, style_label, video_purpose, description)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6)
            """,
            gid, audience_id, str(aud["campaign_id"]),
            body.style_label.strip(), body.video_purpose, body.description,
        )
    return {"id": str(gid)}


@router.put("/groups/{group_id}")
async def update_group(group_id: str, body: MaterialGroupUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM ad_review.material_groups WHERE id = $1::uuid", group_id)
        if not row:
            raise HTTPException(status_code=404, detail="风格组不存在")
        await conn.execute(
            """
            UPDATE ad_review.material_groups SET
              style_label = COALESCE($2, style_label),
              video_purpose = COALESCE($3, video_purpose),
              description = COALESCE($4, description)
            WHERE id = $1::uuid
            """,
            group_id,
            body.style_label.strip() if body.style_label else None,
            body.video_purpose,
            body.description,
        )
    return {"ok": True}


@router.delete("/groups/{group_id}")
async def delete_group(group_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ad_review.materials SET group_id = NULL WHERE group_id = $1::uuid",
            group_id,
        )
        result = await conn.execute(
            "DELETE FROM ad_review.material_groups WHERE id = $1::uuid",
            group_id,
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="风格组不存在")
    return {"ok": True}
