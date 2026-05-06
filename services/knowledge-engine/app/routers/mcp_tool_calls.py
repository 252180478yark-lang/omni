"""REST router for mcp.tool_calls (W4-B 切片 1).

3 endpoint：
- GET  /api/v1/mcp/tool-calls           列表 + 24h 概览
- GET  /api/v1/mcp/tool-calls/{id}      详情（带 args/result）
- POST /api/v1/mcp/tool-calls/{id}/rate 评分（写库 + pattern_lib 双写）

评分错误格式（invalid_rating / invalid_call_id / call_not_found）由 service layer
返 {ok:false, error:..., hint:...}；router 直接 JSONResponse 透传，不被 FastAPI
HTTPException(detail=...) 包成 {"detail":...} 影响前端解析。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.schemas.mcp_tool_calls import RateRequest
from app.services.agent_log_service import (
    get_tool_call,
    list_tool_calls,
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
    )
    if not result.get("ok"):
        code = 404 if result.get("error") == "call_not_found" else 400
        return JSONResponse(content=result, status_code=code)
    return result
