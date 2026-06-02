"""REST router for mcp.tool_calls (W4-B 切片 1).

3 endpoint：
- GET  /api/v1/mcp/tool-calls           列表 + 24h 概览
- GET  /api/v1/mcp/tool-calls/{id}      详情（带 args/result）
- POST /api/v1/mcp/tool-calls/{id}/rate 评分（写库 + pattern_lib 双写）

2026-05-28 反馈飞轮地基（migration 031）：
- 原 /tool-calls/{id}/rate 加 category 入参（向后兼容，不传 = None）
- 新加 POST /api/v1/mcp/messages/rate：对 AI 整条消息打分（直接调
  rate_message_logic 透传）

评分错误格式（invalid_rating / invalid_call_id / call_not_found 等）由 service layer
返 {ok:false, error:..., hint:...}；router 直接 JSONResponse 透传，不被 FastAPI
HTTPException(detail=...) 包成 {"detail":...} 影响前端解析。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.database import get_pool
from app.schemas.mcp_tool_calls import (
    MessageRateRequest,
    RateRecentRequest,
    RateRequest,
)
from app.services.agent_log_service import (
    get_tool_call,
    list_tool_calls,
    rate_message_logic,
    rate_tool_call_logic,
)

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-tool-calls"])


@router.get("/tool-calls")
async def list_calls(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    tool_name: str | None = None,
    since_hours: int = Query(168, ge=1, le=720),
) -> dict:
    return await list_tool_calls(
        limit=limit,
        offset=offset,
        status=status_filter,
        tool_name=tool_name,
        since_hours=since_hours,
    )


@router.get("/tool-calls/{call_id}")
async def get_call(call_id: str) -> dict:
    row = await get_tool_call(call_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tool_call {call_id} 不存在",
        )
    return {"data": row}


@router.post("/tool-calls/{call_id}/rate")
async def rate_call(call_id: str, payload: RateRequest):
    result = await rate_tool_call_logic(
        call_id=call_id,
        rating=payload.rating,
        note=payload.note,
        category=payload.category,
    )
    if not result.get("ok"):
        code = 404 if result.get("error") == "call_not_found" else 400
        return JSONResponse(content=result, status_code=code)
    return result


@router.post("/tool-calls/rate-recent")
async def rate_recent_call(payload: RateRecentRequest):
    """按 tool_name 评"最近一条"调用（桌面工具块 👍👎 入口）。

    解析策略：取该 tool_name 在 within_minutes 内**最近的一条**，优先未评分的
    （已评的会被覆盖，但优先挑没评过的，避免反复评同一条老的）。解析到 call_id 后
    走标准 rate_tool_call_logic，user_rating + rating_category 落 mcp.tool_calls，
    feedback_digest cron 的工具级聚类就能吃到。
    """
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id::text AS id
        FROM mcp.tool_calls
        WHERE tool_name = $1
          AND created_at > NOW() - make_interval(mins => $2)
        ORDER BY (user_rating IS NULL) DESC, created_at DESC
        LIMIT 1
        """,
        payload.tool_name, payload.within_minutes,
    )
    if not row:
        return JSONResponse(
            content={
                "ok": False,
                "error": "no_recent_call",
                "hint": f"{payload.within_minutes} 分钟内没有 {payload.tool_name} 的调用记录可评",
            },
            status_code=404,
        )
    result = await rate_tool_call_logic(
        call_id=row["id"],
        rating=payload.rating,
        note=payload.note,
        category=payload.category,
    )
    if not result.get("ok"):
        code = 404 if result.get("error") == "call_not_found" else 400
        return JSONResponse(content=result, status_code=code)
    return result


@router.post("/messages/rate")
async def rate_message_endpoint(payload: MessageRateRequest):
    """对 AI 整条消息打分（migration 031）— 直接调 rate_message_logic 透传。"""
    result = await rate_message_logic(
        session_id=payload.session_id,
        message_id=payload.message_id,
        rating=payload.rating,
        category=payload.category,
        note=payload.note,
        message_text_snapshot=payload.message_text_snapshot,
        tool_use_ids=payload.tool_use_ids,
        client=payload.client,
    )
    if not result.get("ok"):
        code = 404 if result.get("error") == "session_not_found" else 400
        return JSONResponse(content=result, status_code=code)
    return result
