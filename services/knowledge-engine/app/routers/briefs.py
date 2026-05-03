from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import briefs as svc

router = APIRouter(prefix="/api/v1/content-studio/briefs", tags=["content-studio-briefs"])


# ─────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────

class BriefCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    usp: str = Field(min_length=1)
    product_id: str | None = None
    product_name: str | None = None
    sku_id: str | None = None
    parent_brief_id: str | None = None
    scenarios: list[dict] = Field(default_factory=list)
    audience_profile: dict = Field(default_factory=dict)
    tone_style: dict = Field(default_factory=dict)
    source_notes: str | None = None
    dmp_sop: str | None = None
    target_purpose: str | None = None  # awareness / planting / conversion
    usp_explicit: list[dict] = Field(default_factory=list)
    usp_implicit: list[dict] = Field(default_factory=list)
    usp_unique: list[dict] = Field(default_factory=list)
    audience_content_preference: dict = Field(default_factory=dict)
    extra: dict = Field(default_factory=dict)


class BriefUpdateRequest(BaseModel):
    title: str | None = None
    usp: str | None = None
    scenarios: list[dict] | None = None
    audience_profile: dict | None = None
    tone_style: dict | None = None
    source_notes: str | None = None
    dmp_sop: str | None = None
    status: str | None = None
    target_purpose: str | None = None
    usp_explicit: list[dict] | None = None
    usp_implicit: list[dict] | None = None
    usp_unique: list[dict] | None = None
    audience_content_preference: dict | None = None
    sku_id: str | None = None
    extra: dict | None = None


class BriefMetricsRequest(BaseModel):
    ctr: float | None = None
    cvr: float | None = None
    samples: int | None = None
    quality_score: float | None = None
    review_summary: str | None = None


class BriefDeriveRequest(BaseModel):
    title: str | None = None
    usp: str | None = None
    scenarios: list[dict] | None = None
    audience_profile: dict | None = None
    tone_style: dict | None = None
    source_notes: str | None = None
    dmp_sop: str | None = None
    target_purpose: str | None = None
    usp_explicit: list[dict] | None = None
    usp_implicit: list[dict] | None = None
    usp_unique: list[dict] | None = None
    audience_content_preference: dict | None = None


class BriefGenerateRequest(BaseModel):
    product_id: str | None = None
    sku_id: str | None = None
    title: str | None = None
    target_purpose: str | None = None  # awareness / planting / conversion
    hints: dict = Field(default_factory=dict)


class DmpSopRequest(BaseModel):
    sop_text: str = Field(min_length=1)


# ─────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────

@router.post("")
async def create_brief(req: BriefCreateRequest):
    return await svc.create_brief(req.model_dump())


@router.get("")
async def list_briefs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    product_id: str | None = None,
    sku_id: str | None = None,
    status: str | None = None,
):
    items = await svc.list_briefs(
        limit, offset, product_id=product_id, sku_id=sku_id, status=status,
    )
    return {"items": items}


@router.post("/generate")
async def generate_brief(req: BriefGenerateRequest):
    return await svc.generate_draft(
        product_id=req.product_id,
        sku_id=req.sku_id,
        hints=req.hints,
        title=req.title,
        target_purpose=req.target_purpose,
    )


@router.get("/{brief_id}")
async def get_brief(brief_id: str):
    brief = await svc.get_brief(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")
    return brief


@router.put("/{brief_id}")
async def update_brief(brief_id: str, req: BriefUpdateRequest):
    brief = await svc.update_brief(brief_id, req.model_dump(exclude_none=True))
    if not brief:
        raise HTTPException(404, "Brief not found")
    return brief


@router.post("/{brief_id}/derive")
async def derive_brief(brief_id: str, req: BriefDeriveRequest):
    new_brief = await svc.derive_brief(brief_id, req.model_dump(exclude_none=True))
    if not new_brief:
        raise HTTPException(404, "Brief not found")
    return new_brief


@router.post("/{brief_id}/dmp-sop")
async def apply_dmp_sop(brief_id: str, req: DmpSopRequest):
    brief = await svc.apply_dmp_sop(brief_id, req.sop_text)
    if not brief:
        raise HTTPException(404, "Brief not found")
    return brief


@router.patch("/{brief_id}/metrics")
async def patch_metrics(brief_id: str, req: BriefMetricsRequest):
    payload = req.model_dump()
    brief = await svc.update_metrics(
        brief_id,
        ctr=payload.get("ctr"),
        cvr=payload.get("cvr"),
        samples=payload.get("samples"),
        quality_score=payload.get("quality_score"),
        review_summary=payload.get("review_summary"),
    )
    if not brief:
        raise HTTPException(404, "Brief not found")
    return brief


@router.get("/{brief_id}/pipelines")
async def list_brief_pipelines(brief_id: str):
    return {"items": await svc.list_pipelines_using(brief_id)}


@router.get("/{brief_id}/version-tree")
async def get_version_tree(brief_id: str):
    return await svc.list_version_tree(brief_id)


@router.delete("/{brief_id}")
async def delete_brief(brief_id: str):
    ok = await svc.delete_brief(brief_id)
    if not ok:
        raise HTTPException(404, "Brief not found")
    return {"deleted": True}
