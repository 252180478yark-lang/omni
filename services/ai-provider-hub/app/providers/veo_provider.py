"""Veo 3.1 video generation provider — Gemini Developer API or Vertex AI.

Two auth modes (auto-detected by env vars):

  A) Vertex AI mode
     - Set: VERTEX_PROJECT + VERTEX_LOCATION + GOOGLE_APPLICATION_CREDENTIALS

  B) Gemini Developer API mode（默认）
     - Set: GEMINI_API_KEY

  两 mode 都支持: t2v / i2v / last_frame 插帧 / reference_images

  官方文档 (Gemini Dev API): https://ai.google.dev/gemini-api/docs/video#veo-3.1-preview

  关键硬规则（文档 + 实测验证）：
    1) last_frame 插帧 → duration 必须 8s（"Duration must be 8 seconds when using this feature"）
       — 传 4s/6s + last_frame 会返 INVALID_ARGUMENT "use case not supported"
       — 处理：发现 last_frame 时自动拉 duration=8 + warning
    2) personGeneration 模式约束:
       - t2v 纯文本: "allow_all"（i2v 模式不能用 allow_all）
       - i2v / 参考图: "allow_adult" 或 "allow_all" 均 OK

Model: veo-3.1-generate-preview (preview model name same in both endpoints)

Duration: 4, 6, or 8 seconds (Veo ignores other values; we clamp to nearest);
          last_frame 强制 8s

Aspect: "9:16" or "16:9"

Flow:
  1. generate_video() submits + polls synchronously in asyncio.to_thread (~60-120s)
  2. Returns {task_id, status:"completed", video_url:"data:video/mp4;base64,...",
              last_frame_used: bool, duration_forced_8s: bool,
              auth_mode: "vertex"|"gemini_dev"}
  3. Hub stores video_url in task_data; get_video_status() returns immediately
  4. KE's wait_for_video sees "completed" in first poll → done
  5. KE's asset_storage.persist_or_fallback decodes data: URI → saves .mp4 to disk
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from collections.abc import AsyncIterator

from app.config import settings
from app.providers.base import BaseProvider, ProviderCapability, is_real_api_key
from app.schemas.ai import ChatResponse, Message, TokenUsage

logger = logging.getLogger(__name__)


def _vertex_config() -> tuple[str, str] | None:
    """Return (project, location) if Vertex AI is fully configured, else None.

    Required: VERTEX_PROJECT + VERTEX_LOCATION + GOOGLE_APPLICATION_CREDENTIALS
    (the SA JSON file path must actually exist).
    """
    project = (os.environ.get("VERTEX_PROJECT") or "").strip()
    location = (os.environ.get("VERTEX_LOCATION") or "").strip()
    creds = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not (project and location and creds):
        return None
    if not os.path.isfile(creds):
        logger.warning("veo: VERTEX_* set but GOOGLE_APPLICATION_CREDENTIALS=%s missing", creds)
        return None
    return (project, location)

# Veo only accepts these exact duration values
_VEO_DURATIONS = (4, 6, 8)


def _clamp_duration(d: int) -> int:
    for v in _VEO_DURATIONS:
        if d <= v:
            return v
    return 8


def _decode_image(data_uri: str, label: str = "image") -> "object | None":
    """base64 data: URI → google.genai.types.Image.

    Returns None if parsing fails or data_uri is empty.
    """
    if not data_uri or not data_uri.startswith("data:"):
        return None
    try:
        from google.genai import types as genai_types

        header, b64_data = data_uri.split(",", 1)
        mime = header.split(":")[1].split(";")[0]
        raw = base64.b64decode(b64_data)
        return genai_types.Image(image_bytes=raw, mime_type=mime)
    except Exception as exc:
        logger.warning("veo: cannot decode %s data URI: %s", label, exc)
        return None


# Keep old name as alias for callers
_decode_first_frame = _decode_image


def _decode_reference_images(ref_list: list[dict]) -> "list | None":
    """Convert hub reference_images list → Veo VideoGenerationReferenceImage list.

    ref_list entries: {"url": "data:image/...", "type": "face"|"product", ...}
    All are mapped to ASSET reference_type (face + product consistency).
    Returns None if list is empty or all entries fail to decode.
    """
    if not ref_list:
        return None
    try:
        from google.genai import types as genai_types

        results = []
        for entry in ref_list:
            url = entry.get("url") or entry.get("data") or ""
            img = _decode_image(url, label=f"ref[{entry.get('type', '?')}]")
            if img is not None:
                results.append(
                    genai_types.VideoGenerationReferenceImage(
                        image=img,
                        reference_type=genai_types.VideoGenerationReferenceType.ASSET,
                    )
                )
        return results or None
    except Exception as exc:
        logger.warning("veo: cannot build reference_images: %s", exc)
        return None


class VeoProvider(BaseProvider):
    """Google Veo 3.1 video generation via Gemini API."""

    name = "veo"
    default_chat_model = ""
    default_embedding_model = ""
    capabilities = {ProviderCapability.VIDEO_GENERATION}

    # ── helpers ────────────────────────────────────────────────────────────────

    def _get_api_key(self) -> str:
        return (settings.gemini_api_key or "").strip()

    def _has_key(self) -> bool:
        return is_real_api_key(self._get_api_key())

    def _has_auth(self) -> bool:
        """Either Vertex mode (best) or Gemini API key — at least one."""
        return _vertex_config() is not None or self._has_key()

    def _pick_model(self, model: str | None) -> str:
        if model and model.startswith("veo-"):
            return model
        return (settings.veo_model or "veo-3.1-generate-preview").strip()

    # ── unsupported base methods ───────────────────────────────────────────────

    async def chat(self, messages: list[Message], model: str, **kwargs: object) -> ChatResponse:
        raise NotImplementedError("Veo does not support chat")

    async def chat_stream(self, messages: list[Message], model: str, **kwargs: object) -> AsyncIterator[str]:
        raise NotImplementedError("Veo does not support chat streaming")
        yield  # noqa: unreachable

    async def embedding(self, texts: list[str], model: str, **kwargs: object) -> tuple[list[list[float]], TokenUsage]:
        raise NotImplementedError("Veo does not support embeddings")

    # ── video generation ───────────────────────────────────────────────────────

    async def generate_video(self, prompt: str, model: str, **kwargs: object) -> dict:
        vertex = _vertex_config()
        if vertex is None and not self._has_key():
            raise RuntimeError(
                "Veo requires either Vertex AI (VERTEX_PROJECT + VERTEX_LOCATION + "
                "GOOGLE_APPLICATION_CREDENTIALS) or GEMINI_API_KEY in hub .env"
            )

        duration = _clamp_duration(int(kwargs.get("duration") or 8))
        aspect_ratio = str(kwargs.get("aspect_ratio") or kwargs.get("ratio") or "9:16")
        first_frame_b64 = kwargs.get("first_frame") or None
        last_frame_b64 = kwargs.get("last_frame") or None
        reference_images_raw: list[dict] = list(kwargs.get("reference_images") or [])
        negative_prompt = str(kwargs.get("negative_prompt") or "").strip() or None
        generate_audio = bool(kwargs.get("generate_audio"))
        resolution = str(kwargs.get("resolution") or "").strip() or None
        chosen_model = self._pick_model(model)

        i2v = bool(first_frame_b64)
        # i2v 时 reference_images 跟 first_frame 文档未明确互斥但实测可能拒；先保留只在 t2v 用 refs
        use_refs = not i2v and bool(reference_images_raw)
        auth_mode = "vertex" if vertex else "gemini_dev"

        # last_frame 处理：
        #   1) 必须跟 first_frame 搭配（API 硬规则）
        #   2) 文档硬规则: "Duration must be 8 seconds when using this feature"
        #      实测：last_frame + duration=4/6 → INVALID_ARGUMENT "use case not supported"
        #      处理：自动拉 duration=8 + warning，不 drop last_frame（保留双帧串场效果）
        if last_frame_b64 and not i2v:
            logger.warning("veo: dropping last_frame because first_frame absent")
            last_frame_b64 = None

        duration_forced_8s = False
        if last_frame_b64 and duration != 8:
            logger.warning(
                "veo: last_frame requires duration=8s (Gemini API hard rule); "
                "raising duration from %ds to 8s",
                duration,
            )
            duration = 8
            duration_forced_8s = True

        # personGeneration（实测规则）:
        #   - t2v: "allow_all" — 传 "allow_adult" 会返 "use case not supported"
        #   - i2v / 参考图: "allow_adult" 或 "allow_all" 都 OK
        person_generation = "allow_adult" if (i2v or use_refs) else "allow_all"

        logger.info(
            "veo: submit auth=%s model=%s duration=%ds aspect=%s i2v=%s last_frame=%s refs=%d person_gen=%s",
            auth_mode, chosen_model, duration, aspect_ratio, i2v,
            bool(last_frame_b64), len(reference_images_raw), person_generation,
        )

        video_bytes = await asyncio.to_thread(
            self._generate_blocking,
            prompt=prompt,
            model=chosen_model,
            duration=duration,
            aspect_ratio=aspect_ratio,
            first_frame_b64=first_frame_b64 or "",
            last_frame_b64=last_frame_b64 or "" if i2v else "",
            reference_images_raw=reference_images_raw if use_refs else [],
            negative_prompt=negative_prompt,
            generate_audio=generate_audio,
            resolution=resolution,
            vertex=vertex,
            person_generation=person_generation,
        )

        b64 = base64.b64encode(video_bytes).decode()
        data_uri = f"data:video/mp4;base64,{b64}"
        task_id = f"veo-{int(time.time())}"

        logger.info("veo: done task_id=%s video_size=%.1f KB", task_id, len(video_bytes) / 1024)

        return {
            "task_id": task_id,
            "status": "completed",
            "video_url": data_uri,
            "model": chosen_model,
            "estimated_seconds": 0,
            "auth_mode": auth_mode,
            "last_frame_used": bool(last_frame_b64) and i2v,
            "duration_forced_8s": duration_forced_8s,
            "person_generation": person_generation,
        }

    def _generate_blocking(
        self,
        *,
        prompt: str,
        model: str,
        duration: int,
        aspect_ratio: str,
        first_frame_b64: str,
        last_frame_b64: str = "",
        reference_images_raw: list = None,
        negative_prompt: str | None = None,
        generate_audio: bool = False,
        resolution: str | None = None,
        vertex: tuple[str, str] | None = None,
        person_generation: str = "allow_adult",
    ) -> bytes:
        """Synchronous Veo generation + poll. Run via asyncio.to_thread.

        vertex=(project, location) → Vertex AI 走 aiplatform.googleapis.com
        vertex=None → Gemini Dev API 走 generativelanguage.googleapis.com
        两 mode 都支持 first_frame / last_frame / reference_images（官方文档证实）
        """
        from google import genai
        from google.genai import types as genai_types

        if vertex is not None:
            project, location = vertex
            client = genai.Client(vertexai=True, project=project, location=location)
        else:
            client = genai.Client(api_key=self._get_api_key())

        first_frame = _decode_image(first_frame_b64, "first_frame") if first_frame_b64 else None
        last_frame = _decode_image(last_frame_b64, "last_frame") if last_frame_b64 else None
        ref_images = _decode_reference_images(reference_images_raw or [])

        config_kwargs: dict = {
            "aspect_ratio": aspect_ratio,
            "duration_seconds": duration,
            "number_of_videos": 1,
            "person_generation": person_generation,
        }
        if negative_prompt:
            config_kwargs["negative_prompt"] = negative_prompt
        if generate_audio:
            config_kwargs["generate_audio"] = True
        # resolution: 1080p/4k 仅在 8s 时可用；其他场景让 Veo 自选默认
        if resolution in ("720p", "1080p", "4k"):
            if resolution in ("1080p", "4k") and duration != 8:
                logger.warning(
                    "veo: resolution=%s requires duration=8s, currently %ds — dropping resolution",
                    resolution, duration,
                )
            else:
                config_kwargs["resolution"] = resolution
        # last_frame only valid in i2v mode (when first_frame is set)
        if last_frame is not None and first_frame is not None:
            config_kwargs["last_frame"] = last_frame
        # reference_images only valid when NOT using first_frame (t2v ref mode)
        if ref_images and first_frame is None:
            config_kwargs["reference_images"] = ref_images

        config = genai_types.GenerateVideosConfig(**config_kwargs)

        generate_kwargs: dict = {"model": model, "config": config}
        if first_frame is not None:
            generate_kwargs["image"] = first_frame
        if prompt:
            generate_kwargs["prompt"] = prompt

        # Submit
        try:
            operation = client.models.generate_videos(**generate_kwargs)
        except Exception as exc:
            logger.error(
                "veo: generate_videos call failed (model=%s i2v=%s last_frame=%s refs=%d person_gen=%s): %s",
                model, first_frame is not None, last_frame is not None,
                len(ref_images or []), person_generation, exc,
            )
            raise
        logger.info("veo: operation submitted name=%s", operation.name)

        # Poll until done (Veo typically 60-120s)
        while not operation.done:
            time.sleep(15)
            operation = client.operations.get(operation)
            logger.debug("veo: polling operation.done=%s", operation.done)

        if operation.error:
            code = getattr(operation.error, "code", -1)
            msg = getattr(operation.error, "message", str(operation.error))
            raise RuntimeError(f"Veo generation failed (code={code}): {msg}")

        generated = operation.response.generated_videos
        if not generated:
            raise RuntimeError("Veo returned no generated videos")

        # Download video bytes
        video_file = generated[0].video
        raw = client.files.download(file=video_file)

        # Handle different SDK return types (bytes / file-like / iterable)
        if isinstance(raw, bytes):
            return raw
        if hasattr(raw, "content"):
            return raw.content
        if hasattr(raw, "read"):
            return raw.read()
        chunks = list(raw)  # try iterable
        if chunks and isinstance(chunks[0], bytes):
            return b"".join(chunks)
        raise RuntimeError(f"Unexpected video download type: {type(raw)}")

    async def get_video_status(self, task_id: str) -> dict:
        # generate_video already completed synchronously; status is always "completed"
        return {"status": "completed"}
