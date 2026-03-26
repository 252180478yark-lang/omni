from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import Enum

from app.schemas.ai import ChatResponse, Message, TokenUsage

_PLACEHOLDER_RE = re.compile(
    r"^(your_|my_|put_|enter_|insert_|replace_|changeme|sk-xxx|placeholder)",
    re.IGNORECASE,
)


def is_real_api_key(key: str | None) -> bool:
    """Return True only if *key* looks like a real credential, not a placeholder."""
    if not key or not key.strip():
        return False
    stripped = key.strip()
    if _PLACEHOLDER_RE.search(stripped):
        return False
    if stripped.endswith("_here") or stripped.endswith("_key"):
        return False
    return True


class ProviderCapability(str, Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    VISION = "vision"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    ANALYSIS = "analysis"
    FUNCTION_CALLING = "function_calling"


class BaseProvider(ABC):
    name: str = "base"
    default_chat_model: str = ""
    default_embedding_model: str = ""
    capabilities: set[ProviderCapability] = set()

    @abstractmethod
    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        raise NotImplementedError

    @abstractmethod
    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # noqa: unreachable — makes this a generator

    @abstractmethod
    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        raise NotImplementedError

    async def generate_image(self, prompt: str, model: str, **kwargs: object) -> dict:
        raise NotImplementedError(f"{self.name} does not support image generation")

    async def generate_video(self, prompt: str, model: str, **kwargs: object) -> dict:
        raise NotImplementedError(f"{self.name} does not support video generation")

    async def analyze(self, content: str, prompt: str, model: str, **kwargs: object) -> dict:
        raise NotImplementedError(f"{self.name} does not support multimodal analysis")

    async def health_check(self) -> bool:
        return True
