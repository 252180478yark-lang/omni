"""Kling 3.0 video generation provider (Kuaishou)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability, is_real_api_key
from app.schemas.ai import ChatResponse, Message, TokenUsage

logger = logging.getLogger(__name__)

_API_BASE = "https://api.klingai.com"


class KlingProvider(BaseProvider):
    name = "kling"
    default_chat_model = ""
    default_embedding_model = ""
    capabilities = {ProviderCapability.VIDEO_GENERATION}

    def _has_key(self) -> bool:
        return is_real_api_key(settings.kling_api_key)

    def _headers(self) -> dict[str, str]:
        key = (settings.kling_api_key or "").strip()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }

    # ── connection test ──

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        key = (api_key or settings.kling_api_key or "").strip()
        if not is_real_api_key(key):
            return False, "未提供 Kling API Key", []
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_API_BASE}/v1/videos/generations",
                    headers=headers,
                    params={"pageNum": 1, "pageSize": 1},
                )
                if resp.status_code == 401:
                    return False, "API Key 无效 (401 Unauthorized)", []
                if resp.status_code == 403:
                    return False, "API Key 权限不足 (403 Forbidden)", []
                resp.raise_for_status()
            return True, "Kling 连接成功", []
        except httpx.HTTPStatusError as exc:
            return False, f"连接失败 (HTTP {exc.response.status_code}): {exc.response.text[:200]}", []
        except Exception as exc:
            return False, f"连接失败: {exc}", []

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        raise NotImplementedError("Kling does not support chat")

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        raise NotImplementedError("Kling does not support chat streaming")
        yield  # noqa: unreachable

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        raise NotImplementedError("Kling does not support embeddings")

    async def generate_video(self, prompt: str, model: str, **kwargs: object) -> dict:
        if not self._has_key():
            logger.warning("Kling API key not configured, returning mock response")
            return {
                "task_id": "kling-mock-task",
                "status": "processing",
                "estimated_seconds": 120,
            }

        duration = int(kwargs.get("duration", 5))
        aspect_ratio = str(kwargs.get("aspect_ratio", "16:9"))
        image_url = kwargs.get("image_url")

        payload: dict = {
            "model": model or "kling-v3",
            "prompt": prompt,
            "duration": min(max(duration, 3), 15),
            "aspect_ratio": aspect_ratio,
            "mode": "std",
        }

        if image_url:
            payload["first_frame"] = {"type": "url", "url": image_url}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{_API_BASE}/v1/videos/generations",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            task_data = data.get("data", data)
            return {
                "task_id": task_data.get("task_id", ""),
                "status": task_data.get("status", "processing"),
                "video_url": task_data.get("video_url", ""),
                "estimated_seconds": task_data.get("estimated_seconds", 120),
            }
        except httpx.HTTPStatusError as exc:
            logger.error("Kling API error %s: %s", exc.response.status_code, exc.response.text[:300])
            raise RuntimeError(f"Kling video generation failed: {exc.response.status_code}") from exc
        except Exception as exc:
            logger.error("Kling request failed: %s", exc)
            raise RuntimeError(f"Kling video generation failed: {exc}") from exc

    async def get_video_status(self, task_id: str) -> dict:
        if not self._has_key() or task_id.startswith("kling-mock"):
            return {"task_id": task_id, "status": "completed", "video_url": "https://placeholder.co/video.mp4"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{_API_BASE}/v1/videos/generations/{task_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            task_data = data.get("data", data)
            video_url = ""
            videos = task_data.get("videos", [])
            if videos and isinstance(videos, list):
                video_url = videos[0].get("url", "")

            return {
                "task_id": task_id,
                "status": task_data.get("status", "processing"),
                "video_url": video_url or task_data.get("video_url", ""),
            }
        except Exception as exc:
            logger.error("Kling status check failed: %s", exc)
            return {"task_id": task_id, "status": "error", "error": str(exc)}
