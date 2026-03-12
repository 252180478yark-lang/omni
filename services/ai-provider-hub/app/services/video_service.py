from __future__ import annotations

from uuid import uuid4

from app.providers.base import ProviderCapability
from app.providers.registry import ProviderRegistry
from app.schemas.ai import VideoGenerateRequest, VideoGenerateResponse, VideoStatusResponse
from app.services.redis_client import get_video_task, set_video_task
from app.utils.fallback import FallbackChain, call_with_retry

# In-memory fallback when Redis is unavailable
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
                "Video generation requires an external provider (e.g., Runway, Kling). "
                "Please configure a video-capable provider and restart."
            )

        last_error: Exception | None = None
        for name in providers:
            provider = self.registry.get(name)
            model = payload.model or "runway-gen3"
            try:
                result = await call_with_retry(
                    provider.generate_video,
                    prompt=payload.prompt, model=model,
                    duration=payload.duration, aspect_ratio=payload.aspect_ratio,
                    image_url=payload.image_url,
                )
                task_id = result.get("task_id", str(uuid4()))
                task_data = {
                    "status": result.get("status", "processing"),
                    "video_url": result.get("video_url", ""),
                    "duration": str(payload.duration),
                    "provider": name,
                    "model": model,
                }
                # Persist to Redis (+ in-memory fallback)
                await set_video_task(task_id, task_data)
                _video_tasks[task_id] = task_data

                return VideoGenerateResponse(
                    task_id=task_id,
                    status=result.get("status", "processing"),
                    estimated_seconds=result.get("estimated_seconds", 120),
                )
            except NotImplementedError:
                continue
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"No video generation provider available: {last_error}")

    async def get_status(self, task_id: str) -> VideoStatusResponse:
        # Try Redis first, then in-memory fallback
        task = await get_video_task(task_id)
        if task is None:
            task = _video_tasks.get(task_id)
        if not task:
            raise ValueError(f"Video task not found: {task_id}")
        return VideoStatusResponse(
            task_id=task_id,
            status=task.get("status", "unknown"),
            video_url=task.get("video_url") or None,
            duration=int(task["duration"]) if task.get("duration") else None,
        )
