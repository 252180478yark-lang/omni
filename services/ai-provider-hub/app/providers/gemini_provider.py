from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability
from app.schemas.ai import ChatResponse, Message, TokenUsage

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_EMBED_DIMENSION = 1536
_EMBED_BATCH_LIMIT = 100

_THINKING_MODELS = frozenset({
    "gemini-3-pro-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
})
_THINKING_MIN_OUTPUT_TOKENS = 16384


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_chat_model = "gemini-3.1-pro-preview"
    default_embedding_model = "gemini-embedding-2-preview"
    capabilities = {ProviderCapability.CHAT, ProviderCapability.EMBEDDING, ProviderCapability.VISION}

    def _key(self, **kwargs: object) -> str:
        return (str(kwargs.get("api_key", "")) or settings.gemini_api_key or "").strip()

    # ─── Chat ───

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        key = self._key(**kwargs)
        if not key:
            raise RuntimeError("Gemini API Key 未配置")

        model_id = model or self.default_chat_model
        url = f"{_API_BASE}/models/{model_id}:generateContent"
        body = _build_chat_body(messages, model=model_id, **kwargs)

        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(url, params={"key": key}, json=body)
            resp.raise_for_status()
            data = resp.json()

        text = _extract_text(data)
        usage = _extract_usage(data)
        return ChatResponse(content=text, provider=self.name, model=model_id, usage=usage)

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        key = self._key(**kwargs)
        if not key:
            raise RuntimeError("Gemini API Key 未配置")

        model_id = model or self.default_chat_model
        url = f"{_API_BASE}/models/{model_id}:streamGenerateContent"
        body = _build_chat_body(messages, model=model_id, **kwargs)

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", url, params={"key": key, "alt": "sse"}, json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        parts = (
                            chunk.get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [])
                        )
                        for part in parts:
                            if text := part.get("text"):
                                yield text
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

    # ─── Embedding ───

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        key = self._key(**kwargs)
        if not key:
            raise RuntimeError("Gemini API Key 未配置")

        model_id = model or self.default_embedding_model
        model_ref = f"models/{model_id}"
        total_tokens = 0
        all_vectors: list[list[float]] = []

        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            for start in range(0, len(texts), _EMBED_BATCH_LIMIT):
                batch = texts[start : start + _EMBED_BATCH_LIMIT]

                if len(batch) == 1:
                    url = f"{_API_BASE}/{model_ref}:embedContent"
                    body = {
                        "model": model_ref,
                        "content": {"parts": [{"text": batch[0]}]},
                        "outputDimensionality": _EMBED_DIMENSION,
                    }
                    resp = await client.post(url, params={"key": key}, json=body)
                    resp.raise_for_status()
                    data = resp.json()
                    all_vectors.append(data["embedding"]["values"])
                    total_tokens += len(batch[0]) // 4
                else:
                    url = f"{_API_BASE}/{model_ref}:batchEmbedContents"
                    requests = [
                        {
                            "model": model_ref,
                            "content": {"parts": [{"text": t}]},
                            "outputDimensionality": _EMBED_DIMENSION,
                        }
                        for t in batch
                    ]
                    resp = await client.post(url, params={"key": key}, json={"requests": requests})
                    resp.raise_for_status()
                    data = resp.json()
                    for emb in data.get("embeddings", []):
                        all_vectors.append(emb["values"])
                    total_tokens += sum(len(t) // 4 for t in batch)

        usage = TokenUsage(prompt_tokens=total_tokens, completion_tokens=0, total_tokens=total_tokens)
        return all_vectors, usage

    # ─── Model Discovery ───

    async def list_models(self, api_key: str | None = None) -> list[str]:
        key = (api_key or settings.gemini_api_key or "").strip()
        if not key:
            return [self.default_chat_model, self.default_embedding_model]
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.get(f"{_API_BASE}/models", params={"key": key})
                resp.raise_for_status()
                rows = resp.json().get("models", [])
                names: list[str] = []
                for row in rows:
                    name = row.get("name", "")
                    if not name:
                        continue
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
                resp = await client.get(f"{_API_BASE}/models", params={"key": key})
                resp.raise_for_status()
                rows = resp.json().get("models", [])
                models = [row.get("name", "").replace("models/", "") for row in rows if row.get("name")]
            return True, f"连接成功，获取到 {len(models)} 个模型", models
        except Exception as exc:
            return False, f"连接失败: {exc}", []


# ─── Helpers ───

def _convert_content_to_parts(content: str | list) -> list[dict]:
    """Convert OpenAI-style message content to Gemini parts format.

    Handles both plain text and multimodal content lists with text/image_url parts.
    """
    if isinstance(content, str):
        return [{"text": content}]

    parts: list[dict] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append({"text": str(item)})
            continue
        t = item.get("type", "text")
        if t == "text":
            parts.append({"text": item.get("text", "")})
        elif t == "image_url":
            url_info = item.get("image_url", {})
            url = url_info.get("url", "") if isinstance(url_info, dict) else str(url_info)
            if url.startswith("data:"):
                # data:image/png;base64,XXXX...
                header, _, b64data = url.partition(",")
                mime = header.split(";")[0].replace("data:", "")
                parts.append({"inline_data": {"mime_type": mime, "data": b64data}})
            else:
                parts.append({"text": f"[Image: {url}]"})
        else:
            parts.append({"text": str(item)})
    return parts


def _build_chat_body(messages: list[Message], model: str = "", **kwargs: object) -> dict:
    contents: list[dict] = []
    system_instruction: dict | None = None

    for msg in messages:
        if msg.role == "system":
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            system_instruction = {"parts": [{"text": text}]}
            continue
        role = "model" if msg.role == "assistant" else "user"
        parts = _convert_content_to_parts(msg.content)
        contents.append({"role": role, "parts": parts})

    body: dict = {"contents": contents}
    if system_instruction:
        body["systemInstruction"] = system_instruction

    is_thinking = any(t in model for t in ("3-pro", "3.1-", "2.5-pro", "2.5-flash"))
    gen_config: dict = {}
    if (temp := kwargs.get("temperature")) is not None:
        gen_config["temperature"] = float(str(temp))
    if (max_tok := kwargs.get("max_tokens")) is not None:
        requested = int(str(max_tok))
        gen_config["maxOutputTokens"] = max(requested, _THINKING_MIN_OUTPUT_TOKENS) if is_thinking else requested
    elif is_thinking:
        gen_config["maxOutputTokens"] = _THINKING_MIN_OUTPUT_TOKENS
    if gen_config:
        body["generationConfig"] = gen_config

    return body


def _extract_text(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError):
        return ""


def _extract_usage(data: dict) -> TokenUsage:
    meta = data.get("usageMetadata", {})
    return TokenUsage(
        prompt_tokens=meta.get("promptTokenCount", 0),
        completion_tokens=meta.get("candidatesTokenCount", 0),
        total_tokens=meta.get("totalTokenCount", 0),
    )
