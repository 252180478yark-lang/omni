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


def _row_to_dict(row, *, include_full: bool) -> dict[str, Any]:
    """asyncpg.Record → dict；include_full=True 时带 args/result 字段。"""
    out: dict[str, Any] = {
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
    }
    if include_full:
        out["args"] = _coerce_jsonb(row["args"])
        out["result"] = _coerce_jsonb(row["result"])
    else:
        # 列表也给 args/result，前端摘要可能用；但限制 result 大小由前端展开决定
        out["args"] = _coerce_jsonb(row["args"])
        out["result"] = _coerce_jsonb(row["result"])
    return out


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
    data = [_row_to_dict(r, include_full=False) for r in rows]

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
    return _row_to_dict(row, include_full=True)


async def rate_tool_call_logic(
    *,
    call_id: str,
    rating: str,
    note: str = "",
) -> dict[str, Any]:
    """评分核心逻辑：写库 + pattern_lib 双写。

    给 router (POST /tool-calls/{id}/rate) 与 mcp tool feedback.rate_tool_call 共用。

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
