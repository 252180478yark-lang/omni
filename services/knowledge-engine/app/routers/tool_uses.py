"""tool_use_id 焊归因链 REST router（蓝图 §3 地基 / 阶段0 块2 · 设计草案方案 A）。

背景：MCP stdio 协议层不透传 Claude 的 tool_use_id（toolu_xxxxx），KE 的 audit.py 自造
gen_random_uuid()，两个 ID 空间互不相识 → "差评→哪次调用→哪段 prompt" join 不通。
migration 035 已给 mcp.tool_calls 加好 tool_use_id + claude_session_id 列（接收侧坑挖好）。

本 router 落地**传递方案 A**（客户端侧 join，零侵入 MCP 协议）：
- 前端 runner 解析 stream-json 时能同时看到 (claude_session_id, tool_use_id, tool_name)，
  在一轮 task_done（所有 tool 已执行完、KE 的 tool_calls 行已落库）时批量 POST 这里。
- KE 按 tool_name + 时间窗，把每个 tool_use_id 回填到**最早一条尚未焊接**的 tool_calls 行
  （单人场景几乎无并发，对齐可靠；同名多次调用按 created_at 升序逐一配对）。

不走 Human Gate（高频被动焊接，无副作用、纯回填空列）。fail-open：匹配不到不报错。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.database import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mcp/tool-uses", tags=["mcp-tool-uses"])


class ToolUseLink(BaseModel):
    tool_use_id: str
    tool_name: str
    claude_session_id: str | None = None


class ToolUseLinkBatch(BaseModel):
    items: list[ToolUseLink]
    # 时间窗：一轮对话通常 <1min，回填在 task_done 即发。窗收到 15min（容网络延迟，
    # 又压低跨轮错配概率）。注：tool_calls 行被焊接前 claude_session_id 为 NULL，无法在
    # WHERE 里按 session 隔离候选行，故这是方案A的"时间窗+tool_name 近似"匹配（单人场景几乎
    # 无并发；要强一致用方案C 离线解析 jsonl 补，见设计草案 §2.3.2）。
    within_minutes: int = 15


@router.post("/link")
async def link_tool_uses(payload: ToolUseLinkBatch) -> dict:
    """把一批 (tool_use_id, tool_name) 回填到最近未焊接的 mcp.tool_calls 行。

    返 {ok, linked, unmatched, total}。unmatched = 时间窗内找不到同名未焊接调用的条数
    （正常情况应接近 0；偏高说明窗口太小或 tool_name 对不上，可观测调参）。
    """
    pool = get_pool()
    linked = 0
    unmatched = 0
    items = payload.items or []
    # 去重：同一 tool_use_id 多次提交只焊一次（前端可能重发）
    seen: set[str] = set()
    for it in items:
        if not it.tool_use_id or it.tool_use_id in seen:
            continue
        seen.add(it.tool_use_id)
        # 该 tool_use_id 若已焊过（幂等重跑），跳过
        exists = await pool.fetchval(
            "SELECT 1 FROM mcp.tool_calls WHERE tool_use_id = $1 LIMIT 1",
            it.tool_use_id,
        )
        if exists:
            linked += 1
            continue
        try:
            row = await pool.fetchrow(
                """
                WITH target AS (
                    SELECT id FROM mcp.tool_calls
                    WHERE tool_name = $1
                      AND tool_use_id IS NULL
                      AND created_at > NOW() - make_interval(mins => $4)
                    ORDER BY created_at ASC
                    LIMIT 1
                )
                UPDATE mcp.tool_calls t
                   SET tool_use_id = $2,
                       claude_session_id = COALESCE($3, t.claude_session_id)
                  FROM target
                 WHERE t.id = target.id
                RETURNING t.id::text AS id
                """,
                it.tool_name,
                it.tool_use_id,
                it.claude_session_id,
                payload.within_minutes,
            )
        except Exception:
            logger.exception("link_tool_uses failed for tool_use_id=%s", it.tool_use_id)
            unmatched += 1
            continue
        if row:
            linked += 1
        else:
            unmatched += 1

    if unmatched:
        logger.info("tool-uses/link: linked=%d unmatched=%d total=%d", linked, unmatched, len(seen))
    return {"ok": True, "linked": linked, "unmatched": unmatched, "total": len(seen)}
