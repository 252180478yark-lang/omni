from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import Enum

from app.schemas.ai import ChatResponse, Message, TokenUsage


class ProviderCapability(str, Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    VISION = "vision"
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

    @abstractmethod
    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        raise NotImplementedError
