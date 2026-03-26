from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability, is_real_api_key
from app.schemas.ai import ChatResponse, Message, TokenUsage

_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(BaseProvider):
    name = "openai"
    default_chat_model = "gpt-4o-mini"
    default_embedding_model = "text-embedding-3-small"
    capabilities = {
        ProviderCapability.CHAT,
        ProviderCapability.EMBEDDING,
        ProviderCapability.IMAGE_GENERATION,
        ProviderCapability.VISION,
        ProviderCapability.ANALYSIS,
    }

    def _headers(self, api_key: str | None = None) -> dict[str, str]:
        key = (api_key or settings.openai_api_key or "").strip()
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _has_key(self) -> bool:
        return is_real_api_key(settings.openai_api_key)

    # ── Chat ──

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        if not self._has_key():
            return _mock_response(messages, model, self.name)

        payload = {
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

        payload = {
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

    # ── Embedding ──

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        if not self._has_key():
            vectors = [[0.01] * 1536 for _ in texts]
            return vectors, TokenUsage(prompt_tokens=len(texts), total_tokens=len(texts))

        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(
                f"{_BASE_URL}/embeddings",
                headers=self._headers(),
                json={"input": texts, "model": model},
            )
            resp.raise_for_status()
            data = resp.json()

        embeddings = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        return embeddings, usage

    # ── Image Generation ──

    async def generate_image(self, prompt: str, model: str, **kwargs: object) -> dict:
        if not self._has_key():
            return {
                "images": [{"url": "https://placeholder.co/1024x1024?text=mock", "revised_prompt": prompt}],
                "usage": {"cost_usd": 0},
            }

        payload = {
            "model": model or "dall-e-3",
            "prompt": prompt,
            "size": kwargs.get("size", "1024x1024"),
            "quality": kwargs.get("quality", "standard"),
            "n": kwargs.get("n", 1),
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{_BASE_URL}/images/generations", headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        images = [{"url": img.get("url", ""), "revised_prompt": img.get("revised_prompt", "")} for img in data.get("data", [])]
        return {"images": images, "usage": {"cost_usd": 0.04 * len(images)}}

    # ── Analysis (Vision) ──

    async def analyze(self, content: str, prompt: str, model: str, **kwargs: object) -> dict:
        content_type = kwargs.get("content_type", "image")
        if content_type == "image" and (content.startswith("http") or content.startswith("data:")):
            messages = [Message(role="user", content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": content}},
            ])]
        else:
            messages = [
                Message(role="system", content=f"Analyze the following {content_type} content."),
                Message(role="user", content=f"{prompt}\n\nContent:\n{content}"),
            ]

        result = await self.chat(messages, model or "gpt-4o")
        return {
            "analysis": result.content,
            "structured_data": {},
            "usage": result.usage.model_dump(),
        }

    # ── Utility ──

    async def list_models(self, api_key: str | None = None) -> list[str]:
        key = (api_key or settings.openai_api_key or "").strip()
        if not key:
            return [self.default_chat_model, self.default_embedding_model]
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.get(f"{_BASE_URL}/models", headers={"Authorization": f"Bearer {key}"})
                resp.raise_for_status()
                data = resp.json().get("data", [])
                ids = [item.get("id", "") for item in data if item.get("id")]
                ranked = [m for m in ids if m.startswith("gpt-") or "embedding" in m or m.startswith("o") or "dall-e" in m]
                models = ranked[:80] if ranked else ids[:80]
                for default in [self.default_chat_model, self.default_embedding_model]:
                    if default and default not in models:
                        models.append(default)
                return list(dict.fromkeys(m for m in models if m))
        except Exception:
            return [self.default_chat_model, self.default_embedding_model]

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        key = (api_key or settings.openai_api_key or "").strip()
        if not key:
            return False, "未提供 OpenAI API Key", []
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.get(f"{_BASE_URL}/models", headers={"Authorization": f"Bearer {key}"})
                resp.raise_for_status()
                models = [item.get("id", "") for item in resp.json().get("data", []) if item.get("id")]
            return True, f"连接成功，获取到 {len(models)} 个模型", models
        except Exception as exc:
            return False, f"连接失败: {exc}", []

    async def health_check(self) -> bool:
        return self._has_key()


def _mock_response(messages: list[Message], model: str, provider: str) -> ChatResponse:
    text = _last_prompt(messages)
    usage = TokenUsage(prompt_tokens=max(1, len(text) // 4), completion_tokens=max(1, len(text) // 8), total_tokens=max(1, len(text) // 4 + len(text) // 8))
    return ChatResponse(content=f"[{provider}-mock] {text}", provider=provider, model=model, usage=usage)


def _last_prompt(messages: list[Message]) -> str:
    if not messages:
        return ""
    content = messages[-1].content
    return content if isinstance(content, str) else str(content)
