"""Bug 记忆库 + 客户端日志 service(2026-05-28 Phase A+/A++).

解决"bug 第一次修第二次还要修":
- A+ insert_client_logs_batch: 客户端 IPC/fetch/spawn/error 全部留痕
- A++ insert_bug / list_bugs / update_bug / get_unfixed_bug_summary_for_inject:
  bug 长期记忆,未修 bug 启动期注入 Claude 让其避坑

session_id 兼容 uuid 或 claude_session_id 文本(沿用 Phase A _resolve_session_uuid 思路).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.database import get_pool

logger = logging.getLogger(__name__)


_VALID_SEVERITIES = {"debug", "info", "warn", "error", "critical"}
_VALID_EVENT_TYPES = {
    "ipc_call",
    "ke_fetch",
    "claude_spawn",
    "claude_stderr",
    "electron_error",
    "electron_crash",
    "startup",
    "manual_bug_report",
}
# 不强校验 event_type(老板加新类型不卡),但记 warning 便于后期发现拼写问题
_MAX_INJECT_CHARS = 2000
_MAX_INJECT_PER_BUG = 200
_DEDUPE_LOOKBACK_DAYS = 30
_DEDUPE_MIN_RATIO = 0.6  # title 字符重合度阈值(简单 set 交集 / 并集)


# ─────────────────────────── 内部工具 ───────────────────────────


async def _resolve_session_uuid(session_id_raw: str | None) -> uuid.UUID | None:
    """session_id 可能是 mcp.agent_sessions.id (uuid) 或 claude_session_id (text).

    None / 空字符串 → 返 None(允许日志不挂 session).
    """
    if not session_id_raw or not isinstance(session_id_raw, str):
        return None
    pool = get_pool()

    # try as uuid first
    candidate: uuid.UUID | None = None
    try:
        candidate = uuid.UUID(session_id_raw)
    except (ValueError, TypeError):
        candidate = None

    if candidate is not None:
        row = await pool.fetchrow(
            "SELECT id FROM mcp.agent_sessions WHERE id=$1",
            candidate,
        )
        if row is not None:
            return row["id"]

    # fallback as claude_session_id
    row = await pool.fetchrow(
        "SELECT id FROM mcp.agent_sessions WHERE claude_session_id=$1",
        session_id_raw,
    )
    if row is None:
        return None
    return row["id"]


def _to_jsonb_param(val: Any) -> str | None:
    """dict/list → json str;其他 → None(asyncpg JSONB 用 str)."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return json.dumps({"_unserializable": str(val)})
    return json.dumps({"_raw": val}, default=str)


def _norm_title(t: str) -> str:
    """归一化 title 用于相似度:小写 + strip + 去多余空白."""
    return " ".join(t.strip().lower().split())


def _title_similarity(a: str, b: str) -> float:
    """简单字符 set Jaccard.中文场景 LIKE 太松,这里 60% 阈值就 OK."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = sa & sb
    union = sa | sb
    return len(inter) / len(union)


# ─────────────────────────── 客户端日志 ───────────────────────────


async def insert_client_logs_batch(events: list[dict[str, Any]]) -> dict:
    """批量插入 client_logs.

    每条 event 至少含 client + event_type + severity.
    可选 channel / payload / result / duration_ms / stack_trace / session_id
    (str/uuid 或 claude_session_id) / user_marked_bug.

    失败行不阻断其他,errors 收集 [{index, error}].
    """
    if not isinstance(events, list):
        return {
            "ok": False,
            "error": "invalid_events",
            "hint": "events 必须是 list",
        }
    if not events:
        return {"ok": True, "inserted_count": 0, "errors": []}

    pool = get_pool()
    inserted = 0
    errors: list[dict[str, Any]] = []

    # 批量内每条独立 INSERT(数量不大,简单稳)
    for idx, ev in enumerate(events):
        try:
            if not isinstance(ev, dict):
                errors.append({"index": idx, "error": "event 必须是 dict"})
                continue

            client = ev.get("client")
            event_type = ev.get("event_type")
            severity = ev.get("severity", "info")

            if not client or not isinstance(client, str):
                errors.append({"index": idx, "error": "缺 client"})
                continue
            if not event_type or not isinstance(event_type, str):
                errors.append({"index": idx, "error": "缺 event_type"})
                continue
            if severity not in _VALID_SEVERITIES:
                errors.append(
                    {"index": idx, "error": f"severity 非法,需 {sorted(_VALID_SEVERITIES)}"}
                )
                continue
            if event_type not in _VALID_EVENT_TYPES:
                # 不卡死,但记日志便于发现 typo
                logger.info("client_logs unfamiliar event_type=%s", event_type)

            session_uuid = await _resolve_session_uuid(ev.get("session_id"))

            channel = ev.get("channel")
            payload = _to_jsonb_param(ev.get("payload"))
            result = _to_jsonb_param(ev.get("result"))
            duration_ms = ev.get("duration_ms")
            if duration_ms is not None:
                try:
                    duration_ms = int(duration_ms)
                except (TypeError, ValueError):
                    duration_ms = None
            stack_trace = ev.get("stack_trace")
            user_marked_bug = bool(ev.get("user_marked_bug", False))

            await pool.execute(
                """
                INSERT INTO mcp.client_logs (
                    session_id, client, event_type, severity,
                    channel, payload, result, duration_ms, stack_trace, user_marked_bug
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10)
                """,
                session_uuid,
                client,
                event_type,
                severity,
                channel,
                payload,
                result,
                duration_ms,
                stack_trace,
                user_marked_bug,
            )
            inserted += 1
        except Exception as exc:  # pragma: no cover - 单条挂不阻断
            logger.exception("client_logs batch insert failed at index=%d", idx)
            errors.append({"index": idx, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "ok": True,
        "inserted_count": inserted,
        "errors": errors,
    }


# ─────────────────────────── Bug 记忆 ───────────────────────────


async def _find_dedupe_candidate(title: str) -> dict | None:
    """30 天内 title 相似度 ≥ _DEDUPE_MIN_RATIO 的最近一条;无返 None."""
    pool = get_pool()
    rows = await pool.fetch(
        f"""
        SELECT id, title, occurrences, tags
        FROM mcp.bug_memory
        WHERE created_at >= NOW() - INTERVAL '{_DEDUPE_LOOKBACK_DAYS} days'
        ORDER BY last_seen DESC
        LIMIT 50
        """
    )
    if not rows:
        return None
    norm_new = _norm_title(title)
    if not norm_new:
        return None
    best: dict | None = None
    best_score = 0.0
    for r in rows:
        score = _title_similarity(norm_new, _norm_title(r["title"]))
        if score >= _DEDUPE_MIN_RATIO and score > best_score:
            best_score = score
            best = {
                "id": r["id"],
                "title": r["title"],
                "occurrences": int(r["occurrences"]),
                "tags": list(r["tags"] or []),
                "score": score,
            }
    return best


async def insert_bug(
    title: str,
    symptom: str,
    trigger_conditions: str | None = None,
    root_cause: str | None = None,
    fix_recipe: str | None = None,
    client_log_ids: list[str] | None = None,
    tags: list[str] | None = None,
    auto_dedupe: bool = True,
) -> dict:
    """新建 bug 记忆.

    auto_dedupe=True 时扫最近 30 天同 title 相似的 bug(_title_similarity ≥ 0.6),
    命中则 occurrences++ + last_seen=now + 合并 tags + 追加 client_log_ids,
    其他字段(symptom/trigger/cause/fix)仅在原行为空时补,不覆盖.

    返回 {ok, bug_id, deduped, occurrences, ?merged_tags}.
    """
    if not title or not isinstance(title, str):
        return {"ok": False, "error": "invalid_title", "hint": "title 必填"}
    if not symptom or not isinstance(symptom, str):
        return {"ok": False, "error": "invalid_symptom", "hint": "symptom 必填"}

    pool = get_pool()

    # 解析 client_log_ids uuid
    parsed_log_ids: list[uuid.UUID] = []
    invalid_log_ids: list[str] = []
    for s in client_log_ids or []:
        try:
            parsed_log_ids.append(uuid.UUID(str(s)))
        except (ValueError, TypeError):
            invalid_log_ids.append(str(s))

    # 标准化 tags
    norm_tags = [t for t in (tags or []) if isinstance(t, str) and t.strip()]

    candidate = await _find_dedupe_candidate(title) if auto_dedupe else None

    if candidate is not None:
        # 合并
        bug_id = candidate["id"]
        merged_tags = sorted({*candidate["tags"], *norm_tags})

        # COALESCE 补字段(原为 NULL 时才填)
        row = await pool.fetchrow(
            """
            UPDATE mcp.bug_memory SET
                occurrences = occurrences + 1,
                last_seen = NOW(),
                updated_at = NOW(),
                tags = $1::text[],
                trigger_conditions = COALESCE(trigger_conditions, $2),
                root_cause = COALESCE(root_cause, $3),
                fix_recipe = COALESCE(fix_recipe, $4),
                client_log_ids = COALESCE(client_log_ids, ARRAY[]::uuid[]) ||
                                 COALESCE($5::uuid[], ARRAY[]::uuid[])
            WHERE id = $6
            RETURNING id, occurrences, tags
            """,
            merged_tags,
            trigger_conditions,
            root_cause,
            fix_recipe,
            parsed_log_ids or None,
            bug_id,
        )
        response = {
            "ok": True,
            "bug_id": str(row["id"]),
            "deduped": True,
            "occurrences": int(row["occurrences"]),
            "merged_tags": list(row["tags"] or []),
        }
        if invalid_log_ids:
            response["warning"] = f"忽略 {len(invalid_log_ids)} 个非 uuid 的 client_log_ids"
        return response

    # 新建
    row = await pool.fetchrow(
        """
        INSERT INTO mcp.bug_memory (
            title, symptom, trigger_conditions, root_cause, fix_recipe,
            client_log_ids, tags
        )
        VALUES ($1, $2, $3, $4, $5, $6::uuid[], $7::text[])
        RETURNING id, occurrences
        """,
        title,
        symptom,
        trigger_conditions,
        root_cause,
        fix_recipe,
        parsed_log_ids or None,
        norm_tags or None,
    )
    response = {
        "ok": True,
        "bug_id": str(row["id"]),
        "deduped": False,
        "occurrences": int(row["occurrences"]),
    }
    if invalid_log_ids:
        response["warning"] = f"忽略 {len(invalid_log_ids)} 个非 uuid 的 client_log_ids"
    return response


async def list_bugs(
    unfixed_only: bool = False,
    tags: list[str] | None = None,
    limit: int = 50,
) -> list[dict]:
    """查 bug 列表,按 last_seen DESC."""
    pool = get_pool()
    where_clauses: list[str] = []
    params: list[Any] = []

    if unfixed_only:
        where_clauses.append("fix_applied = FALSE")

    norm_tags = [t for t in (tags or []) if isinstance(t, str) and t.strip()]
    if norm_tags:
        params.append(norm_tags)
        where_clauses.append(f"tags && ${len(params)}::text[]")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    params.append(max(1, min(int(limit), 500)))
    sql = (
        "SELECT id, title, symptom, trigger_conditions, root_cause, fix_recipe, "
        "       fix_applied, occurrences, last_seen, client_log_ids, tags, "
        "       created_at, updated_at "
        f"FROM mcp.bug_memory{where_sql} "
        "ORDER BY last_seen DESC "
        f"LIMIT ${len(params)}"
    )
    rows = await pool.fetch(sql, *params)
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "symptom": r["symptom"],
            "trigger_conditions": r["trigger_conditions"],
            "root_cause": r["root_cause"],
            "fix_recipe": r["fix_recipe"],
            "fix_applied": bool(r["fix_applied"]),
            "occurrences": int(r["occurrences"]),
            "last_seen": r["last_seen"],
            "client_log_ids": [str(u) for u in (r["client_log_ids"] or [])],
            "tags": list(r["tags"] or []),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


async def update_bug(
    bug_id: str,
    fix_applied: bool | None = None,
    root_cause: str | None = None,
    fix_recipe: str | None = None,
    add_tags: list[str] | None = None,
    note_append: str | None = None,
) -> dict:
    """更新 bug.

    - fix_applied/root_cause/fix_recipe 非 None 就更新(覆盖)
    - add_tags 追加去重
    - note_append 追加到 fix_recipe 末尾(加分隔)

    返回 {ok, updated_fields}.
    """
    try:
        bug_uuid = uuid.UUID(bug_id)
    except (ValueError, TypeError):
        return {
            "ok": False,
            "error": "invalid_bug_id",
            "hint": "bug_id 必须是 uuid 字符串",
        }

    pool = get_pool()

    # 拉 current 用于 note_append + tag merge
    cur = await pool.fetchrow(
        "SELECT fix_recipe, tags FROM mcp.bug_memory WHERE id=$1",
        bug_uuid,
    )
    if cur is None:
        return {
            "ok": False,
            "error": "bug_not_found",
            "hint": f"bug_id={bug_id} 不存在",
        }

    updated_fields: list[str] = []
    set_clauses: list[str] = ["updated_at = NOW()"]
    params: list[Any] = []

    if fix_applied is not None:
        params.append(bool(fix_applied))
        set_clauses.append(f"fix_applied = ${len(params)}")
        updated_fields.append("fix_applied")

    if root_cause is not None:
        params.append(root_cause)
        set_clauses.append(f"root_cause = ${len(params)}")
        updated_fields.append("root_cause")

    # fix_recipe 跟 note_append 互动:fix_recipe 给覆盖,note_append 给追加
    if fix_recipe is not None and note_append is not None:
        merged = fix_recipe + "\n\n--- 追加 ---\n" + note_append
        params.append(merged)
        set_clauses.append(f"fix_recipe = ${len(params)}")
        updated_fields.append("fix_recipe")
    elif fix_recipe is not None:
        params.append(fix_recipe)
        set_clauses.append(f"fix_recipe = ${len(params)}")
        updated_fields.append("fix_recipe")
    elif note_append is not None:
        base = cur["fix_recipe"] or ""
        sep = "\n\n--- 追加 ---\n" if base else ""
        merged = base + sep + note_append
        params.append(merged)
        set_clauses.append(f"fix_recipe = ${len(params)}")
        updated_fields.append("fix_recipe(append)")

    if add_tags:
        norm_new = [t for t in add_tags if isinstance(t, str) and t.strip()]
        if norm_new:
            existing = list(cur["tags"] or [])
            merged_tags = sorted({*existing, *norm_new})
            params.append(merged_tags)
            set_clauses.append(f"tags = ${len(params)}::text[]")
            updated_fields.append("tags")

    if not updated_fields:
        return {
            "ok": True,
            "updated_fields": [],
            "warning": "没字段被更新(传 None 不算更新)",
        }

    params.append(bug_uuid)
    sql = (
        "UPDATE mcp.bug_memory SET "
        + ", ".join(set_clauses)
        + f" WHERE id = ${len(params)}"
    )
    await pool.execute(sql, *params)

    return {"ok": True, "updated_fields": updated_fields}


async def get_unfixed_bug_summary_for_inject(max_bugs: int = 10) -> str:
    """启动期/spawn 期 inject 用:把未修 bug 列表渲染成短文本(≤2000 字符).

    用于 Claude --append-system-prompt.格式:

    ## 已知未修 bug(操作时主动规避)
    1. [bug-xxxxxxxx] 症状: ... | 触发: ... | 兜底: ...
    2. ...

    没未修 bug 时返空字符串("").
    """
    bugs = await list_bugs(unfixed_only=True, limit=max(1, min(int(max_bugs), 50)))
    if not bugs:
        return ""

    lines = ["## 已知未修 bug(操作时主动规避)"]
    total_chars = len(lines[0])

    for i, b in enumerate(bugs, start=1):
        bid = b["id"]
        short_id = f"bug-{bid[:8]}"
        sym = (b["symptom"] or "").replace("\n", " ").strip()[:80]
        trg = (b["trigger_conditions"] or "").replace("\n", " ").strip()[:60]
        fix = (b["fix_recipe"] or "").replace("\n", " ").strip()[:60]
        parts = [f"症状: {sym}"]
        if trg:
            parts.append(f"触发: {trg}")
        if fix:
            parts.append(f"兜底: {fix}")
        if b["occurrences"] > 1:
            parts.append(f"已发生 {b['occurrences']} 次")
        line = f"{i}. [{short_id}] " + " | ".join(parts)

        # 单条不超 200 字符
        if len(line) > _MAX_INJECT_PER_BUG:
            line = line[: _MAX_INJECT_PER_BUG - 3] + "..."

        # 总字符不超 2000(留 50 字符余量)
        if total_chars + len(line) + 1 > _MAX_INJECT_CHARS - 50:
            lines.append(f"... (剩余 {len(bugs) - i + 1} 条 bug 因字数限制省略,看 bug 库全表)")
            break

        lines.append(line)
        total_chars += len(line) + 1

    return "\n".join(lines)
