"""W3a T6：Human Gate 真实现（design doc §5）。

行为：
1. `request_approval` 写一行 mcp.human_gates（decision=NULL）
2. 起 DB poll 循环，等 `decision IS NOT NULL`
3. 超时（默认 timeout_seconds 秒）→ 写 decision=expired（不是 rejected！§1.6 不替老板做否定决定）
4. 调用方（audit.py wrapper）拿到 decision 决定继续/中止

不做：前端 /inbox（W3a 起步走 CLI 批），多用户隔离（个人自用）

CLI 配套：`python -m app.mcp.cli_approve list/approve/reject/tail`（T7 落地）

W5-B 3.1：INSERT 后 Redis publish 到 mcp.human_gates.new，让前端 WS-handler 订阅推 UI。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import TypedDict

from app.database import get_pool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# W5-B 3.1: Redis publish helper
# ---------------------------------------------------------------------------
try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None  # 容错：未装 redis-py 时静默跳过

_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_redis_pub: "aioredis.Redis | None" = None


async def _get_redis_pub() -> "aioredis.Redis | None":
    global _redis_pub
    if aioredis is None:
        return None
    if _redis_pub is None:
        try:
            _redis_pub = aioredis.from_url(_REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning("Redis 连接失败 (W5-B human_gate publish): %s", e)
            return None
    return _redis_pub


async def _notify_human_gate(short_id: str, tool_name: str, summary: str) -> None:
    """W5-B: 新 human_gate 写入时通知前端 ws-handler 订阅 channel `mcp.human_gates.new`"""
    r = await _get_redis_pub()
    if r is None:
        return
    try:
        await r.publish(
            "mcp.human_gates.new",
            json.dumps({"short_id": short_id, "tool_name": tool_name, "summary": summary}),
        )
        logger.debug("published human_gate short_id=%s to mcp.human_gates.new", short_id)
    except Exception as e:
        logger.warning("publish mcp.human_gates.new 失败: %s", e)


class GateDecision(TypedDict):
    decision: str          # "approved" | "rejected" | "expired"（expired=超时未决，非老板驳回）
    decision_note: str | None


async def request_approval(
    *,
    tool_call_id: str,
    tool_name: str = "",
    summary: str,
    timeout_seconds: int = 21600,  # 6h；超时=expired 不是 rejected，适配异步/路上用
    poll_interval_seconds: float = 2.0,
) -> GateDecision:
    """写 human_gates → 等批/驳/超时 → 返决策。

    Args:
        tool_call_id: 关联的 mcp.tool_calls.id（uuid str）
        tool_name: tool 名称（W5-B：用于 Redis publish payload）
        summary: 给人看的摘要（CLI list / 未来 /inbox 卡片显示）
        timeout_seconds: 超时（默认 21600 = 6h，适配异步/路上用）；超时标 expired，绝不替老板 rejected
        poll_interval_seconds: DB poll 间隔（默认 2 秒；测试用 0.1）

    Returns:
        {"decision": "approved" | "rejected", "decision_note": str | None}
    """
    pool = get_pool()
    gate_id = uuid.uuid4()

    # 1. 写 gate（pending = decision IS NULL）
    await pool.execute(
        "INSERT INTO mcp.human_gates (id, tool_call_id, summary, timeout_seconds, decision) "
        "VALUES ($1, $2, $3, $4, NULL)",
        gate_id, uuid.UUID(tool_call_id), summary, int(timeout_seconds),
    )
    logger.info("human gate created id=%s tool_call_id=%s timeout=%ds",
                gate_id, tool_call_id, timeout_seconds)

    # W5-B 3.1: 写库后异步 publish 给前端 WS-handler（失败不挡主流程）
    short_id = str(gate_id)[:8]
    asyncio.create_task(_notify_human_gate(short_id, tool_name or tool_call_id, summary))

    # 2. poll 等决定
    elapsed = 0.0
    while elapsed < timeout_seconds:
        row = await pool.fetchrow(
            "SELECT decision, decision_note FROM mcp.human_gates WHERE id=$1",
            gate_id,
        )
        if row and row["decision"] is not None:
            logger.info("human gate decided id=%s decision=%s", gate_id, row["decision"])
            return {
                "decision": row["decision"],
                "decision_note": row["decision_note"],
            }
        await asyncio.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds

    # 3. 超时 → 标 expired（不是 rejected！宪法 §1.6：系统永远不替老板做否定决定）。
    #    expired 让 CLI list / 复盘时能区分"我驳的" vs "超时没决定"；record_cost 这类纯写入
    #    超时不算"老板拒绝"，需要时重发即可。decision 列是 TEXT 无 CHECK，免迁移。
    await pool.execute(
        "UPDATE mcp.human_gates SET decision='expired', "
        "decision_note=COALESCE(decision_note,'') || '[timeout-未经你决定]', decided_at=NOW() "
        "WHERE id=$1 AND decision IS NULL",
        gate_id,
    )
    logger.warning("human gate EXPIRED id=%s after %ds（超时未决，未替老板驳回）", gate_id, timeout_seconds)
    return {"decision": "expired", "decision_note": "timeout_expired"}


async def list_pending() -> list[dict]:
    """列出未决定的 gate（CLI 用）。"""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT g.id, g.tool_call_id, g.summary, g.timeout_seconds, g.created_at,
               t.tool_name, t.args
          FROM mcp.human_gates g
          JOIN mcp.tool_calls t ON t.id = g.tool_call_id
         WHERE g.decision IS NULL
         ORDER BY g.created_at ASC
        """
    )
    return [dict(r) for r in rows]


async def approve(gate_id: str, note: str = "") -> bool:
    """批一条 gate。返回是否成功（False = gate 不存在或已决定）。"""
    pool = get_pool()
    rec = await pool.fetchrow(
        "UPDATE mcp.human_gates SET decision='approved', decision_note=$1, decided_at=NOW() "
        "WHERE id=$2 AND decision IS NULL RETURNING id",
        note, uuid.UUID(gate_id),
    )
    return rec is not None


async def reject(gate_id: str, note: str = "") -> bool:
    pool = get_pool()
    rec = await pool.fetchrow(
        "UPDATE mcp.human_gates SET decision='rejected', decision_note=$1, decided_at=NOW() "
        "WHERE id=$2 AND decision IS NULL RETURNING id",
        note, uuid.UUID(gate_id),
    )
    return rec is not None
