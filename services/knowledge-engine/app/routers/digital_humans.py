from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import digital_humans as svc

router = APIRouter(prefix="/api/v1/content-studio/digital-humans", tags=["content-studio-digital-humans"])


# ─────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────

class DigitalHumanCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    seed_face_url: str = Field(min_length=1)
    face_urls: list[str] = Field(default_factory=list)
    gender: str | None = None
    age_range: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    identity_anchor: str | None = None
    source_pipeline_id: str | None = None
    source_scene_id: int | None = None
    extra: dict = Field(default_factory=dict)


class DigitalHumanUpdateRequest(BaseModel):
    name: str | None = None
    seed_face_url: str | None = None
    face_urls: list[str] | None = None
    gender: str | None = None
    age_range: str | None = None
    style_tags: list[str] | None = None
    identity_anchor: str | None = None
    status: str | None = None
    extra: dict | None = None


class DigitalHumanMetricsRequest(BaseModel):
    ctr: float | None = None
    cvr: float | None = None
    samples: int = 1
    quality_score: float | None = None


class DigitalHumanGenerateRequest(BaseModel):
    name: str = Field(min_length=1)
    appearance_desc: str = ""
    reference_images: list[str] = Field(default_factory=list)
    angles: list[str] | None = None
    gender: str | None = None
    age_range: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    identity_anchor: str | None = None


class DigitalHumanPromoteRequest(BaseModel):
    to_status: str | None = None  # 默认按状态机自动推进


class DigitalHumanPromoteFromPipelineRequest(BaseModel):
    pipeline_id: str
    character_name: str
    new_avatar_name: str


# ─────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────

@router.post("")
async def create_digital_human(req: DigitalHumanCreateRequest):
    payload = req.model_dump()
    if not payload.get("face_urls"):
        payload["face_urls"] = [payload["seed_face_url"]]
    return await svc.create_digital_human(payload)


@router.get("")
async def list_digital_humans(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    sort: str = "ctr",
):
    items = await svc.list_digital_humans(limit, offset, status=status, sort=sort)
    return {"items": items}


@router.post("/generate")
async def generate_avatar(req: DigitalHumanGenerateRequest):
    angles = tuple(req.angles) if req.angles else ("front", "45", "side", "half_body")
    try:
        return await svc.generate_from_refs(
            name=req.name,
            appearance_desc=req.appearance_desc,
            reference_images=req.reference_images,
            angles=angles,
            gender=req.gender,
            age_range=req.age_range,
            style_tags=req.style_tags,
            identity_anchor=req.identity_anchor,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/promote-from-pipeline")
async def promote_from_pipeline(req: DigitalHumanPromoteFromPipelineRequest):
    avatar = await svc.promote_from_pipeline(
        req.pipeline_id, req.character_name, req.new_avatar_name,
    )
    if not avatar:
        raise HTTPException(404, "Source character not found in pipeline")
    return avatar


@router.get("/{digital_human_id}")
async def get_digital_human(digital_human_id: str):
    dh = await svc.get_digital_human(digital_human_id)
    if not dh:
        raise HTTPException(404, "Digital human not found")
    return dh


@router.put("/{digital_human_id}")
async def update_digital_human(digital_human_id: str, req: DigitalHumanUpdateRequest):
    dh = await svc.update_digital_human(digital_human_id, req.model_dump(exclude_none=True))
    if not dh:
        raise HTTPException(404, "Digital human not found")
    return dh


@router.post("/{digital_human_id}/promote")
async def promote_avatar(digital_human_id: str, req: DigitalHumanPromoteRequest):
    try:
        dh = await svc.promote_digital_human(digital_human_id, req.to_status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not dh:
        raise HTTPException(404, "Digital human not found")
    return dh


@router.post("/{digital_human_id}/archive")
async def archive_avatar(digital_human_id: str):
    dh = await svc.archive_digital_human(digital_human_id)
    if not dh:
        raise HTTPException(404, "Digital human not found")
    return dh


@router.patch("/{digital_human_id}/metrics")
async def patch_metrics(digital_human_id: str, req: DigitalHumanMetricsRequest):
    payload = req.model_dump()
    dh = await svc.update_metrics(
        digital_human_id,
        ctr=payload.get("ctr"),
        cvr=payload.get("cvr"),
        samples=payload.get("samples", 1),
        quality_score=payload.get("quality_score"),
    )
    if not dh:
        raise HTTPException(404, "Digital human not found")
    return dh


@router.get("/{digital_human_id}/pipelines")
async def list_avatar_pipelines(digital_human_id: str):
    return {"items": await svc.list_pipelines_using(digital_human_id)}


@router.delete("/{digital_human_id}")
async def delete_digital_human(digital_human_id: str):
    try:
        ok = await svc.delete_digital_human(digital_human_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not ok:
        raise HTTPException(404, "Digital human not found")
    return {"deleted": True}
