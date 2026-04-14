from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.database import get_pool
from app.schemas import AudiencePackCreate, AudiencePackUpdate

from app.services.file_parser import extract_text

router = APIRouter(prefix="/api/v1/ad-review", tags=["ad-review-audiences"])


ALLOWED_EXTS = (".xlsx", ".xls", ".csv", ".doc", ".docx", ".pdf", ".txt")


def _safe_filename(name: str) -> str:
    base = os.path.basename(name) or "upload.bin"
    return base.replace("..", "_")[:255]


@router.get("/campaigns/{campaign_id}/audiences")
async def list_audiences(campaign_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow("SELECT id FROM ad_review.campaigns WHERE id = $1::uuid", campaign_id)
        if not camp:
            raise HTTPException(status_code=404, detail="批次不存在")
        rows = await conn.fetch(
            "SELECT * FROM ad_review.audience_packs WHERE campaign_id = $1::uuid ORDER BY created_at",
            campaign_id,
        )
    items = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except json.JSONDecodeError:
                d["tags"] = []
        items.append(d)
    return {"items": items}


@router.post("/campaigns/{campaign_id}/audiences")
async def create_audience(campaign_id: str, body: AudiencePackCreate):
    pool = await get_pool()
    aid = uuid.uuid4()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow("SELECT id FROM ad_review.campaigns WHERE id = $1::uuid", campaign_id)
        if not camp:
            raise HTTPException(status_code=404, detail="批次不存在")
        await conn.execute(
            """
            INSERT INTO ad_review.audience_packs
              (id, campaign_id, name, description, tags, targeting_method_text, audience_profile_text)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6, $7)
            """,
            aid,
            campaign_id,
            body.name.strip(),
            body.description or "",
            json.dumps(body.tags or []),
            body.targeting_method_text or "",
            body.audience_profile_text or "",
        )
    return {"id": str(aid)}


@router.put("/audiences/{audience_id}")
async def update_audience(audience_id: str, body: AudiencePackUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM ad_review.audience_packs WHERE id = $1::uuid", audience_id)
        if not row:
            raise HTTPException(status_code=404, detail="人群包不存在")
        tags_json = json.dumps(body.tags) if body.tags is not None else None
        await conn.execute(
            """
            UPDATE ad_review.audience_packs SET
              name = COALESCE($2, name),
              description = COALESCE($3, description),
              tags = COALESCE($4::jsonb, tags),
              targeting_method_text = COALESCE($5, targeting_method_text),
              audience_profile_text = COALESCE($6, audience_profile_text)
            WHERE id = $1::uuid
            """,
            audience_id,
            body.name.strip() if body.name else None,
            body.description,
            tags_json,
            body.targeting_method_text,
            body.audience_profile_text,
        )
    return {"ok": True}


@router.delete("/audiences/{audience_id}")
async def delete_audience(audience_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM ad_review.audience_packs WHERE id = $1::uuid", audience_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="人群包不存在")
    return {"ok": True}


@router.post("/audiences/{audience_id}/upload-profile")
async def upload_profile(audience_id: str, file: UploadFile = File(...)):
    pool = await get_pool()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"支持的文件格式：{', '.join(ALLOWED_EXTS)}")

    root = Path(settings.data_dir) / "audience_uploads" / audience_id
    root.mkdir(parents=True, exist_ok=True)
    fname = _safe_filename(file.filename or "profile.xlsx")
    path = root / fname
    path.write_bytes(data)
    rel = str(path.relative_to(Path(settings.data_dir)))

    extracted = extract_text(data, file.filename or "", context="人群画像")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM ad_review.audience_packs WHERE id = $1::uuid", audience_id)
        if not row:
            raise HTTPException(status_code=404, detail="人群包不存在")
        await conn.execute(
            "UPDATE ad_review.audience_packs SET audience_profile_file = $2, audience_profile_text = COALESCE(NULLIF($3, ''), audience_profile_text) WHERE id = $1::uuid",
            audience_id,
            rel,
            extracted,
        )
    return {"path": rel, "filename": fname, "extracted_text": extracted[:500]}


@router.post("/audiences/{audience_id}/upload-targeting")
async def upload_targeting(audience_id: str, file: UploadFile = File(...)):
    pool = await get_pool()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"支持的文件格式：{', '.join(ALLOWED_EXTS)}")

    root = Path(settings.data_dir) / "audience_uploads" / audience_id
    root.mkdir(parents=True, exist_ok=True)
    fname = _safe_filename(file.filename or "targeting.xlsx")
    path = root / fname
    path.write_bytes(data)
    rel = str(path.relative_to(Path(settings.data_dir)))

    extracted = extract_text(data, file.filename or "", context="圈包手法/定向策略")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM ad_review.audience_packs WHERE id = $1::uuid", audience_id)
        if not row:
            raise HTTPException(status_code=404, detail="人群包不存在")
        await conn.execute(
            "UPDATE ad_review.audience_packs SET targeting_method_file = $2, targeting_method_text = COALESCE(NULLIF($3, ''), targeting_method_text) WHERE id = $1::uuid",
            audience_id,
            rel,
            extracted,
        )
    return {"path": rel, "filename": fname, "extracted_text": extracted[:500]}
