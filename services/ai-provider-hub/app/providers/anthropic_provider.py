from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability
from app.schemas.ai import ChatResponse, Message, TokenUsage

_BASE_URL = "https://api.anthropic.com/v1"
_API_VERSION = "2023-06-01"


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    default_chat_model = "claude-sonnet-4-20250514"
    default_embedding_model = ""
    capabilities = {ProviderCapability.CHAT, ProviderCapability.VISION, ProviderCapability.ANALYSIS}

    def _headers(self) -> dict[str, str]:
        key = (settings.anthropic_api_key or "").strip()
        return {
            "x-api-key": key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

    def _has_key(self) -> bool:
        return bool((settings.anthropic_api_key or "").strip())

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        if not self._has_key():
            text = _last_prompt(messages)
            return _mock_response(text, model, self.name)

        system_prompt, api_messages = _split_system(messages)
        payload: dict = {"model": model, "messages": api_messages, "max_tokens": kwargs.get("max_tokens") or 2048}
        if system_prompt:
            payload["system"] = system_prompt
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]

        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(f"{_BASE_URL}/messages", headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        content_blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
        usage_data = data.get("usage", {})
        return ChatResponse(
            content=text,
            provider=self.name,
            model=data.get("model", model),
            usage=TokenUsage(
                prompt_tokens=usage_data.get("input_tokens", 0),
                completion_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            ),
        )

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        if not self._has_key():
            for word in _last_prompt(messages).split():
                yield f"{word} "
            return

        system_prompt, api_messages = _split_system(messages)
        payload: dict = {"model": model, "messages": api_messages, "max_tokens": kwargs.get("max_tokens") or 2048, "stream": True}
        if system_prompt:
            payload["system"] = system_prompt
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{_BASE_URL}/messages", headers=self._headers(), json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield delta.get("text", "")
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        raise NotImplementedError("Anthropic does not provide embedding models")

    async def analyze(self, content: str, prompt: str, model: str, **kwargs: object) -> dict:
        content_type = kwargs.get("content_type", "image")
        if content_type == "image" and content.startswith("http"):
            messages = [Message(role="user", content=[
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "url", "url": content}},
            ])]
        else:
            messages = [
                Message(role="system", content=f"Analyze the following {content_type} content in detail."),
                Message(role="user", content=f"{prompt}\n\nContent:\n{content}"),
            ]
        result = await self.chat(messages, model or self.default_chat_model)
        return {"analysis": result.content, "structured_data": {}, "usage": result.usage.model_dump()}

    async def list_models(self, api_key: str | None = None) -> list[str]:
        return [
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ]

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        key = (api_key or settings.anthropic_api_key or "").strip()
        if not key:
            return False, "未提供 Anthropic API Key", []
        try:
            headers = {"x-api-key": key, "anthropic-version": _API_VERSION, "content-type": "application/json"}
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.post(
                    f"{_BASE_URL}/messages",
                    headers=headers,
                    json={"model": "claude-3-5-haiku-20241022", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                )
                resp.raise_for_status()
            models = await self.list_models()
            return True, "连接成功", models
        except Exception as exc:
            return False, f"连接失败: {exc}", []

    async def health_check(self) -> bool:
        return self._has_key()


def _split_system(messages: list[Message]) -> tuple[str, list[dict]]:
    system = ""
    api_msgs: list[dict] = []
    for m in messages:
        if m.role == "system":
            system += (m.content if isinstance(m.content, str) else str(m.content)) + "\n"
        else:
            api_msgs.append({"role": m.role, "content": m.content})
    return system.strip(), api_msgs


def _last_prompt(messages: list[Message]) -> str:
    if not messages:
        return ""
    c = messages[-1].content
    return c if isinstance(c, str) else str(c)


def _mock_response(text: str, model: str, provider: str) -> ChatResponse:
    usage = TokenUsage(prompt_tokens=max(1, len(text) // 4), completion_tokens=max(1, len(text) // 8), total_tokens=max(1, len(text) // 3))
    return ChatResponse(content=f"[{provider}-mock] {text}", provider=provider, model=model, usage=usage)
