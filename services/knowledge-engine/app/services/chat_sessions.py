"""PostgreSQL-backed chat session store.

Hot path (LLM 上下文) 仍然走 Redis `session_store`，这里负责：
  • 列表/搜索历史会话（冷路径）
  • 保存完整消息流水（sources / retrieval / images / video 等富信息）
  • 支持重命名 / 软删除 / 恢复单个会话的完整 messages
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.database import get_pool

logger = logging.getLogger(__name__)


def _row_to_session(row: dict | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("kb_ids",):
        val = data.get(key)
        if isinstance(val, str):
            try:
                data[key] = json.loads(val)
            except json.JSONDecodeError:
                data[key] = []
    for key in ("last_message_at", "created_at", "updated_at", "deleted_at"):
        val = data.get(key)
        if val is not None:
            data[key] = val.isoformat()
    return data


def _row_to_message(row: dict) -> dict:
    data = dict(row)
    for key in ("sources", "retrieval", "images", "video"):
        val = data.get(key)
        if isinstance(val, str):
            try:
                data[key] = json.loads(val) if val else None
            except json.JSONDecodeError:
                data[key] = None
    for key in ("created_at",):
        val = data.get(key)
        if val is not None:
            data[key] = val.isoformat()
    return data


# ═══ Session CRUD ═══

async def ensure_session(
    session_id: str,
    *,
    kb_ids: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    persona_id: str | None = None,
    title: str | None = None,
) -> dict:
    """Insert session if missing, otherwise refresh mutable meta (kb_ids/provider/model)."""
    pool = get_pool()
    kb_json = json.dumps(kb_ids or [], ensure_ascii=False)
    row = await pool.fetchrow(
        """
        INSERT INTO knowledge.chat_sessions (id, title, kb_ids, provider, model, persona_id)
        VALUES ($1, COALESCE($2, ''), $3::jsonb, $4, $5, $6)
        ON CONFLICT (id) DO UPDATE SET
            kb_ids     = EXCLUDED.kb_ids,
            provider   = COALESCE(EXCLUDED.provider,   knowledge.chat_sessions.provider),
            model      = COALESCE(EXCLUDED.model,      knowledge.chat_sessions.model),
            persona_id = COALESCE(EXCLUDED.persona_id, knowledge.chat_sessions.persona_id),
            deleted_at = NULL,
            updated_at = NOW()
        RETURNING id, title, kb_ids, provider, model, persona_id, message_count,
                  last_message_at, created_at, updated_at, deleted_at
        """,
        session_id,
        title,
        kb_json,
        provider,
        model,
        persona_id,
    )
    return _row_to_session(row)  # type: ignore[return-value]


async def list_sessions(
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
) -> list[dict]:
    pool = get_pool()
    if search and search.strip():
        rows = await pool.fetch(
            """
            SELECT s.id, s.title, s.kb_ids, s.provider, s.model, s.persona_id,
                   s.message_count, s.last_message_at, s.created_at, s.updated_at
              FROM knowledge.chat_sessions s
             WHERE s.deleted_at IS NULL
               AND (s.title ILIKE $1
                    OR EXISTS (SELECT 1 FROM knowledge.chat_messages m
                                WHERE m.session_id = s.id AND m.content ILIKE $1))
             ORDER BY COALESCE(s.last_message_at, s.created_at) DESC
             LIMIT $2 OFFSET $3
            """,
            f"%{search.strip()}%",
            limit,
            offset,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, title, kb_ids, provider, model, persona_id,
                   message_count, last_message_at, created_at, updated_at
              FROM knowledge.chat_sessions
             WHERE deleted_at IS NULL
             ORDER BY COALESCE(last_message_at, created_at) DESC
             LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
    return [_row_to_session(r) for r in rows]  # type: ignore[misc]


async def get_session(session_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, title, kb_ids, provider, model, persona_id,
               message_count, last_message_at, created_at, updated_at, deleted_at
          FROM knowledge.chat_sessions
         WHERE id = $1 AND deleted_at IS NULL
        """,
        session_id,
    )
    return _row_to_session(row)


async def update_session(
    session_id: str,
    *,
    title: str | None = None,
    kb_ids: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    persona_id: str | None = None,
) -> dict | None:
    pool = get_pool()
    kb_json = json.dumps(kb_ids, ensure_ascii=False) if kb_ids is not None else None
    row = await pool.fetchrow(
        """
        UPDATE knowledge.chat_sessions
           SET title      = COALESCE($2, title),
               kb_ids     = COALESCE($3::jsonb, kb_ids),
               provider   = COALESCE($4, provider),
               model      = COALESCE($5, model),
               persona_id = COALESCE($6, persona_id),
               updated_at = NOW()
         WHERE id = $1 AND deleted_at IS NULL
         RETURNING id, title, kb_ids, provider, model, persona_id,
                   message_count, last_message_at, created_at, updated_at
        """,
        session_id,
        title,
        kb_json,
        provider,
        model,
        persona_id,
    )
    return _row_to_session(row)


async def delete_session(session_id: str) -> bool:
    pool = get_pool()
    val = await pool.fetchval(
        """
        UPDATE knowledge.chat_sessions
           SET deleted_at = NOW()
         WHERE id = $1 AND deleted_at IS NULL
         RETURNING id
        """,
        session_id,
    )
    return val is not None


# ═══ Messages ═══

async def append_message(
    session_id: str,
    *,
    role: str,
    content: str,
    output_mode: str | None = None,
    sources: list | None = None,
    retrieval: dict | None = None,
    images: list | None = None,
    video: dict | None = None,
) -> int | None:
    """Append a message to a session. Returns the new message id, or None if session missing."""
    if role not in ("user", "assistant", "system"):
        raise ValueError(f"invalid role: {role}")
    pool = get_pool()
    # 防御：如果会话已软删/不存在，静默跳过而非崩溃（RAG 热路径不能被这类错误阻断）
    exists = await pool.fetchval(
        "SELECT 1 FROM knowledge.chat_sessions WHERE id = $1 AND deleted_at IS NULL",
        session_id,
    )
    if not exists:
        logger.debug("append_message: session %s missing, skipping", session_id)
        return None
    new_id = await pool.fetchval(
        """
        INSERT INTO knowledge.chat_messages
            (session_id, role, content, output_mode, sources, retrieval, images, video)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb)
        RETURNING id
        """,
        session_id,
        role,
        content or "",
        output_mode,
        json.dumps(sources, ensure_ascii=False) if sources is not None else None,
        json.dumps(retrieval, ensure_ascii=False) if retrieval is not None else None,
        json.dumps(images, ensure_ascii=False) if images is not None else None,
        json.dumps(video, ensure_ascii=False) if video is not None else None,
    )
    return new_id


async def list_messages(session_id: str, *, limit: int = 500) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, session_id, role, content, output_mode,
               sources, retrieval, images, video, created_at
          FROM knowledge.chat_messages
         WHERE session_id = $1
         ORDER BY created_at ASC, id ASC
         LIMIT $2
        """,
        session_id,
        limit,
    )
    return [_row_to_message(r) for r in rows]


async def maybe_auto_title(session_id: str, first_user_content: str) -> None:
    """首次用户消息后，如果 title 还是空，用前 30 字回填；失败静默。"""
    if not first_user_content:
        return
    snippet = first_user_content.strip().splitlines()[0][:30]
    if not snippet:
        return
    pool = get_pool()
    try:
        await pool.execute(
            """
            UPDATE knowledge.chat_sessions
               SET title = $2, updated_at = NOW()
             WHERE id = $1
               AND (title IS NULL OR title = '')
               AND deleted_at IS NULL
            """,
            session_id,
            snippet,
        )
    except Exception:  # noqa: BLE001
        logger.debug("maybe_auto_title failed", exc_info=True)


# ═══ 便捷聚合 ═══

async def get_session_with_messages(session_id: str) -> dict | None:
    sess = await get_session(session_id)
    if sess is None:
        return None
    sess["messages"] = await list_messages(session_id)
    return sess
