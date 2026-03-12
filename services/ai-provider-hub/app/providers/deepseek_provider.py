from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability
from app.schemas.ai import ChatResponse, Message, TokenUsage

_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekProvider(BaseProvider):
    """DeepSeek provider — uses OpenAI-compatible API format."""

    name = "deepseek"
    default_chat_model = "deepseek-chat"
    default_embedding_model = ""
    capabilities = {ProviderCapability.CHAT}

    def _headers(self) -> dict[str, str]:
        key = (settings.deepseek_api_key or "").strip()
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _has_key(self) -> bool:
        return bool((settings.deepseek_api_key or "").strip())

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        if not self._has_key():
            text = _last_prompt(messages)
            usage = _usage_estimate(text)
            return ChatResponse(content=f"[deepseek-mock] {text}", provider=self.name, model=model, usage=usage)

        payload: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]

        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(f"{_BASE_URL}/chat/completions", headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        usage_data = data.get("usage", {})
        return ChatResponse(
            content=choice["message"]["content"],
            provider=self.name,
            model=data.get("model", model),
            usage=TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            ),
        )

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        if not self._has_key():
            for word in _last_prompt(messages).split():
                yield f"{word} "
            return

        payload: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{_BASE_URL}/chat/completions", headers=self._headers(), json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        raise NotImplementedError("DeepSeek does not provide embedding models via this provider")

    async def list_models(self, api_key: str | None = None) -> list[str]:
        return ["deepseek-chat", "deepseek-reasoner"]

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        key = (api_key or settings.deepseek_api_key or "").strip()
        if not key:
            return False, "未提供 DeepSeek API Key", []
        try:
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.post(
                    f"{_BASE_URL}/chat/completions",
                    headers=headers,
                    json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                )
                resp.raise_for_status()
            models = await self.list_models()
            return True, "连接成功", models
        except Exception as exc:
            return False, f"连接失败: {exc}", []

    async def health_check(self) -> bool:
        return self._has_key()


def _last_prompt(messages: list[Message]) -> str:
    if not messages:
        return ""
    c = messages[-1].content
    return c if isinstance(c, str) else str(c)


def _usage_estimate(text: str) -> TokenUsage:
    pt = max(1, len(text) // 4)
    ct = max(1, pt // 2)
    return TokenUsage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct)
