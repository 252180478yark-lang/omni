from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

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

    async def list_models(self, api_key: str | None = None) -> list[str]:
        key = (api_key or settings.gemini_api_key or "").strip()
        if not key:
            return [self.default_chat_model, self.default_embedding_model]
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": key},
                )
                resp.raise_for_status()
                rows = resp.json().get("models", [])
                names: list[str] = []
                for row in rows:
                    name = row.get("name", "")
                    if not name:
                        continue
                    # API returns "models/gemini-2.0-flash", normalize to bare id.
                    names.append(name.replace("models/", ""))
                ranked = [m for m in names if "gemini" in m or "embedding" in m]
                models = ranked[:80] if ranked else names[:80]
                if self.default_chat_model not in models:
                    models.insert(0, self.default_chat_model)
                if self.default_embedding_model not in models:
                    models.append(self.default_embedding_model)
                return list(dict.fromkeys([m for m in models if m]))
        except Exception:
            return [self.default_chat_model, self.default_embedding_model]

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        key = (api_key or settings.gemini_api_key or "").strip()
        if not key:
            return False, "未提供 Gemini API Key", []
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": key},
                )
                resp.raise_for_status()
                rows = resp.json().get("models", [])
                models = [row.get("name", "").replace("models/", "") for row in rows if row.get("name")]
            return True, f"连接成功，获取到 {len(models)} 个模型", models
        except Exception as exc:
            return False, f"连接失败: {exc}", []


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
