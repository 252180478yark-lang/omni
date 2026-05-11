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

_THINKING_MIN_OUTPUT_TOKENS = 16384


def _gemini_high_output_floor_model(model: str) -> bool:
    """Gemini 1.5 / 2.x / 3.x 等长上下文模型：保证 maxOutputTokens 下限，避免默认值过小截断长回答。"""
    m = (model or "").lower()
    return any(
        tok in m
        for tok in (
            "1.5-pro",
            "1.5-flash",
            "2.5-pro",
            "2.5-flash",
            "3-pro",
            "3.1-",
            "gemini-2.0",
            "gemini-2.5",
            "gemini-3",
        )
    )


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_chat_model = "gemini-3-flash-preview"
    default_embedding_model = "gemini-embedding-2-preview"
    capabilities = {
        ProviderCapability.CHAT, ProviderCapability.EMBEDDING,
        ProviderCapability.VISION, ProviderCapability.IMAGE_GENERATION,
        ProviderCapability.ANALYSIS,
    }

    def _key(self, **kwargs: object) -> str:
        return (str(kwargs.get("api_key", "")) or settings.gemini_api_key or "").strip()

    # ─── Chat ───

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        import asyncio
        key = self._key(**kwargs)
        if not key:
            raise RuntimeError("Gemini API Key 未配置")

        model_id = model or self.default_chat_model
        url = f"{_API_BASE}/models/{model_id}:generateContent"
        body = _build_chat_body(messages, model=model_id, **kwargs)

        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                read_timeout = max(
                    settings.request_timeout_seconds,
                    settings.chat_stream_timeout_seconds,
                )
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=30.0, read=read_timeout, write=60.0, pool=30.0),
                ) as client:
                    resp = await client.post(url, params={"key": key}, json=body)
                    if resp.status_code == 400:
                        err = resp.json().get("error", {})
                        reason = err.get("message", resp.text[:200])
                        raise RuntimeError(f"Gemini API error (400): {reason}")
                    resp.raise_for_status()
                    data = resp.json()
                text = _extract_text(data)
                usage = _extract_usage(data)
                return ChatResponse(content=text, provider=self.name, model=model_id, usage=usage)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < 4:
                    await asyncio.sleep(min(2 ** attempt, 8))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                    last_exc = exc
                    await asyncio.sleep(min(2 ** attempt, 8))
                else:
                    raise
        raise last_exc

    async def analyze(
        self,
        content: str,
        prompt: str,
        model: str,
        **kwargs: object,
    ) -> dict:
        """Vision/document analysis via Gemini's native multimodal API.

        `content` is base64-encoded for image/video; `content_type` (kwarg) is
        'image'/'video'/'document'. Builds a Gemini request with inline_data.
        """
        import asyncio
        key = self._key(**kwargs)
        if not key:
            raise RuntimeError("Gemini API Key 未配置")

        content_type = str(kwargs.get("content_type", "image")).lower()
        # Default to image/png; Gemini accepts most common mime types
        mime_map = {
            "image": "image/png",
            "video": "video/mp4",
            "document": "application/pdf",
        }
        mime = str(kwargs.get("mime_type", "")) or mime_map.get(content_type, "image/png")
        # If content already looks like a data URL, strip the prefix
        if content.startswith("data:") and "," in content:
            content = content.split(",", 1)[1]

        model_id = model or self.default_chat_model
        url = f"{_API_BASE}/models/{model_id}:generateContent"
        body = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt or "Analyze this content"},
                    {"inline_data": {"mime_type": mime, "data": content}},
                ],
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=30.0, read=120.0, write=60.0, pool=30.0),
                ) as client:
                    resp = await client.post(url, params={"key": key}, json=body)
                    if resp.status_code == 400:
                        err = resp.json().get("error", {})
                        raise RuntimeError(f"Gemini analyze 400: {err.get('message', resp.text[:200])}")
                    resp.raise_for_status()
                    data = resp.json()

                text = _extract_text(data)
                usage = _extract_usage(data)

                # Try to parse text as JSON (since responseMimeType=application/json)
                structured: dict = {}
                try:
                    structured = json.loads(text) if text else {}
                except Exception:
                    # Fallback: find first {...} block
                    import re
                    m = re.search(r"\{[\s\S]*\}", text or "")
                    if m:
                        try:
                            structured = json.loads(m.group(0))
                        except Exception:
                            structured = {}

                return {
                    "analysis": text,
                    "structured_data": structured,
                    "usage": {
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                    },
                }
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(min(2 ** attempt, 4))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    last_exc = exc
                    await asyncio.sleep(min(2 ** attempt, 4))
                else:
                    raise
        raise last_exc

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        key = self._key(**kwargs)
        if not key:
            raise RuntimeError("Gemini API Key 未配置")

        model_id = model or self.default_chat_model
        url = f"{_API_BASE}/models/{model_id}:streamGenerateContent"
        body = _build_chat_body(messages, model=model_id, **kwargs)

        stream_timeout = httpx.Timeout(
            connect=30.0,
            read=settings.chat_stream_timeout_seconds,
            write=60.0,
            pool=30.0,
        )
        async with httpx.AsyncClient(timeout=stream_timeout) as client:
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

    # ─── Image Generation (Nano Banana 2) ───

    async def generate_image(self, prompt: str, model: str, **kwargs: object) -> dict:
        import base64

        key = self._key(**kwargs)
        if not key:
            return {
                "images": [{"url": "https://placeholder.co/1536x1024?text=gemini-mock", "revised_prompt": prompt}],
                "usage": {"cost_usd": 0},
            }

        model_id = model or "gemini-3.1-flash-image-preview"
        url = f"{_API_BASE}/models/{model_id}:generateContent"

        size_map = {"1024x1024": "1K", "1536x1024": "1K", "1024x1536": "1K", "2048x2048": "2K", "4096x4096": "4K"}
        raw_size = str(kwargs.get("size", "1536x1024"))
        image_size = size_map.get(raw_size, "1K")

        aspect_map = {"1024x1024": "1:1", "1536x1024": "16:9", "1024x1536": "9:16"}
        aspect = aspect_map.get(raw_size, "16:9")

        # ── W4-B 14.4 phase D：多参考图（face_refs / product_refs / style_refs）支持 ──
        # 入参 reference_images: list[str | {url, type, weight}]，data URL 或 http(s) URL 都接受
        # Gemini API 支持多模态：parts 数组里混合 text + inline_data (base64)
        raw_refs = kwargs.get("reference_images") or []
        ref_urls: list[str] = []
        for r in raw_refs:
            if isinstance(r, str):
                ref_urls.append(r)
            elif isinstance(r, dict):
                u = r.get("url") or ""
                if u:
                    ref_urls.append(u)
        ref_parts: list[dict] = []
        if ref_urls:
            print(f"[IMG-DBG][gemini] reference_images count={len(ref_urls)} first={ref_urls[0][:60]}", flush=True)
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as fetch_client:
                for i, ru in enumerate(ref_urls):
                    try:
                        if ru.startswith("data:"):
                            # data:image/png;base64,XXX
                            header, b64_data = ru.split(",", 1)
                            mime = "image/png"
                            if ";" in header and ":" in header:
                                mime_part = header.split(":", 1)[1].split(";", 1)[0]
                                if mime_part:
                                    mime = mime_part
                            ref_parts.append({"inline_data": {"mime_type": mime, "data": b64_data}})
                        elif ru.startswith(("http://", "https://")):
                            rr = await fetch_client.get(ru)
                            rr.raise_for_status()
                            mime = rr.headers.get("content-type", "image/png").split(";")[0]
                            b64_data = base64.b64encode(rr.content).decode("ascii")
                            ref_parts.append({"inline_data": {"mime_type": mime, "data": b64_data}})
                        else:
                            print(f"[IMG-DBG][gemini] skip ref {i} unsupported scheme: {ru[:40]}", flush=True)
                    except Exception as exc:
                        print(f"[IMG-DBG][gemini] ref {i} fetch failed: {exc}", flush=True)

        # parts 顺序：先 text 再 reference images（让模型把后续 inline_data 当参考）
        parts: list[dict] = [{"text": prompt}, *ref_parts]
        print(f"[IMG-DBG][gemini] → {model_id} parts: 1 text + {len(ref_parts)} refs", flush=True)

        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {"aspectRatio": aspect, "imageSize": image_size},
            },
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=180.0, write=120.0, pool=30.0)) as client:
            resp = await client.post(url, params={"key": key}, json=body)
            resp.raise_for_status()
            data = resp.json()

        images = []
        try:
            parts = data["candidates"][0]["content"]["parts"]
            for part in parts:
                inline = part.get("inlineData")
                if inline and inline.get("data"):
                    mime = inline.get("mimeType", "image/png")
                    b64 = inline["data"]
                    data_url = f"data:{mime};base64,{b64}"
                    images.append({"url": data_url, "revised_prompt": prompt})
        except (KeyError, IndexError):
            pass

        if not images:
            images.append({"url": "", "revised_prompt": prompt})
        return {"images": images, "usage": {"cost_usd": 0.01 * len(images)}}

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
        import asyncio
        max_retries = 8
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                    resp = await client.get(f"{_API_BASE}/models", params={"key": key})
                    resp.raise_for_status()
                    rows = resp.json().get("models", [])
                    models = [row.get("name", "").replace("models/", "") for row in rows if row.get("name")]
                return True, f"连接成功，获取到 {len(models)} 个模型", models
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(2 ** attempt, 8))
        return False, f"连接失败: {last_exc}", []


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

    long_out = _gemini_high_output_floor_model(model)
    gen_config: dict = {}
    if (temp := kwargs.get("temperature")) is not None:
        gen_config["temperature"] = float(str(temp))
    if (max_tok := kwargs.get("max_tokens")) is not None:
        requested = int(str(max_tok))
        gen_config["maxOutputTokens"] = max(requested, _THINKING_MIN_OUTPUT_TOKENS) if long_out else requested
    elif long_out:
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
