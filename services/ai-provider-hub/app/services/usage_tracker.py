from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.ai import TokenUsage

_USAGE_STORE: list[dict[str, object]] = []


def record_usage(provider: str, model: str, usage: TokenUsage) -> None:
    _USAGE_STORE.append(
        {
            "provider": provider,
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )


def latest_usage(limit: int = 20) -> list[dict[str, object]]:
    return _USAGE_STORE[-limit:]
