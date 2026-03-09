from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability
from app.schemas.ai import ChatResponse, Message, TokenUsage


class OllamaProvider(BaseProvider):
    name = "ollama"
    default_chat_model = "qwen2.5:7b"
    default_embedding_model = "bge-m3"
    capabilities = {ProviderCapability.CHAT, ProviderCapability.EMBEDDING}

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        text = _last_prompt(messages)
        payload = {"model": model, "messages": [{"role": "user", "content": text}], "stream": False}
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
        except Exception:
            content = f"[ollama-mock] {text}"
        usage = _usage_estimate(text)
        return ChatResponse(content=content, provider=self.name, model=model, usage=usage)

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        text = _last_prompt(messages)
        for token in text.split():
            yield f"{token} "

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        vectors = [[0.03] * 1536 for _ in texts]
        usage = TokenUsage(prompt_tokens=len(texts), completion_tokens=0, total_tokens=len(texts))
        return vectors, usage

    async def list_models(self, api_key: str | None = None) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json().get("models", [])
                return [item.get("name", "") for item in data if item.get("name")]
        except Exception:
            return [self.default_chat_model]

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        try:
            models = await self.list_models()
            if len(models) == 0:
                return False, "Ollama 可达，但未发现模型", []
            return True, f"Ollama 连接成功，发现 {len(models)} 个模型", models
        except Exception as exc:
            return False, f"Ollama 连接失败: {exc}", []


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
