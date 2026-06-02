"""W4-A T2: rate_tool_call tool（W4-B T1 后内部委托 agent_log_service）。

design doc §7.4 反馈循环：
- 老板对历史 tool_call 打分（good/bad/redo）
- 写 mcp.tool_calls.user_rating + rating_note (+ rating_category 自 migration 031)
- good → pattern_lib.append_successful_pattern
- bad/redo → pattern_lib.append_failed_pattern

F 类，不走 Human Gate（high-volume 操作）。

W4-B 重构：核心逻辑抽到 app.services.agent_log_service.rate_tool_call_logic，
给 REST router 与本 mcp tool 共用，避免重复。本 mcp tool 接口签名保持向后兼容。

2026-05-28 反馈飞轮地基（migration 031）：
- rate_tool_call 加 category 入参（负反馈归因分类，向后兼容可空）
- 新加 rate_message tool：对 AI 整条消息（不是 tool）做反馈，写 mcp.message_feedback
"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services.agent_log_service import (
    rate_message_logic,
    rate_tool_call_logic,
)

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def rate_tool_call(
    call_id: str,
    rating: str,
    note: str = "",
    category: str | None = None,
) -> dict:
    """对一个历史 tool_call 打分。

    Args:
        call_id: mcp.tool_calls.id（uuid str）
        rating: good | bad | redo
        note: 可选备注
        category: 负反馈归因分类（migration 031；可空，向后兼容）。建议集合：
            prompt_bad / tradeoff_wrong / factual_error / tone_off /
            wrong_tool / incomplete / other

    Returns:
        {ok, result: {call_id, rating, tool_name}}（出错时 {ok:false, error, hint}）
    """
    result = await rate_tool_call_logic(
        call_id=call_id, rating=rating, note=note, category=category,
    )
    if result.get("ok"):
        logger.info(
            "rate_tool_call call_id=%s rating=%s category=%s tool=%s",
            call_id[:8],
            rating,
            category,
            result["result"]["tool_name"],
        )
    return result


@tool_with_audit(mcp, require_approval=False)
async def rate_message(
    session_id: str,
    message_id: str,
    rating: str,
    category: str | None = None,
    note: str | None = None,
    message_text_snapshot: str | None = None,
    tool_use_ids: list[str] | None = None,
    client: str = "desktop",
) -> dict:
    """对 AI 整条消息（不是单个 tool）做反馈。

    session_id 接受两种：
    - mcp.agent_sessions.id（uuid 字符串）— 直接用
    - claude_session_id（文本）— 后端反查 agent_sessions.id

    rating ∈ {'good', 'bad'}；category 当 rating='bad' 时建议带，集合：
    prompt_bad / tradeoff_wrong / factual_error / tone_off / wrong_tool /
    incomplete / other

    同 session_id+message_id 已有记录则覆盖（UNIQUE 约束）— 用
    ON CONFLICT DO UPDATE。

    message_text_snapshot 客户端截到 ≤ 4KB（后端不强校验，但记录长度便于排查；
    超长落库且 warning 提示）。

    Returns:
        {ok:true, feedback_id, replaced:bool}（已有同 session+message 时 replaced=true）
        {ok:false, error, hint}
    """
    result = await rate_message_logic(
        session_id=session_id,
        message_id=message_id,
        rating=rating,
        category=category,
        note=note,
        message_text_snapshot=message_text_snapshot,
        tool_use_ids=tool_use_ids,
        client=client,
    )
    if result.get("ok"):
        logger.info(
            "rate_message session_id=%s msg_id=%s rating=%s category=%s replaced=%s",
            session_id[:12],
            message_id[:24],
            rating,
            category,
            result.get("replaced"),
        )
    return result
