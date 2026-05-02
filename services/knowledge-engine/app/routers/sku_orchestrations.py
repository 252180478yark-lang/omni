"""SKU 内容编排 API — 暴露 17 步状态机给前端。

主要 endpoints：
  POST   /api/v1/content-studio/sku-orchestrations              新建编排
  GET    /api/v1/content-studio/sku-orchestrations              列表（可按 sku_id 过滤）
  GET    /api/v1/content-studio/sku-orchestrations/{id}         详情
  POST   /api/v1/content-studio/sku-orchestrations/{id}/run     跑当前步
  POST   /api/v1/content-studio/sku-orchestrations/{id}/run/{step}  跑指定步（支持单点重跑）
  POST   /api/v1/content-studio/sku-orchestrations/{id}/advance 一直跑到完成/失败
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import sku_orchestrator as svc

router = APIRouter(
    prefix="/api/v1/content-studio/sku-orchestrations",
    tags=["content-studio-sku-orchestrations"],
)


class CreateOrchestrationRequest(BaseModel):
    sku_id: str = Field(min_length=1)
    title: str | None = None
    target_purpose: str | None = Field(
        default=None,
        description="awareness 曝光 / planting 种草 / conversion 收割。留空则在 purpose_routing 步由 LLM 推荐。",
    )


@router.post("")
async def create(req: CreateOrchestrationRequest):
    try:
        return await svc.create_orchestration(
            sku_id=req.sku_id,
            title=req.title,
            target_purpose=req.target_purpose,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("")
async def list_all(
    sku_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items = await svc.list_orchestrations(sku_id=sku_id, limit=limit, offset=offset)
    return {"items": items}


@router.get("/{orch_id}")
async def detail(orch_id: str):
    orch = await svc.get_orchestration(orch_id)
    if not orch:
        raise HTTPException(404, "Orchestration not found")
    return orch


@router.post("/{orch_id}/run")
async def run_current(orch_id: str):
    """跑当前 current_step。"""
    try:
        return await svc.run_step(orch_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{orch_id}/run/{step}")
async def run_specific(orch_id: str, step: str):
    """跑指定步（单点重跑用）。step 必须是 STEPS_ORDER 中的合法名。"""
    if step not in svc.STEP_FN_MAP:
        raise HTTPException(400, f"invalid step: {step}")
    try:
        return await svc.run_step(orch_id, step)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{orch_id}/advance")
async def advance(orch_id: str):
    """从 current_step 一路跑到 completed 或 failed。"""
    try:
        return await svc.advance(orch_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
