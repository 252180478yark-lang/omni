"""REST router for Bug 记忆库 + 客户端日志 (Phase A+/A++, 2026-05-28).

5 endpoint:
- POST  /api/v1/mcp/client-logs/batch    批量客户端日志(IPC/fetch/spawn/error/etc)
- POST  /api/v1/mcp/bugs                 报告 bug 入记忆库(30 天内同 title 自动合并)
- GET   /api/v1/mcp/bugs                 查 bug 列表(unfixed_only / tags / limit)
- PATCH /api/v1/mcp/bugs/{bug_id}        更新 bug(fix_applied / root_cause / fix_recipe / add_tags / note_append)
- GET   /api/v1/mcp/bugs/inject-summary  渲染未修 bug 列表给 omni-desktop spawn claude 用

错误格式跟现有 router 一致:service 返 {ok:false, error, hint} 时 router 直接
JSONResponse 透传不被 FastAPI HTTPException 包成 {"detail":...}.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services import bug_memory_service as svc

router = APIRouter(prefix="/api/v1/mcp", tags=["bug-memory"])


# ─────────────────────────── schemas ───────────────────────────


class ClientLogEvent(BaseModel):
    """单条客户端日志事件.

    严格校验只走 client/event_type/severity 三个必填;其他字段 svc 内部松校验.
    """

    client: str
    event_type: str
    severity: str = "info"
    channel: str | None = None
    payload: dict | list | None = None
    result: dict | list | None = None
    duration_ms: int | None = None
    stack_trace: str | None = None
    session_id: str | None = None
    user_marked_bug: bool = False


class ClientLogBatchRequest(BaseModel):
    events: list[ClientLogEvent]


class ReportBugRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    symptom: str = Field(..., min_length=1)
    trigger_conditions: str | None = None
    root_cause: str | None = None
    fix_recipe: str | None = None
    client_log_ids: list[str] | None = None
    tags: list[str] | None = None


class UpdateBugRequest(BaseModel):
    fix_applied: bool | None = None
    root_cause: str | None = None
    fix_recipe: str | None = None
    add_tags: list[str] | None = None
    note_append: str | None = None


# ─────────────────────────── endpoints ───────────────────────────


@router.post("/client-logs/batch")
async def post_client_logs_batch(payload: ClientLogBatchRequest) -> dict:
    """批量插入 client_logs."""
    events_dict = [e.model_dump() for e in payload.events]
    result = await svc.insert_client_logs_batch(events_dict)
    if not result.get("ok"):
        return JSONResponse(content=result, status_code=400)
    return result


@router.post("/bugs")
async def post_bug(payload: ReportBugRequest) -> dict:
    """报告 bug 入记忆库(30 天内同 title 相似自动合并)."""
    result = await svc.insert_bug(
        title=payload.title,
        symptom=payload.symptom,
        trigger_conditions=payload.trigger_conditions,
        root_cause=payload.root_cause,
        fix_recipe=payload.fix_recipe,
        client_log_ids=payload.client_log_ids,
        tags=payload.tags,
        auto_dedupe=True,
    )
    if not result.get("ok"):
        return JSONResponse(content=result, status_code=400)
    return result


@router.get("/bugs")
async def get_bugs(
    unfixed_only: bool = Query(False),
    tags: str | None = Query(None, description="逗号分隔 tags 用 GIN 索引 && 查"),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """查 bug 列表(按 last_seen DESC)."""
    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    bugs = await svc.list_bugs(
        unfixed_only=unfixed_only, tags=tag_list, limit=limit,
    )
    return {"ok": True, "bugs": bugs, "count": len(bugs)}


@router.patch("/bugs/{bug_id}")
async def patch_bug(bug_id: str, payload: UpdateBugRequest) -> dict:
    """更新 bug.字段非 None 才更新."""
    result = await svc.update_bug(
        bug_id=bug_id,
        fix_applied=payload.fix_applied,
        root_cause=payload.root_cause,
        fix_recipe=payload.fix_recipe,
        add_tags=payload.add_tags,
        note_append=payload.note_append,
    )
    if not result.get("ok"):
        code = 404 if result.get("error") == "bug_not_found" else 400
        return JSONResponse(content=result, status_code=code)
    return result


@router.get("/bugs/inject-summary")
async def get_inject_summary(
    max_bugs: int = Query(10, ge=1, le=50),
) -> dict:
    """渲染未修 bug 列表给 omni-desktop spawn claude 用(--append-system-prompt).

    没未修 bug 返空字符串.
    """
    summary = await svc.get_unfixed_bug_summary_for_inject(max_bugs=max_bugs)
    return {"summary": summary, "length": len(summary)}
