from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import httpx

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RawArticle:
    title: str
    url: str
    snippet: str
    source_type: str
    source_name: str | None
    language: str
    published_at: datetime | None


def handle_fetch_errors(source_type: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Wrap fetch methods and convert HTTP/parsing failures to safe defaults."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await func(*args, **kwargs)
            except httpx.TimeoutException:
                logger.warning("%s fetch timed out", source_type)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "%s fetch failed with status %s",
                    source_type,
                    exc.response.status_code if exc.response else "unknown",
                )
            except httpx.RequestError as exc:
                logger.warning("%s request error: %s", source_type, str(exc))
            except (TypeError, KeyError, ValueError) as exc:
                logger.warning("%s response parse error: %s", source_type, str(exc))
            return []

        return wrapper

    return decorator


class BaseFetcher(ABC):
    source_type: str
    language: str

    def __init__(self, client: httpx.AsyncClient, api_key: str):
        self.client = client
        self.api_key = api_key

    @abstractmethod
    async def fetch(
        self,
        keywords: list[str],
        freshness: str = "oneDay",
        max_results: int = 10,
    ) -> list[RawArticle]:
        """Fetch and normalize articles from a source."""
        raise NotImplementedError

    @staticmethod
    def parse_datetime(raw: Any) -> datetime | None:
        """Best-effort datetime parser for heterogeneous upstream formats."""
        if raw is None:
            return None

        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)

        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw, tz=timezone.utc)

        if not isinstance(raw, str):
            return None

        value = raw.strip()
        if not value:
            return None

        # Common ISO-8601 input.
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

        # Common datetime formats seen in news APIs.
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None
