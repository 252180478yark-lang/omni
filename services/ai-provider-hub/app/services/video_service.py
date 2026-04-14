from __future__ import annotations

import logging
from uuid import uuid4

from app.providers.base import ProviderCapability
from app.providers.registry import ProviderRegistry
from app.schemas.ai import VideoGenerateRequest, VideoGenerateResponse, VideoStatusResponse
from app.services.redis_client import get_video_task, set_video_task
from app.utils.fallback import FallbackChain, call_with_retry

logger = logging.getLogger(__name__)

_video_tasks: dict[str, dict] = {}


class VideoService:
    def __init__(self, registry: ProviderRegistry, fallback: FallbackChain) -> None:
        self.registry = registry
        self.fallback = fallback

    async def generate(self, payload: VideoGenerateRequest) -> VideoGenerateResponse:
        providers = self.fallback.get_chain_for_capability(
            payload.provider, self.registry, ProviderCapability.VIDEO_GENERATION,
        )
        if not providers:
            raise RuntimeError(
                "No video generation provider configured. "
                "Set ARK_API_KEY for Seedance 2.0 or KLING_API_KEY for Kling."
            )

        kw: dict = {
            "duration": payload.duration,
            "ratio": payload.effective_ratio(),
            "aspect_ratio": payload.effective_ratio(),
            "image_url": payload.image_url,
            "generate_audio": payload.generate_audio,
            "watermark": payload.watermark,
            "quality": payload.quality,
            "mode": payload.mode,
            "reference_images": payload.reference_images,
            "reference_videos": payload.reference_videos,
            "reference_audios": payload.reference_audios,
            "first_frame": payload.first_frame,
            "last_frame": payload.last_frame,
            "tools": payload.tools,
            "content_items": payload.content,
        }

        last_error: Exception | None = None
        for name in providers:
            provider = self.registry.get(name)
            model = payload.model or ""
            try:
                result = await call_with_retry(
                    provider.generate_video,
                    prompt=payload.prompt, model=model, **kw,
                )
                task_id = result.get("task_id", str(uuid4()))
                task_data = {
                    "status": result.get("status", "processing"),
                    "video_url": result.get("video_url", ""),
                    "duration": str(payload.duration),
                    "provider": name,
                    "model": result.get("model", model),
                }
                await set_video_task(task_id, task_data)
                _video_tasks[task_id] = task_data

                return VideoGenerateResponse(
                    task_id=task_id,
                    status=result.get("status", "processing"),
                    estimated_seconds=result.get("estimated_seconds", 120),
                    provider=name,
                    model=task_data["model"],
                )
            except NotImplementedError:
                continue
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"No video generation provider available: {last_error}")

    async def get_status(self, task_id: str) -> VideoStatusResponse:
        task = await get_video_task(task_id)
        if task is None:
            task = _video_tasks.get(task_id)
        if not task:
            raise ValueError(f"Video task not found: {task_id}")

        provider_name = task.get("provider", "")
        current_status = task.get("status", "unknown")

        # Poll upstream if still processing
        if current_status in ("processing", "running", "queued", "pending"):
            upstream = await self._poll_upstream(provider_name, task_id)
            if upstream:
                task.update(upstream)
                await set_video_task(task_id, task)
                _video_tasks[task_id] = task

        return VideoStatusResponse(
            task_id=task_id,
            status=task.get("status", "unknown"),
            video_url=task.get("video_url") or None,
            duration=int(task["duration"]) if task.get("duration") else None,
            provider=provider_name or None,
            error=task.get("error"),
        )

    async def _poll_upstream(self, provider_name: str, task_id: str) -> dict | None:
        try:
            provider = self.registry.get(provider_name)
            result = await provider.get_video_status(task_id)
            update: dict = {}
            if result.get("status"):
                update["status"] = result["status"]
            if result.get("video_url"):
                update["video_url"] = result["video_url"]
            if result.get("error"):
                update["error"] = result["error"]
            return update if update else None
        except (KeyError, NotImplementedError):
            return None
        except Exception as exc:
            logger.warning("Upstream status poll failed for %s/%s: %s", provider_name, task_id, exc)
            return None
