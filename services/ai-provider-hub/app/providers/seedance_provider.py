"""Seedance 2.0 video generation provider — 火山方舟 (Volcengine Ark) API.

Based on the official Seedance 2.0 tutorial:
  - API base: https://ark.cn-beijing.volces.com/api/v3
  - Auth: Bearer ARK_API_KEY
  - Models: doubao-seedance-2-0-260128 (quality), doubao-seedance-2-0-fast-260128 (fast)
  - Capabilities: multi-modal reference, video edit, video extend, web search, virtual avatars
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability, is_real_api_key
from app.schemas.ai import ChatResponse, Message, TokenUsage, VideoContentItem

logger = logging.getLogger(__name__)

_ARK_API_BASE = "https://ark.cn-beijing.volces.com/api/v3"


class SeedanceProvider(BaseProvider):
    name = "seedance"
    default_chat_model = ""
    default_embedding_model = ""
    capabilities = {ProviderCapability.VIDEO_GENERATION}

    # ── auth ──

    def _get_api_key(self) -> str:
        """Prefer ark_api_key; fall back to legacy seedance_access_key."""
        key = (settings.ark_api_key or "").strip()
        if is_real_api_key(key):
            return key
        return (settings.seedance_access_key or "").strip()

    def _has_key(self) -> bool:
        return is_real_api_key(self._get_api_key())

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_api_key()}",
        }

    def _pick_model(self, model: str | None = None, quality: str = "standard") -> str:
        if model and model.startswith("doubao-"):
            return model
        if quality == "fast":
            return settings.seedance_fast_model
        return settings.seedance_model

    # ── connection test ──

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        key = (api_key or self._get_api_key() or "").strip()
        if not is_real_api_key(key):
            return False, "未提供 Seedance (火山方舟) API Key", []
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_ARK_API_BASE}/models",
                    headers=headers,
                )
                resp.raise_for_status()
            return True, "Seedance (火山方舟) 连接成功", []
        except httpx.HTTPStatusError as exc:
            return False, f"连接失败 (HTTP {exc.response.status_code}): {exc.response.text[:200]}", []
        except Exception as exc:
            return False, f"连接失败: {exc}", []

    # ── unsupported methods ──

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        raise NotImplementedError("Seedance does not support chat")

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        raise NotImplementedError("Seedance does not support chat streaming")
        yield  # noqa: unreachable

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        raise NotImplementedError("Seedance does not support embeddings")

    # ── content building ──

    @staticmethod
    def _build_content(
        prompt: str,
        *,
        content_items: list[VideoContentItem] | None = None,
        reference_images: list[str] | None = None,
        reference_videos: list[str] | None = None,
        reference_audios: list[str] | None = None,
        first_frame: str | None = None,
        last_frame: str | None = None,
        image_url: str | None = None,
    ) -> list[dict]:
        """Build the ``content`` array for the Ark content_generation API.

        Priority: explicit ``content_items`` > convenience fields > legacy ``image_url``.
        """
        if content_items:
            items: list[dict] = []
            for ci in content_items:
                item: dict = {"type": ci.type}
                if ci.type == "text" and ci.text:
                    item["text"] = ci.text
                elif ci.type == "image_url" and ci.image_url:
                    item["image_url"] = ci.image_url
                    if ci.role:
                        item["role"] = ci.role
                elif ci.type == "video_url" and ci.video_url:
                    item["video_url"] = ci.video_url
                    if ci.role:
                        item["role"] = ci.role
                elif ci.type == "audio_url" and ci.audio_url:
                    item["audio_url"] = ci.audio_url
                    if ci.role:
                        item["role"] = ci.role
                items.append(item)
            return items

        # Build from convenience fields
        result: list[dict] = []
        if prompt:
            result.append({"type": "text", "text": prompt})

        if first_frame:
            result.append({
                "type": "image_url",
                "image_url": {"url": first_frame},
                "role": "first_frame",
            })
        if last_frame:
            result.append({
                "type": "image_url",
                "image_url": {"url": last_frame},
                "role": "last_frame",
            })

        for url in (reference_images or []):
            result.append({
                "type": "image_url",
                "image_url": {"url": url},
                "role": "reference_image",
            })

        # Legacy single image_url
        if image_url and not reference_images and not first_frame:
            result.append({
                "type": "image_url",
                "image_url": {"url": image_url},
                "role": "first_frame",
            })

        for url in (reference_videos or []):
            result.append({
                "type": "video_url",
                "video_url": {"url": url},
                "role": "reference_video",
            })

        for url in (reference_audios or []):
            result.append({
                "type": "audio_url",
                "audio_url": {"url": url},
                "role": "reference_audio",
            })

        return result

    # ── video generation ──

    async def generate_video(self, prompt: str, model: str, **kwargs: object) -> dict:
        if not self._has_key():
            logger.warning("Seedance API key not configured, returning mock response")
            return {
                "task_id": "seedance-mock-task",
                "status": "processing",
                "estimated_seconds": 60,
            }

        duration = int(kwargs.get("duration", 5))
        duration = min(max(duration, 4), 15)
        ratio = str(kwargs.get("ratio") or kwargs.get("aspect_ratio") or "16:9")
        quality = str(kwargs.get("quality", "standard"))
        generate_audio = bool(kwargs.get("generate_audio", False))
        watermark = bool(kwargs.get("watermark", True))
        tools = kwargs.get("tools")

        content = self._build_content(
            prompt,
            content_items=kwargs.get("content_items"),
            reference_images=kwargs.get("reference_images"),
            reference_videos=kwargs.get("reference_videos"),
            reference_audios=kwargs.get("reference_audios"),
            first_frame=kwargs.get("first_frame"),
            last_frame=kwargs.get("last_frame"),
            image_url=kwargs.get("image_url"),
        )

        chosen_model = self._pick_model(model, quality)
        payload: dict = {
            "model": chosen_model,
            "content": content,
            "duration": duration,
            "ratio": ratio,
            "generate_audio": generate_audio,
            "watermark": watermark,
        }
        if tools:
            payload["tools"] = tools

        return await self._create_task(payload, chosen_model)

    async def _create_task(self, payload: dict, model_used: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{_ARK_API_BASE}/content_generation/tasks",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            return {
                "task_id": data.get("id", ""),
                "status": data.get("status", "processing"),
                "video_url": "",
                "estimated_seconds": 120,
                "model": model_used,
            }
        except httpx.HTTPStatusError as exc:
            logger.error("Seedance API error %s: %s", exc.response.status_code, exc.response.text[:500])
            raise RuntimeError(f"Seedance video generation failed: {exc.response.status_code}") from exc
        except Exception as exc:
            logger.error("Seedance request failed: %s", exc)
            raise RuntimeError(f"Seedance video generation failed: {exc}") from exc

    # ── status polling ──

    async def get_video_status(self, task_id: str) -> dict:
        if not self._has_key() or task_id.startswith("seedance-mock"):
            return {
                "task_id": task_id,
                "status": "succeeded",
                "video_url": "https://placeholder.co/video.mp4",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{_ARK_API_BASE}/content_generation/tasks/{task_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            status = data.get("status", "processing")
            video_url = ""
            if status == "succeeded":
                content_block = data.get("content", {})
                video_url = content_block.get("video_url", "") if isinstance(content_block, dict) else ""

            error_info = None
            if status == "failed" and data.get("error"):
                err = data["error"]
                error_info = err.get("message", str(err)) if isinstance(err, dict) else str(err)

            return {
                "task_id": task_id,
                "status": status,
                "video_url": video_url,
                "error": error_info,
            }
        except Exception as exc:
            logger.error("Seedance status check failed: %s", exc)
            return {"task_id": task_id, "status": "error", "error": str(exc)}
