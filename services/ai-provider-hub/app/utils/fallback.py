from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.providers.base import ProviderCapability
from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)
T = TypeVar("T")

_MAX_RETRIES = 3
_BASE_DELAY = 1.0


class FallbackChain:
    def __init__(self, ordered: list[str] | None = None) -> None:
        self.ordered = ordered or ["gemini", "openai", "anthropic", "deepseek", "ollama"]

    def get_chain(self, preferred: str | None, registry: ProviderRegistry) -> list[str]:
        names = [name for name in self.ordered if name in registry.list_providers()]
        if preferred and preferred in names:
            names.remove(preferred)
            return [preferred, *names]
        return names

    def get_chain_for_capability(
        self,
        preferred: str | None,
        registry: ProviderRegistry,
        capability: ProviderCapability,
    ) -> list[str]:
        """Filter fallback chain to providers that have the required capability."""
        all_providers = registry.list_providers()
        names = [
            name for name in self.ordered
            if name in all_providers
            and capability.value in all_providers[name].get("capabilities", [])
        ]
        if preferred and preferred in names:
            names.remove(preferred)
            return [preferred, *names]
        return names


def _is_retryable(exc: Exception) -> bool:
    """Determine if an exception warrants a retry (transient errors)."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


async def call_with_retry(
    fn: Callable[..., Awaitable[T]],
    *args: object,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _BASE_DELAY,
    **kwargs: object,
) -> T:
    """Call an async function with exponential backoff retry on transient errors."""
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await fn(*args, **kwargs)
        except NotImplementedError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1 and _is_retryable(exc):
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Retryable error (attempt %d/%d, next in %.1fs): %s",
                    attempt + 1, max_retries, delay, exc,
                )
                await asyncio.sleep(delay)
                continue
            raise
    raise RuntimeError(f"call_with_retry exhausted: {last_error}")
