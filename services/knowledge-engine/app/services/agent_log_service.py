"""Service layer for /api/v1/mcp/tool-calls REST router (W4-B 切片 1).

职责：
- 列表 / 详情查询 mcp.tool_calls
- 评分写库 + pattern_lib 双写（共用 router 与 mcp tool feedback.py）
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.database import get_pool
from app.mcp import pattern_lib

logger = logging.getLogger(__name__)


_VALID_RATINGS = {"good", "bad", "redo"}
_VALID_STATUSES = {
    "pending",
    "approved",
    "rejected",
    "completed",
    "error",
    "orphaned",
}


def _coerce_jsonb(val: Any) -> dict[str, Any] | None:
    """asyncpg 已注册 JSONB codec，但万一 result/args 返回 str 兜底解析。"""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {"_raw": parsed}
        except (json.JSONDecodeError, TypeError):
            return {"_raw": val}
    # list / 其它类型：包一层避免炸 schema
    return {"_raw": val}


def _row_to_dict(row) -> dict[str, Any]:
    """asyncpg.Record → dict（含 args/result 完整字段）。

    list 与 detail 路径目前都返完整字段（前端摘要按需展开）。如未来要为分页性能
    裁字段，另起 task 再切分。
    """
    return {
        "id": str(row["id"]),
        "tool_name": row["tool_name"],
        "status": row["status"],
        "require_approval": row["require_approval"],
        "duration_ms": row["duration_ms"],
        "user_rating": row["user_rating"],
        "rating_note": row["rating_note"],
        "model_used": row["model_used"],
        "error": row["error"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "args": _coerce_jsonb(row["args"]),
        "result": _coerce_jsonb(row["result"]),
    }


def _parse_status_filter(status: str | None) -> list[str] | None:
    if not status:
        return None
    parts = [s.strip() for s in status.split(",") if s.strip()]
    if not parts:
        return None
    # 不抛错，过滤掉不在白名单的
    valid = [p for p in parts if p in _VALID_STATUSES]
    return valid or None


async def list_tool_calls(
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    tool_name: str | None = None,
    since_hours: int = 168,
) -> dict[str, Any]:
    """列出 mcp.tool_calls，DESC by created_at；带 24h 概览。"""
    pool = get_pool()
    where_clauses: list[str] = []
    params: list[Any] = []

    where_clauses.append(
        f"created_at >= NOW() - INTERVAL '{int(since_hours)} hours'"
    )

    status_list = _parse_status_filter(status)
    if status_list:
        params.append(status_list)
        where_clauses.append(f"status = ANY(${len(params)}::text[])")

    if tool_name:
        params.append(tool_name)
        where_clauses.append(f"tool_name = ${len(params)}")

    where_sql = " AND ".join(where_clauses)

    # 总数（用于分页）
    count_sql = f"SELECT COUNT(*) FROM mcp.tool_calls WHERE {where_sql}"
    total = await pool.fetchval(count_sql, *params)

    # 列表
    list_params = list(params)
    list_params.append(limit)
    list_params.append(offset)
    list_sql = (
        f"SELECT id, tool_name, args, result, status, require_approval, "
        f"       duration_ms, error, user_rating, rating_note, model_used, "
        f"       tokens_input, tokens_output, created_at, completed_at "
        f"FROM mcp.tool_calls "
        f"WHERE {where_sql} "
        f"ORDER BY created_at DESC "
        f"LIMIT ${len(list_params) - 1} OFFSET ${len(list_params)}"
    )
    rows = await pool.fetch(list_sql, *list_params)
    data = [_row_to_dict(r) for r in rows]

    summary = await _build_summary_24h()

    return {
        "data": data,
        "total": int(total or 0),
        "summary_24h": summary,
    }


async def _build_summary_24h() -> dict[str, Any]:
    """24h 概览：成功率 / 平均耗时 / pending 数 / 评分分布。"""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE status='completed') AS completed,
          COUNT(*) FILTER (WHERE status='pending') AS pending,
          AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) AS avg_dur,
          COUNT(*) FILTER (WHERE user_rating='good') AS rate_good,
          COUNT(*) FILTER (WHERE user_rating='bad') AS rate_bad,
          COUNT(*) FILTER (WHERE user_rating='redo') AS rate_redo,
          COUNT(*) FILTER (WHERE user_rating IS NULL) AS rate_none
        FROM mcp.tool_calls
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        """
    )
    total = int(row["total"] or 0)
    completed = int(row["completed"] or 0)
    success_rate = round(completed / total, 4) if total > 0 else 0.0
    avg_dur = row["avg_dur"]
    return {
        "total": total,
        "success_rate": success_rate,
        "avg_duration_ms": int(avg_dur) if avg_dur is not None else None,
        "pending_count": int(row["pending"] or 0),
        "rating_dist": {
            "good": int(row["rate_good"] or 0),
            "bad": int(row["rate_bad"] or 0),
            "redo": int(row["rate_redo"] or 0),
            "none": int(row["rate_none"] or 0),
        },
    }


async def get_tool_call(call_id: str) -> dict[str, Any] | None:
    """单行查询；call_id 解析失败也返 None。"""
    try:
        call_uuid = uuid.UUID(call_id)
    except (ValueError, TypeError):
        return None
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, tool_name, args, result, status, require_approval, "
        "       duration_ms, error, user_rating, rating_note, model_used, "
        "       tokens_input, tokens_output, created_at, completed_at "
        "FROM mcp.tool_calls WHERE id=$1",
        call_uuid,
    )
    if row is None:
        return None
    return _row_to_dict(row)


async def rate_tool_call_logic(
    *,
    call_id: str,
    rating: str,
    note: str = "",
    category: str | None = None,
) -> dict[str, Any]:
    """评分核心逻辑：写库 + pattern_lib 双写。

    给 router (POST /tool-calls/{id}/rate) 与 mcp tool feedback.rate_tool_call 共用。

    Args:
        call_id: mcp.tool_calls.id (uuid str)
        rating: good | bad | redo
        note: 可选备注
        category: 负反馈归因分类（migration 031；可空，向后兼容）
            prompt_bad / tradeoff_wrong / factual_error / tone_off /
            wrong_tool / incomplete / other

    Returns:
        {ok:true, result:{call_id,rating,tool_name}}
        {ok:false, error:invalid_rating|invalid_call_id|call_not_found, hint:...}
        {ok:true, warning:"pattern 写盘失败但 DB 已记录", result:...} 当写盘失败
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
        "UPDATE mcp.tool_calls SET user_rating=$1, rating_note=$2, rating_category=$3 "
        "WHERE id=$4 RETURNING tool_name",
        rating,
        note,
        category,
        call_uuid,
    )
    if row is None:
        return {
            "ok": False,
            "error": "call_not_found",
            "hint": f"call_id={call_id} 不存在；用 SELECT id FROM mcp.tool_calls 查",
        }

    tool_name = row["tool_name"]
    warning: str | None = None
    try:
        if rating == "good":
            pattern_lib.append_successful_pattern(
                tool_call_id=call_id, tool_name=tool_name, note=note,
            )
        else:  # bad / redo
            pattern_lib.append_failed_pattern(
                tool_call_id=call_id, tool_name=tool_name, note=note,
            )
    except Exception as exc:  # pragma: no cover - 写盘极少失败
        logger.exception("pattern_lib write failed for call_id=%s", call_id[:8])
        warning = f"pattern 写盘失败但 DB 已记录: {type(exc).__name__}"

    response: dict[str, Any] = {
        "ok": True,
        "result": {
            "call_id": call_id,
            "rating": rating,
            "tool_name": tool_name,
        },
    }
    if warning:
        response["warning"] = warning
    return response


# ---------------------------------------------------------------------------
# message_feedback (migration 031)
# ---------------------------------------------------------------------------

_VALID_MESSAGE_RATINGS = {"good", "bad"}
_MAX_SNAPSHOT_BYTES = 4096


async def _resolve_session_uuid(session_id: str) -> uuid.UUID | None:
    """session_id 接受 mcp.agent_sessions.id (uuid) 或 claude_session_id (text).

    先试 uuid 转换，fail 就用 claude_session_id 字段查。两个都查不到返 None。
    """
    pool = get_pool()
    # try as uuid first
    try:
        candidate = uuid.UUID(session_id)
    except (ValueError, TypeError):
        candidate = None

    if candidate is not None:
        row = await pool.fetchrow(
            "SELECT id FROM mcp.agent_sessions WHERE id=$1",
            candidate,
        )
        if row is not None:
            return row["id"]

    # fallback：当 text 当 claude_session_id 查
    row = await pool.fetchrow(
        "SELECT id FROM mcp.agent_sessions WHERE claude_session_id=$1",
        session_id,
    )
    if row is None:
        return None
    return row["id"]


async def rate_message_logic(
    *,
    session_id: str,
    message_id: str,
    rating: str,
    category: str | None = None,
    note: str | None = None,
    message_text_snapshot: str | None = None,
    tool_use_ids: list[str] | None = None,
    client: str = "desktop",
) -> dict[str, Any]:
    """对 AI 整条消息打分（写 mcp.message_feedback）。

    给 router (POST /messages/rate) 与 mcp tool feedback.rate_message 共用。

    Returns:
        {ok:true, feedback_id, replaced:bool}
        {ok:false, error:..., hint:...}
    """
    if rating not in _VALID_MESSAGE_RATINGS:
        return {
            "ok": False,
            "error": "invalid_rating",
            "hint": f"rating 必须是 {sorted(_VALID_MESSAGE_RATINGS)} 之一",
        }
    if not session_id or not isinstance(session_id, str):
        return {
            "ok": False,
            "error": "invalid_session_id",
            "hint": "session_id 不能为空",
        }
    if not message_id or not isinstance(message_id, str):
        return {
            "ok": False,
            "error": "invalid_message_id",
            "hint": "message_id 不能为空",
        }

    session_uuid = await _resolve_session_uuid(session_id)
    if session_uuid is None:
        return {
            "ok": False,
            "error": "session_not_found",
            "hint": (
                f"session_id={session_id} 既不是 mcp.agent_sessions.id 也不是 "
                "claude_session_id；先确认 chat session 是否真存在"
            ),
        }

    # snapshot 大小观测（不强校验，超长记 warning）
    snapshot_len: int | None = None
    snapshot_warning: str | None = None
    if message_text_snapshot is not None:
        snapshot_bytes = message_text_snapshot.encode("utf-8", errors="ignore")
        snapshot_len = len(snapshot_bytes)
        if snapshot_len > _MAX_SNAPSHOT_BYTES:
            snapshot_warning = (
                f"message_text_snapshot {snapshot_len}B 超过 {_MAX_SNAPSHOT_BYTES}B "
                "约定但已落库（建议客户端裁剪）"
            )

    pool = get_pool()
    # 先查 existing 决定 replaced 标位（ON CONFLICT 拿不到这个语义）
    existing_id = await pool.fetchval(
        "SELECT id FROM mcp.message_feedback "
        "WHERE session_id=$1 AND message_id=$2",
        session_uuid,
        message_id,
    )

    row = await pool.fetchrow(
        """
        INSERT INTO mcp.message_feedback (
            session_id, message_id, rating, category, note,
            message_text_snapshot, tool_use_ids, client
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (session_id, message_id) DO UPDATE SET
            rating = EXCLUDED.rating,
            category = EXCLUDED.category,
            note = EXCLUDED.note,
            message_text_snapshot = EXCLUDED.message_text_snapshot,
            tool_use_ids = EXCLUDED.tool_use_ids,
            client = EXCLUDED.client
        RETURNING id
        """,
        session_uuid,
        message_id,
        rating,
        category,
        note,
        message_text_snapshot,
        tool_use_ids,
        client,
    )

    response: dict[str, Any] = {
        "ok": True,
        "feedback_id": str(row["id"]),
        "replaced": existing_id is not None,
    }
    if snapshot_warning:
        response["warning"] = snapshot_warning
    if snapshot_len is not None:
        response["snapshot_bytes"] = snapshot_len
    return response
