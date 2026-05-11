from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability, is_real_api_key
from app.schemas.ai import ChatResponse, Message, TokenUsage

_BASE_URL = "https://api.openai.com/v1"

_RECOMMENDED_OPENAI_MODELS: tuple[str, ...] = (
    # Current general-purpose/frontier choices.
    "gpt-5.5",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    # ChatGPT snapshot alias for teams that want ChatGPT-like behavior.
    "gpt-5.2-chat-latest",
    # Image generation/editing models.
    "gpt-image-2",
    "gpt-image-1.5",
    "gpt-image-1",
    "gpt-image-1-mini",
)


class OpenAIProvider(BaseProvider):
    name = "openai"
    default_chat_model = "gpt-5.2-chat-latest"
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

        stream_timeout = httpx.Timeout(
            connect=30.0,
            read=settings.chat_stream_timeout_seconds,
            write=60.0,
            pool=30.0,
        )
        async with httpx.AsyncClient(timeout=stream_timeout) as client:
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
        import logging
        log = logging.getLogger("openai_provider.image")
        if not self._has_key():
            return {
                "images": [{"url": "https://placeholder.co/1536x1024?text=mock", "revised_prompt": prompt}],
                "usage": {"cost_usd": 0},
            }

        # 提取参考图 URL（dict 取 url 字段；str 直接用）
        raw_refs = kwargs.get("reference_images") or []
        print(
            f"[IMG-DBG] generate_image model={model} prompt_len={len(prompt or '')} "
            f"raw_refs_count={len(raw_refs)} raw_refs_types={[type(r).__name__ for r in raw_refs[:3]]}",
            flush=True,
        )
        ref_urls: list[str] = []
        for ref in raw_refs:
            if isinstance(ref, dict):
                u = ref.get("url") or ref.get("image_url")
                if isinstance(u, str) and u:
                    ref_urls.append(u)
            elif isinstance(ref, str) and ref:
                ref_urls.append(ref)
        print(
            f"[IMG-DBG] extracted ref_urls count={len(ref_urls)} "
            f"first={ref_urls[0][:80] if ref_urls else '(none)'}",
            flush=True,
        )

        chosen_model = model or "gpt-image-2"
        size = kwargs.get("size", "1536x1024")
        quality = kwargs.get("quality", "auto")
        n = int(kwargs.get("n", 1))

        if chosen_model.startswith("gpt-image"):
            if quality == "standard":
                quality = "auto"
            valid_sizes = {"1024x1024", "1024x1536", "1536x1024"}
            if size not in valid_sizes:
                size = "1536x1024"

        # 走 /images/edits（gpt-image 系列支持 image[] 多张参考图）— 只在有参考图时
        if ref_urls and chosen_model.startswith("gpt-image"):
            print(f"[IMG-DBG] → /images/edits (with {len(ref_urls)} refs, model={chosen_model})", flush=True)
            return await self._generate_image_with_refs(
                prompt=prompt, model=chosen_model, size=size, quality=quality, n=n, ref_urls=ref_urls
            )

        print(f"[IMG-DBG] → /images/generations (no refs or non-gpt-image model={chosen_model})", flush=True)

        # 没参考图 → 走 /images/generations 纯 text-to-image
        payload = {
            "model": chosen_model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": n,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{_BASE_URL}/images/generations", headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        images = []
        for img in data.get("data", []):
            url = img.get("url") or ""
            if not url and img.get("b64_json"):
                url = f"data:image/png;base64,{img['b64_json']}"
            images.append({"url": url, "revised_prompt": img.get("revised_prompt", "")})
        return {"images": images, "usage": {"cost_usd": 0.04 * len(images)}}

    async def _generate_image_with_refs(
        self,
        *,
        prompt: str,
        model: str,
        size: str,
        quality: str,
        n: int,
        ref_urls: list[str],
    ) -> dict:
        """gpt-image-1+ /images/edits 接口：multipart/form-data 上传 image[] 多张参考图。

        ref_urls 元素可以是：
          - data URL (data:image/png;base64,...) → 直接 base64 解码拿 bytes
          - http(s):// URL → httpx GET 下载拿 bytes
        """
        import base64
        # 1. 把所有参考图都解码/下载成 (filename, bytes, mime) 元组
        files_to_upload: list[tuple[str, bytes, str]] = []
        async with httpx.AsyncClient(timeout=60.0) as fetch_client:
            for i, url in enumerate(ref_urls):
                if url.startswith("data:"):
                    # data URL: data:[mime];base64,[content]
                    try:
                        header, b64_data = url.split(",", 1)
                        mime = "image/png"
                        if ";" in header and ":" in header:
                            mime_part = header.split(":", 1)[1].split(";", 1)[0]
                            if mime_part:
                                mime = mime_part
                        img_bytes = base64.b64decode(b64_data)
                    except Exception as exc:
                        raise ValueError(f"failed to decode data URL ref {i}: {exc}") from exc
                elif url.startswith(("http://", "https://")):
                    r = await fetch_client.get(url)
                    r.raise_for_status()
                    img_bytes = r.content
                    mime = r.headers.get("content-type", "image/png").split(";")[0]
                else:
                    raise ValueError(f"ref {i} unsupported scheme: {url[:50]}")
                ext = "png" if "png" in mime else "jpg" if ("jpeg" in mime or "jpg" in mime) else "png"
                files_to_upload.append((f"ref{i}.{ext}", img_bytes, mime))

        # 2. 组装 multipart files + form data
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for filename, content, mime in files_to_upload:
            files.append(("image[]", (filename, content, mime)))

        data = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": str(n),
        }

        # 3. POST /images/edits（multipart/form-data — 不要 Content-Type: application/json）
        headers = {k: v for k, v in self._headers().items() if k.lower() != "content-type"}
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{_BASE_URL}/images/edits",
                headers=headers,
                files=files,
                data=data,
            )
            resp.raise_for_status()
            ret = resp.json()

        images = []
        for img in ret.get("data", []):
            u = img.get("url") or ""
            if not u and img.get("b64_json"):
                u = f"data:image/png;base64,{img['b64_json']}"
            images.append({"url": u, "revised_prompt": img.get("revised_prompt", "")})
        # cost：edits 比 generations 略贵（OpenAI 定价 ~$0.06-0.16 per image）
        return {"images": images, "usage": {"cost_usd": 0.06 * len(images)}}

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
            return list(dict.fromkeys([
                self.default_chat_model,
                self.default_embedding_model,
                *_RECOMMENDED_OPENAI_MODELS,
            ]))
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.get(f"{_BASE_URL}/models", headers={"Authorization": f"Bearer {key}"})
                resp.raise_for_status()
                data = resp.json().get("data", [])
                ids = [item.get("id", "") for item in data if item.get("id")]
                ranked = [
                    m for m in ids
                    if (
                        m.startswith("gpt-")
                        or m.startswith("chatgpt-")
                        or "embedding" in m
                        or m.startswith("o")
                        or "dall-e" in m
                    )
                ]
                models = ranked[:80] if ranked else ids[:80]
                for default in [
                    self.default_chat_model,
                    self.default_embedding_model,
                    *_RECOMMENDED_OPENAI_MODELS,
                ]:
                    if default and default not in models:
                        models.append(default)
                return list(dict.fromkeys(m for m in models if m))
        except Exception:
            return list(dict.fromkeys([
                self.default_chat_model,
                self.default_embedding_model,
                *_RECOMMENDED_OPENAI_MODELS,
            ]))

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
