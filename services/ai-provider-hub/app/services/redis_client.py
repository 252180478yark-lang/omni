"""Shared async Redis client for ai-provider-hub (MOD-07).

Key patterns:
  cost:daily:{provider}:{YYYY-MM-DD}  — daily token accumulator  (HINCRBY)
  rate:{provider}:{window_key}         — sliding-window rate limit (INCR + EXPIRE)
  video:task:{task_id}                 — video generation task     (HSET + EXPIRE)
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_redis():
    global _client
    if _client is not None:
        return _client
    url = settings.redis_url
    if not url:
        return None
    try:
        import redis.asyncio as aioredis
        _client = aioredis.from_url(url, decode_responses=True)
        return _client
    except Exception:
        logger.warning("Redis unavailable — all state falls back to in-memory", exc_info=True)
        return None


# ── Cost tracking ──────────────────────────────────────────────

async def incr_cost(provider: str, date_str: str, prompt: int, completion: int) -> None:
    r = _get_redis()
    if r is None:
        return
    key = f"cost:daily:{provider}:{date_str}"
    try:
        pipe = r.pipeline(transaction=False)
        pipe.hincrby(key, "prompt_tokens", prompt)
        pipe.hincrby(key, "completion_tokens", completion)
        pipe.hincrby(key, "total_tokens", prompt + completion)
        pipe.hincrby(key, "request_count", 1)
        pipe.expire(key, 90 * 86400)  # 90-day retention
        await pipe.execute()
    except Exception:
        logger.debug("Redis cost incr failed", exc_info=True)


async def get_daily_cost(provider: str, date_str: str) -> dict[str, int]:
    r = _get_redis()
    if r is None:
        return {}
    try:
        key = f"cost:daily:{provider}:{date_str}"
        data = await r.hgetall(key)
        return {k: int(v) for k, v in data.items()} if data else {}
    except Exception:
        return {}


# ── Rate limiting ──────────────────────────────────────────────

async def check_rate_limit(provider: str, window_seconds: int = 60, max_requests: int = 60) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    r = _get_redis()
    if r is None:
        return True
    import time
    window_key = str(int(time.time()) // window_seconds)
    key = f"rate:{provider}:{window_key}"
    try:
        pipe = r.pipeline(transaction=False)
        pipe.incr(key)
        pipe.expire(key, window_seconds + 5)
        results = await pipe.execute()
        current = results[0]
        return int(current) <= max_requests
    except Exception:
        return True  # fail-open


# ── Video task store ───────────────────────────────────────────

_VIDEO_TASK_TTL = 24 * 3600  # 24h

async def set_video_task(task_id: str, data: dict[str, Any]) -> None:
    r = _get_redis()
    if r is None:
        return
    key = f"video:task:{task_id}"
    try:
        await r.hset(key, mapping={k: str(v) if v is not None else "" for k, v in data.items()})
        await r.expire(key, _VIDEO_TASK_TTL)
    except Exception:
        logger.debug("Redis video task set failed", exc_info=True)


async def get_video_task(task_id: str) -> dict[str, str] | None:
    r = _get_redis()
    if r is None:
        return None
    key = f"video:task:{task_id}"
    try:
        data = await r.hgetall(key)
        return data if data else None
    except Exception:
        return None
