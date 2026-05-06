"""W4-A T2: rate_tool_call tool。

design doc §7.4 反馈循环：
- 老板对历史 tool_call 打分（good/bad/redo）
- 写 mcp.tool_calls.user_rating + rating_note
- good → pattern_lib.append_successful_pattern
- bad/redo → pattern_lib.append_failed_pattern

F 类，不走 Human Gate（high-volume 操作）。
"""
from __future__ import annotations

import logging
import uuid

from app.database import get_pool
from app.mcp import pattern_lib
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp

logger = logging.getLogger(__name__)

_VALID_RATINGS = {"good", "bad", "redo"}


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
    if rating not in _VALID_RATINGS:
        return {
            "ok": False,
            "error": "invalid_rating",
            "hint": f"rating 必须是 {sorted(_VALID_RATINGS)} 之一",
        }

    try:
        call_uuid = uuid.UUID(call_id)
    except (ValueError, TypeError):
        return {
            "ok": False,
            "error": "invalid_call_id",
            "hint": "call_id 必须是 uuid 字符串",
        }

    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE mcp.tool_calls SET user_rating=$1, rating_note=$2 "
        "WHERE id=$3 RETURNING tool_name",
        rating,
        note,
        call_uuid,
    )
    if row is None:
        return {
            "ok": False,
            "error": "call_not_found",
            "hint": f"call_id={call_id} 不存在；用 SELECT id FROM mcp.tool_calls 查",
        }

    tool_name = row["tool_name"]
    if rating == "good":
        pattern_lib.append_successful_pattern(
            tool_call_id=call_id, tool_name=tool_name, note=note,
        )
    else:  # bad / redo
        pattern_lib.append_failed_pattern(
            tool_call_id=call_id, tool_name=tool_name, note=note,
        )

    logger.info("rate_tool_call call_id=%s rating=%s tool=%s",
                call_id[:8], rating, tool_name)
    return {
        "ok": True,
        "result": {
            "call_id": call_id,
            "rating": rating,
            "tool_name": tool_name,
        },
    }
