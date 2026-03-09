from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability
from app.schemas.ai import ChatResponse, Message, TokenUsage


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_chat_model = "gemini-2.0-flash"
    default_embedding_model = "text-embedding-004"
    capabilities = {ProviderCapability.CHAT, ProviderCapability.EMBEDDING}

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        content = _last_prompt(messages)
        usage = _usage_estimate(content)
        prefix = "[gemini-mock]" if not settings.gemini_api_key else "[gemini]"
        return ChatResponse(content=f"{prefix} {content}", provider=self.name, model=model, usage=usage)

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        text = _last_prompt(messages)
        for token in text.split():
            yield f"{token} "

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        vectors = [[0.02] * 1536 for _ in texts]
        usage = TokenUsage(prompt_tokens=len(texts), completion_tokens=0, total_tokens=len(texts))
        return vectors, usage


def _last_prompt(messages: list[Message]) -> str:
    if not messages:
        return ""
    content = messages[-1].content
    return content if isinstance(content, str) else str(content)


def _usage_estimate(text: str) -> TokenUsage:
    prompt_tokens = max(1, len(text) // 4)
    completion_tokens = max(1, prompt_tokens // 2)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
