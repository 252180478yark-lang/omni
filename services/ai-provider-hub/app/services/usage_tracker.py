"""Usage tracking with Redis cost accumulation (MOD-07).

Dual-write: in-memory list (for /usage API) + Redis hash (for cost:daily:{provider}:{date}).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.schemas.ai import TokenUsage
from app.services.redis_client import incr_cost

logger = logging.getLogger(__name__)
_USAGE_STORE: list[dict[str, object]] = []


def record_usage(provider: str, model: str, usage: TokenUsage) -> None:
    now = datetime.now(UTC)
    _USAGE_STORE.append(
        {
            "provider": provider,
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "timestamp": now.isoformat(),
        }
    )

    # Fire-and-forget Redis cost accumulation
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            incr_cost(provider, now.strftime("%Y-%m-%d"), usage.prompt_tokens, usage.completion_tokens)
        )
    except RuntimeError:
        pass


def latest_usage(limit: int = 20) -> list[dict[str, object]]:
    return _USAGE_STORE[-limit:]
