"""Service layer for /api/v1/mcp/human-gates REST router (W4-B 切片 2).

职责：
- 列待批 gate（含 join tool_calls 拿 tool_name + args 摘要）
- 批 / 驳一条 gate（带 short_id 解析 + 错误格式规范）

底层调用 app/mcp/human_gate.py 的 approve/reject（已 idempotent）。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.database import get_pool
from app.mcp import human_gate

logger = logging.getLogger(__name__)


async def list_pending() -> dict[str, Any]:
    """列出未决定的 gate（join mcp.tool_calls 拿 tool_name / args 摘要）。"""
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
    now = datetime.now(timezone.utc)
    data = []
    for r in rows:
        created = r["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = int((now - created).total_seconds())
        gate_id = str(r["id"])
        data.append(
            {
                "id": gate_id,
                "short_id": gate_id[:8],
                "tool_call_id": str(r["tool_call_id"]),
                "tool_name": r["tool_name"],
                "summary": r["summary"],
                "args_preview": r["args"] if isinstance(r["args"], dict) else None,
                "timeout_seconds": int(r["timeout_seconds"]),
                "created_at": r["created_at"],
                "age_seconds": age,
            }
        )
    return {"data": data, "total": len(data)}


async def _resolve_gate_id(short_or_full: str) -> dict[str, Any]:
    """short_id (8+ chars) 或全 uuid → 全 uuid。

    Returns:
        {"ok":True, "id": "<full uuid>"} 或
        {"ok":False, "error": "gate_not_found"|"ambiguous_short_id", "hint": "..."}
    """
    pool = get_pool()
    s = (short_or_full or "").strip()
    if not s:
        return {"ok": False, "error": "gate_not_found", "hint": "id 不能为空"}

    if len(s) >= 32:
        # 完整 uuid（去横杠 32 位）
        try:
            full = str(uuid.UUID(s))
        except ValueError:
            return {
                "ok": False,
                "error": "gate_not_found",
                "hint": f"'{s[:16]}...' 不是合法 uuid",
            }
        # 不在此处过滤 decision IS NULL：让 human_gate.approve/reject 的 idempotent
        # 行为决定 already_decided。本层只判 gate 是否存在。
        row = await pool.fetchrow(
            "SELECT id FROM mcp.human_gates WHERE id=$1",
            uuid.UUID(full),
        )
        if row is None:
            return {
                "ok": False,
                "error": "gate_not_found",
                "hint": f"gate {full[:8]} 不存在",
            }
        return {"ok": True, "id": full}

    # short_id：扫 pending 找前缀匹配
    rows = await pool.fetch(
        "SELECT id::text AS id_str FROM mcp.human_gates WHERE decision IS NULL"
    )
    matches = [r["id_str"] for r in rows if r["id_str"].startswith(s)]
    if len(matches) == 1:
        return {"ok": True, "id": matches[0]}
    if len(matches) > 1:
        return {
            "ok": False,
            "error": "ambiguous_short_id",
            "hint": f"short_id '{s}' 撞了 {len(matches)} 条，发完整 uuid",
        }
    return {
        "ok": False,
        "error": "gate_not_found",
        "hint": f"没找到 short_id '{s}' 的待批 gate",
    }


async def approve_gate(gate_id: str, note: str = "") -> dict[str, Any]:
    """批一条 gate。返回 {ok:true, result:{id, note}} 或 {ok:false, error, hint}."""
    resolved = await _resolve_gate_id(gate_id)
    if not resolved.get("ok"):
        return resolved
    full_id = resolved["id"]
    success = await human_gate.approve(full_id, note)
    if not success:
        return {
            "ok": False,
            "error": "already_decided",
            "hint": f"gate {full_id[:8]} 已批/驳，无法重复",
        }
    return {
        "ok": True,
        "result": {"id": full_id, "decision": "approved", "note": note},
    }


async def reject_gate(gate_id: str, note: str = "") -> dict[str, Any]:
    """驳一条 gate。同 approve_gate 错误格式。"""
    resolved = await _resolve_gate_id(gate_id)
    if not resolved.get("ok"):
        return resolved
    full_id = resolved["id"]
    success = await human_gate.reject(full_id, note)
    if not success:
        return {
            "ok": False,
            "error": "already_decided",
            "hint": f"gate {full_id[:8]} 已批/驳，无法重复",
        }
    return {
        "ok": True,
        "result": {"id": full_id, "decision": "rejected", "note": note},
    }
