"""Redis-backed chat session store (MOD-07).

Key pattern: chat:session:{session_id}
Stores the last N conversation turns as a JSON list.
TTL: 24 hours.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_MAX_TURNS = 20
_SESSION_TTL = 24 * 3600  # 24h
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        return _redis_client
    except Exception:
        logger.warning("Redis unavailable, session memory disabled", exc_info=True)
        return None


def _session_key(session_id: str) -> str:
    return f"chat:session:{session_id}"


async def get_history(session_id: str) -> list[dict[str, str]]:
    """Retrieve the conversation history for a session."""
    r = _get_redis()
    if r is None:
        return []
    try:
        data = await r.get(_session_key(session_id))
        if data:
            turns = json.loads(data)
            return turns if isinstance(turns, list) else []
        return []
    except Exception:
        logger.debug("Redis session read failed", exc_info=True)
        return []


async def append_turn(session_id: str, role: str, content: str) -> None:
    """Append a turn (user or assistant) to the session history."""
    r = _get_redis()
    if r is None:
        return
    try:
        key = _session_key(session_id)
        history = await get_history(session_id)
        history.append({"role": role, "content": content})
        # Keep only last N turns
        if len(history) > _MAX_TURNS * 2:
            history = history[-_MAX_TURNS * 2:]
        await r.setex(key, _SESSION_TTL, json.dumps(history, ensure_ascii=False))
    except Exception:
        logger.debug("Redis session write failed", exc_info=True)


async def clear_session(session_id: str) -> None:
    """Clear a session's history."""
    r = _get_redis()
    if r is None:
        return
    try:
        await r.delete(_session_key(session_id))
    except Exception:
        logger.debug("Redis session clear failed", exc_info=True)
