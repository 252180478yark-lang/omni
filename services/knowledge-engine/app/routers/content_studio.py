"""Content Studio router — /api/v1/content-studio/*"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services import content_studio as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/content-studio", tags=["content-studio"])


# ──── Request / Response schemas ────

class CreatePipelineRequest(BaseModel):
    title: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    config: dict = Field(default_factory=dict)

class UpdatePipelineRequest(BaseModel):
    copy_result: str | None = None
    script_result: dict | None = None
    config: dict | None = None

class RegenerateSceneRequest(BaseModel):
    scene_id: int
    prompt_override: str | None = Field(
        default=None,
        description="If provided, skip LLM prompt transformation and use this prompt directly",
    )

class PresetCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    config: dict = Field(default_factory=dict)

class EstimateRequest(BaseModel):
    scene_count: int = Field(ge=1, le=20)
    avg_duration: int = Field(default=5, ge=1, le=15)

class ProductImagesRequest(BaseModel):
    image_urls: list[str] = Field(min_length=1)

class ImportScriptRequest(BaseModel):
    script: dict = Field(...)

class UpdateCharacterRequest(BaseModel):
    character_id: str
    face_url: str | None = None
    virtual_avatar_id: str | None = None  # Seedance asset ID, e.g. "asset-20260401123823-6d4x2"
    appearance: str | None = None

class AutoRunRequest(BaseModel):
    skip_copy: bool = False
    skip_script: bool = False
    wait_videos: bool = True
    auto_compose: bool = True


# ──── Pipeline CRUD ────

@router.post("/pipelines")
async def create_pipeline(req: CreatePipelineRequest):
    pipe = await svc.create_pipeline(req.title, req.source_text, req.config)
    return _serialize(pipe)


@router.get("/pipelines")
async def list_pipelines(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    rows = await svc.list_pipelines(limit, offset)
    return {"pipelines": [_serialize(r) for r in rows]}


@router.get("/pipeline/{pipeline_id}")
async def get_pipeline(pipeline_id: str):
    pipe = await svc.get_pipeline(pipeline_id)
    if not pipe:
        raise HTTPException(404, "Pipeline not found")
    return _serialize(pipe)


@router.put("/pipeline/{pipeline_id}")
async def update_pipeline(pipeline_id: str, req: UpdatePipelineRequest):
    fields = {}
    if req.copy_result is not None:
        fields["copy_result"] = req.copy_result
    if req.script_result is not None:
        fields["script_result"] = req.script_result
    if req.config is not None:
        fields["config"] = req.config
    if not fields:
        raise HTTPException(400, "No fields to update")
    pipe = await svc.update_pipeline(pipeline_id, **fields)
    if not pipe:
        raise HTTPException(404, "Pipeline not found")
    return _serialize(pipe)


@router.delete("/pipeline/{pipeline_id}")
async def delete_pipeline(pipeline_id: str):
    ok = await svc.delete_pipeline(pipeline_id)
    if not ok:
        raise HTTPException(404, "Pipeline not found")
    return {"deleted": True}


# ──── Product images & script import ────

@router.put("/pipeline/{pipeline_id}/product-images")
async def set_product_images(pipeline_id: str, req: ProductImagesRequest):
    """Upload product white-background image URLs for consistency across all scenes."""
    try:
        pipe = await svc.set_product_images(pipeline_id, req.image_urls)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/script/import")
async def import_script(pipeline_id: str = Query(...), req: ImportScriptRequest = ...):
    """Import a script generated externally (e.g. from knowledge Q&A module)."""
    try:
        pipe = await svc.import_script(pipeline_id, req.script)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ──── Script analysis & character generation ────

@router.post("/analyze")
async def step_analyze(pipeline_id: str = Query(...)):
    """Analyze the script to extract characters and product appearances."""
    try:
        pipe = await svc.analyze_script(pipeline_id)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/characters/generate")
async def step_character_faces(pipeline_id: str = Query(...)):
    """Generate consistent character portrait reference images."""
    try:
        pipe = await svc.generate_character_faces(pipeline_id)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/pipeline/{pipeline_id}/character")
async def update_character(pipeline_id: str, req: UpdateCharacterRequest):
    """Manually update a character's face URL or appearance description."""
    pipe = await svc.get_pipeline(pipeline_id)
    if not pipe:
        raise HTTPException(404, "Pipeline not found")
    profiles = pipe.get("character_profiles")
    if isinstance(profiles, str):
        profiles = json.loads(profiles)
    if not profiles:
        raise HTTPException(400, "No character profiles found")

    found = False
    for p in profiles:
        if p["id"] == req.character_id:
            if req.virtual_avatar_id is not None:
                p["face_url"] = f"asset://{req.virtual_avatar_id}"
                p["is_virtual_avatar"] = True
            elif req.face_url is not None:
                p["face_url"] = req.face_url
                p["is_virtual_avatar"] = False
            if req.appearance is not None:
                p["appearance"] = req.appearance
            found = True
            break
    if not found:
        raise HTTPException(404, f"Character {req.character_id} not found")

    result = await svc.update_pipeline(pipeline_id, character_profiles=profiles)
    return _serialize(result)


# ──── Prompt preview — review before generating ────

@router.post("/storyboard/preview-prompts")
async def preview_storyboard_prompts(pipeline_id: str = Query(...)):
    """Preview image-gen prompts for all scenes WITHOUT actually generating images.

    Use this to inspect the prompts before running /storyboard.
    If any prompt looks wrong, you can fix the scene description
    or character profile first, then re-preview.
    """
    try:
        previews = await svc.preview_storyboard_prompts(pipeline_id)
        return {"pipeline_id": pipeline_id, "previews": previews}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/video/preview-prompts")
async def preview_video_prompts(pipeline_id: str = Query(...)):
    """Preview video-gen prompts and reference images for all scenes
    WITHOUT actually generating videos.

    Use this to inspect prompts after storyboard is done.
    If a prompt is wrong, fix the scene or character profile first.
    """
    try:
        previews = await svc.preview_video_prompts(pipeline_id)
        return {"pipeline_id": pipeline_id, "previews": previews}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ──── Step executors ────

@router.post("/copy")
async def step_copy(pipeline_id: str = Query(...)):
    try:
        pipe = await svc.generate_copy(pipeline_id)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/script")
async def step_script(pipeline_id: str = Query(...)):
    try:
        pipe = await svc.generate_script(pipeline_id)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/storyboard")
async def step_storyboard(pipeline_id: str = Query(...)):
    try:
        pipe = await svc.generate_storyboard(pipeline_id)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/storyboard/regenerate")
async def regenerate_storyboard(pipeline_id: str = Query(...), req: RegenerateSceneRequest = ...):
    try:
        pipe = await svc.regenerate_storyboard_scene(
            pipeline_id, req.scene_id, prompt_override=req.prompt_override,
        )
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/video")
async def step_video(pipeline_id: str = Query(...)):
    try:
        pipe = await svc.generate_videos(pipeline_id)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/video/regenerate")
async def regenerate_video(pipeline_id: str = Query(...), req: RegenerateSceneRequest = ...):
    try:
        pipe = await svc.regenerate_video_scene(
            pipeline_id, req.scene_id, prompt_override=req.prompt_override,
        )
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/compose")
async def step_compose(pipeline_id: str = Query(...)):
    try:
        pipe = await svc.compose_final_video(pipeline_id)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ──── Downloads ────

@router.get("/download/{pipeline_id}")
async def download_zip(pipeline_id: str):
    zip_path = await svc.build_download_zip(pipeline_id)
    if not zip_path or not zip_path.exists():
        raise HTTPException(404, "Download not available")
    return FileResponse(str(zip_path), media_type="application/zip",
                        filename=f"content-studio-{pipeline_id[:8]}.zip")


@router.get("/download/{pipeline_id}/{filename}")
async def download_file(pipeline_id: str, filename: str):
    file_path = svc.get_file_path(pipeline_id, filename)
    if not file_path:
        raise HTTPException(404, "File not found")
    return FileResponse(str(file_path), filename=filename)


# ──── Presets ────

@router.get("/presets")
async def get_presets():
    presets = await svc.list_presets()
    return {"presets": [_serialize(p) for p in presets]}


@router.post("/presets")
async def create_preset(req: PresetCreateRequest):
    preset = await svc.create_preset(req.name, req.description, req.config)
    return _serialize(preset)


# ──── Convenience shortcuts (optional, step-by-step is recommended) ────

@router.post("/auto-run")
async def auto_run(pipeline_id: str = Query(...), req: AutoRunRequest = AutoRunRequest()):
    """OPTIONAL shortcut: execute remaining steps automatically.

    ⚠️ Recommended workflow is step-by-step with manual review between steps.
    Only use auto-run for quick previews or when all intermediate results
    have already been reviewed.
    """
    try:
        pipe = await svc.auto_run(
            pipeline_id,
            skip_copy=req.skip_copy,
            skip_script=req.skip_script,
            wait_videos=req.wait_videos,
            auto_compose=req.auto_compose,
        )
        return _serialize(pipe)
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/video/poll-all")
async def poll_all_videos(pipeline_id: str = Query(...)):
    """Wait for all video tasks in a pipeline to complete."""
    try:
        pipe = await svc.poll_all_videos(pipeline_id)
        return _serialize(pipe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ──── Cost estimation ────

@router.post("/estimate")
async def cost_estimate(req: EstimateRequest):
    return svc.estimate_cost(req.scene_count, req.avg_duration)


# ──── Helpers ────

def _serialize(obj: dict) -> dict:
    result = {}
    for k, v in obj.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        elif isinstance(v, (bytes, memoryview)):
            continue
        elif hasattr(v, "__str__") and type(v).__name__ == "UUID":
            result[k] = str(v)
        else:
            result[k] = v
    return result
