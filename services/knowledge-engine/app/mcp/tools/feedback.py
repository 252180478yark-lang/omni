"""W4-A T2: rate_tool_call tool（W4-B T1 后内部委托 agent_log_service）。

design doc §7.4 反馈循环：
- 老板对历史 tool_call 打分（good/bad/redo）
- 写 mcp.tool_calls.user_rating + rating_note
- good → pattern_lib.append_successful_pattern
- bad/redo → pattern_lib.append_failed_pattern

F 类，不走 Human Gate（high-volume 操作）。

W4-B 重构：核心逻辑抽到 app.services.agent_log_service.rate_tool_call_logic，
给 REST router 与本 mcp tool 共用，避免重复。本 mcp tool 接口签名保持不变。
"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services.agent_log_service import rate_tool_call_logic

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def rate_tool_call(
    call_id: str,
    rating: str,
    note: str = "",
) -> dict:
    """对一个历史 tool_call 打分。

    Args:
        call_id: mcp.tool_calls.id（uuid str）
        rating: good | bad | redo
        note: 可选备注

    Returns:
        {ok, result: {call_id, rating, tool_name}}（出错时 {ok:false, error, hint}）
    """
    result = await rate_tool_call_logic(
        call_id=call_id, rating=rating, note=note,
    )
    if result.get("ok"):
        logger.info(
            "rate_tool_call call_id=%s rating=%s tool=%s",
            call_id[:8],
            rating,
            result["result"]["tool_name"],
        )
    return result
