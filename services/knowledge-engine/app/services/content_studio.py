"""Content Studio pipeline orchestration service."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

import httpx

from app.config import settings
from app.database import get_pool
from app.services.prompt_templates import (
    build_copy_prompt,
    build_character_face_prompt,
    build_image_prompt,
    build_scene_to_image_prompt,
    build_scene_to_video_prompt,
    build_script_analysis_prompt,
    build_script_prompt,
    build_video_reference_images,
)

logger = logging.getLogger(__name__)

DATA_ROOT = Path("/app/data/content-studio")
HUB_BASE = settings.ai_provider_hub_url.rstrip("/")
HUB_CHAT = f"{HUB_BASE}/api/v1/ai/chat"
HUB_IMAGE = f"{HUB_BASE}/api/v1/ai/images/generate"
HUB_VIDEO = f"{HUB_BASE}/api/v1/ai/videos/generate"
HUB_VIDEO_STATUS = f"{HUB_BASE}/api/v1/ai/videos/status"

_HTTP_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)


# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────

async def create_pipeline(title: str, source_text: str, config: dict) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO content_studio.pipelines (title, source_text, config)
           VALUES ($1, $2, $3::jsonb) RETURNING *""",
        title, source_text, json.dumps(config, ensure_ascii=False),
    )
    return dict(row)


async def get_pipeline(pipeline_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM content_studio.pipelines WHERE id = $1", uuid.UUID(pipeline_id),
    )
    return dict(row) if row else None


async def list_pipelines(limit: int = 50, offset: int = 0) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT id, title, status, current_step, config, cost_estimate, actual_cost,
                  created_at, updated_at
           FROM content_studio.pipelines ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
        limit, offset,
    )
    return [dict(r) for r in rows]


async def update_pipeline(pipeline_id: str, **fields: object) -> dict | None:
    pool = get_pool()
    sets = []
    vals = []
    idx = 1
    for key, val in fields.items():
        if key in ("id", "created_at"):
            continue
        if key in ("script_result", "storyboard_results", "video_results", "config",
                    "cost_estimate", "actual_cost", "product_images", "character_profiles"):
            sets.append(f"{key} = ${idx}::jsonb")
            vals.append(json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val)
        else:
            sets.append(f"{key} = ${idx}")
            vals.append(val)
        idx += 1
    sets.append(f"updated_at = NOW()")
    vals.append(uuid.UUID(pipeline_id))
    query = f"UPDATE content_studio.pipelines SET {', '.join(sets)} WHERE id = ${idx} RETURNING *"
    row = await pool.fetchrow(query, *vals)
    return dict(row) if row else None


async def delete_pipeline(pipeline_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute(
        "DELETE FROM content_studio.pipelines WHERE id = $1", uuid.UUID(pipeline_id),
    )
    task_dir = DATA_ROOT / pipeline_id
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)
    return result == "DELETE 1"


# ──────────────────────────────────────────────
# Style presets
# ──────────────────────────────────────────────

async def list_presets() -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM content_studio.style_presets ORDER BY is_builtin DESC, created_at")
    return [dict(r) for r in rows]


async def create_preset(name: str, description: str, config: dict) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO content_studio.style_presets (name, description, config)
           VALUES ($1, $2, $3::jsonb) RETURNING *""",
        name, description, json.dumps(config, ensure_ascii=False),
    )
    return dict(row)


# ──────────────────────────────────────────────
# AI Hub calls
# ──────────────────────────────────────────────

async def _call_chat(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"messages": messages, "temperature": 0.7}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(HUB_CHAT, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data.get("content", "")


async def _call_image_with_prompt(prompt: str, model: str = "gpt-image-1.5") -> dict:
    """Call image generation and return both URL and the prompt used."""
    url = await _call_image(prompt, model)
    return {"image_url": url, "prompt_used": prompt}


async def _call_image(prompt: str, model: str = "gpt-image-1.5") -> str:
    payload = {"prompt": prompt, "model": model, "size": "1536x1024", "quality": "high", "n": 1}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(HUB_IMAGE, json=payload)
        resp.raise_for_status()
        data = resp.json()
    images = data.get("images", [])
    return images[0].get("url", "") if images else ""


async def _call_video(
    prompt: str,
    image_url: str | None = None,
    duration: int = 5,
    *,
    reference_images: list[str] | None = None,
    reference_videos: list[str] | None = None,
    reference_audios: list[str] | None = None,
    first_frame: str | None = None,
    last_frame: str | None = None,
    generate_audio: bool = False,
    ratio: str = "16:9",
    mode: str = "generate",
    quality: str = "standard",
) -> dict:
    payload: dict = {
        "prompt": prompt,
        "duration": duration,
        "ratio": ratio,
        "aspect_ratio": ratio,
        "generate_audio": generate_audio,
        "mode": mode,
        "quality": quality,
    }
    if image_url and not first_frame:
        payload["image_url"] = image_url
    if first_frame:
        payload["first_frame"] = first_frame
    if last_frame:
        payload["last_frame"] = last_frame
    if reference_images:
        payload["reference_images"] = reference_images
    if reference_videos:
        payload["reference_videos"] = reference_videos
    if reference_audios:
        payload["reference_audios"] = reference_audios
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(HUB_VIDEO, json=payload)
        resp.raise_for_status()
        return resp.json()


async def _poll_video(task_id: str, max_wait: int = 600) -> dict:
    elapsed = 0
    interval = 5
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        while elapsed < max_wait:
            resp = await client.get(f"{HUB_VIDEO_STATUS}/{task_id}")
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            if status in ("completed", "succeeded"):
                return data
            if status in ("failed", "error"):
                raise RuntimeError(f"Video generation failed: {data}")
            await asyncio.sleep(interval)
            elapsed += interval
            interval = min(interval + 2, 15)
    raise TimeoutError(f"Video generation timed out after {max_wait}s")


# ──────────────────────────────────────────────
# Preview prompts — see before you generate
# ──────────────────────────────────────────────

async def preview_storyboard_prompts(pipeline_id: str) -> list[dict]:
    """Preview the image-gen prompts that WOULD be used, without actually generating images."""
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    script = pipe["script_result"]
    if isinstance(script, str):
        script = json.loads(script)
    scenes = script.get("scenes", [])
    if not scenes:
        raise ValueError("Script has no scenes")

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    image_style = config.get("image_style", "lifestyle_photo")

    product_images = pipe.get("product_images")
    if isinstance(product_images, str):
        product_images = json.loads(product_images)
    character_profiles = pipe.get("character_profiles")
    if isinstance(character_profiles, str):
        character_profiles = json.loads(character_profiles)

    use_enhanced = bool(character_profiles or product_images)
    previews = []

    for scene in scenes:
        if use_enhanced:
            llm_prompt = build_scene_to_image_prompt(
                scene, image_style=image_style,
                product_images=product_images, character_profiles=character_profiles,
            )
            optimized = await _call_chat(llm_prompt)
            optimized = optimized.strip().strip('"').strip("'")
        else:
            optimized = build_image_prompt(scene.get("visual_description", ""), image_style)

        previews.append({
            "scene_id": scene["scene_id"],
            "original_description": scene.get("visual_description", ""),
            "characters_in_scene": scene.get("characters", []),
            "has_product": scene.get("has_product", False),
            "prompt_will_use": optimized,
        })

    return previews


async def preview_video_prompts(pipeline_id: str) -> list[dict]:
    """Preview the video-gen prompts and reference images that WOULD be used."""
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    script = pipe["script_result"]
    if isinstance(script, str):
        script = json.loads(script)
    storyboard = pipe.get("storyboard_results")
    if isinstance(storyboard, str):
        storyboard = json.loads(storyboard)

    scenes = script.get("scenes", [])
    sb_map = {r["scene_id"]: r for r in (storyboard or [])}

    product_images = pipe.get("product_images")
    if isinstance(product_images, str):
        product_images = json.loads(product_images)
    character_profiles = pipe.get("character_profiles")
    if isinstance(character_profiles, str):
        character_profiles = json.loads(character_profiles)

    use_enhanced = bool(character_profiles or product_images)
    previews = []

    for scene in scenes:
        sb = sb_map.get(scene["scene_id"], {})
        storyboard_url = sb.get("image_url", "")

        if use_enhanced:
            llm_prompt = build_scene_to_video_prompt(
                scene, product_images=product_images, character_profiles=character_profiles,
            )
            optimized = await _call_chat(llm_prompt)
            optimized = optimized.strip().strip('"').strip("'")
            ref_images = build_video_reference_images(
                scene, character_profiles=character_profiles, product_images=product_images,
            )
        else:
            prompt = scene.get("visual_description", "")
            cam = scene.get("camera_movement", "")
            if cam:
                prompt += f"，运镜：{cam}"
            optimized = prompt
            ref_images = []

        previews.append({
            "scene_id": scene["scene_id"],
            "original_description": scene.get("visual_description", ""),
            "prompt_will_use": optimized,
            "first_frame": storyboard_url,
            "reference_images": ref_images,
            "characters_in_scene": scene.get("characters", []),
            "has_product": scene.get("has_product", False),
        })

    return previews


# ──────────────────────────────────────────────
# Product image & script import helpers
# ──────────────────────────────────────────────

async def set_product_images(pipeline_id: str, image_urls: list[str]) -> dict:
    """Store product white-background image URLs for consistency enforcement."""
    result = await update_pipeline(pipeline_id, product_images=image_urls)
    if not result:
        raise ValueError("Pipeline not found")
    return result


async def import_script(pipeline_id: str, script: dict) -> dict:
    """Import a script generated externally (e.g. from knowledge Q&A module)."""
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    return await update_pipeline(
        pipeline_id, script_result=script,
        current_step="analyze", status="paused",
    )


# ──────────────────────────────────────────────
# Script analysis — extract characters + product map
# ──────────────────────────────────────────────

async def analyze_script(pipeline_id: str) -> dict:
    """Use LLM to analyze the script and extract character/product information."""
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    script = pipe["script_result"]
    if isinstance(script, str):
        script = json.loads(script)
    if not script or not script.get("scenes"):
        raise ValueError("Script not available or has no scenes")

    await update_pipeline(pipeline_id, status="running", current_step="analyze")
    try:
        prompt = build_script_analysis_prompt(script)
        raw = await _call_chat(prompt)
        analysis = _parse_script_json(raw)

        characters = analysis.get("characters", [])
        product_scenes = analysis.get("product_scenes", [])

        # Merge product scene info back into script
        for scene in script.get("scenes", []):
            sid = scene["scene_id"]
            scene["has_product"] = sid in product_scenes
            scene_chars = []
            for ch in characters:
                if sid in ch.get("scene_ids", []):
                    scene_chars.append(ch["name"])
            scene["characters"] = scene_chars

        # Save character profiles (without face_url yet) and updated script
        profiles = [
            {
                "id": ch["id"],
                "name": ch["name"],
                "gender": ch.get("gender", ""),
                "age_range": ch.get("age_range", ""),
                "appearance": ch.get("appearance", ""),
                "scene_ids": ch.get("scene_ids", []),
                "face_url": "",
            }
            for ch in characters
        ]

        return await update_pipeline(
            pipeline_id,
            script_result=script,
            character_profiles=profiles,
            current_step="characters",
            status="paused",
        )
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


# ──────────────────────────────────────────────
# Character face generation — pre-generate consistent faces
# ──────────────────────────────────────────────

async def generate_character_faces(pipeline_id: str) -> dict:
    """Generate portrait reference images for each character to ensure cross-scene consistency."""
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")

    profiles = pipe.get("character_profiles")
    if isinstance(profiles, str):
        profiles = json.loads(profiles)
    if not profiles:
        return await update_pipeline(pipeline_id, current_step="storyboard", status="paused")

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    image_style = config.get("image_style", "lifestyle_photo")

    await update_pipeline(pipeline_id, status="running", current_step="characters")
    try:
        tasks = []
        for profile in profiles:
            if profile.get("face_url"):
                tasks.append(None)
            else:
                prompt = build_character_face_prompt(profile, image_style)
                tasks.append(_call_image(prompt))

        results = []
        for t in tasks:
            if t is None:
                results.append(None)
            else:
                results.append(await t)

        for i, profile in enumerate(profiles):
            if results[i] is not None:
                profile["face_url"] = results[i]

        return await update_pipeline(
            pipeline_id,
            character_profiles=profiles,
            current_step="storyboard",
            status="paused",
        )
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


# ──────────────────────────────────────────────
# Pipeline step executors
# ──────────────────────────────────────────────

async def generate_copy(pipeline_id: str) -> dict:
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    prompt = build_copy_prompt(pipe["source_text"], config)

    await update_pipeline(pipeline_id, status="running", current_step="copy")
    try:
        copy_text = await _call_chat(prompt)
        return await update_pipeline(pipeline_id, copy_result=copy_text, current_step="script", status="paused")
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


async def generate_script(pipeline_id: str) -> dict:
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    if not pipe.get("copy_result"):
        raise ValueError("Copy text not generated yet")

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    prompt = build_script_prompt(pipe["copy_result"], config)

    await update_pipeline(pipeline_id, status="running", current_step="script")
    try:
        raw = await _call_chat(prompt)
        script = _parse_script_json(raw)
        return await update_pipeline(pipeline_id, script_result=script, current_step="storyboard", status="paused")
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


def _parse_script_json(raw: str) -> dict:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
    if "```" in text:
        text = text.split("```", 1)[0]
    return json.loads(text.strip())


async def generate_storyboard(pipeline_id: str) -> dict:
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    script = pipe["script_result"]
    if isinstance(script, str):
        script = json.loads(script)
    scenes = script.get("scenes", [])
    if not scenes:
        raise ValueError("Script has no scenes")

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    image_style = config.get("image_style", "lifestyle_photo")

    product_images = pipe.get("product_images")
    if isinstance(product_images, str):
        product_images = json.loads(product_images)
    character_profiles = pipe.get("character_profiles")
    if isinstance(character_profiles, str):
        character_profiles = json.loads(character_profiles)

    use_enhanced = bool(character_profiles or product_images)

    await update_pipeline(pipeline_id, status="running", current_step="storyboard")
    try:
        tasks = []
        for scene in scenes:
            if use_enhanced:
                llm_prompt = build_scene_to_image_prompt(
                    scene,
                    image_style=image_style,
                    product_images=product_images,
                    character_profiles=character_profiles,
                )
                tasks.append(_generate_image_with_transform(llm_prompt, scene, product_images, character_profiles))
            else:
                img_prompt = build_image_prompt(scene.get("visual_description", ""), image_style)
                tasks.append(_call_image_with_prompt(img_prompt))

        image_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for scene, result_or_exc in zip(scenes, image_results):
            if isinstance(result_or_exc, Exception):
                results.append({
                    "scene_id": scene["scene_id"], "image_url": "",
                    "status": "failed", "error": str(result_or_exc),
                    "prompt_used": "",
                })
            elif isinstance(result_or_exc, dict):
                results.append({
                    "scene_id": scene["scene_id"],
                    "image_url": result_or_exc.get("image_url", ""),
                    "status": "completed",
                    "prompt_used": result_or_exc.get("prompt_used", ""),
                })
            else:
                results.append({
                    "scene_id": scene["scene_id"],
                    "image_url": result_or_exc,
                    "status": "completed",
                    "prompt_used": "",
                })

        return await update_pipeline(pipeline_id, storyboard_results=results,
                                     current_step="video", status="paused")
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


async def _generate_image_with_transform(
    llm_prompt: str,
    scene: dict,
    product_images: list[str] | None,
    character_profiles: list[dict] | None,
    prompt_override: str | None = None,
) -> dict:
    """Transform scene → optimized image prompt → generate image.

    Returns {"image_url": ..., "prompt_used": ...} so user can review.
    """
    if prompt_override:
        optimized_prompt = prompt_override
    else:
        optimized_prompt = await _call_chat(llm_prompt)
        optimized_prompt = optimized_prompt.strip().strip('"').strip("'")

    ref_notes = []
    if scene.get("has_product") and product_images:
        ref_notes.append("the product shown must exactly match the provided reference")
    if scene.get("characters") and character_profiles:
        ref_notes.append("all character faces must match their reference portraits")
    if ref_notes:
        optimized_prompt += f". IMPORTANT: {', '.join(ref_notes)}"

    url = await _call_image(optimized_prompt)
    return {"image_url": url, "prompt_used": optimized_prompt}


async def regenerate_storyboard_scene(
    pipeline_id: str,
    scene_id: int,
    prompt_override: str | None = None,
) -> dict:
    """Regenerate a single storyboard image.

    If prompt_override is given, skip LLM prompt transformation and use it directly.
    """
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    script = pipe["script_result"]
    if isinstance(script, str):
        script = json.loads(script)
    scene = next((s for s in script.get("scenes", []) if s["scene_id"] == scene_id), None)
    if not scene:
        raise ValueError(f"Scene {scene_id} not found")

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    image_style = config.get("image_style", "lifestyle_photo")

    product_images = pipe.get("product_images")
    if isinstance(product_images, str):
        product_images = json.loads(product_images)
    character_profiles = pipe.get("character_profiles")
    if isinstance(character_profiles, str):
        character_profiles = json.loads(character_profiles)

    if character_profiles or product_images:
        llm_prompt = build_scene_to_image_prompt(
            scene, image_style=image_style,
            product_images=product_images, character_profiles=character_profiles,
        )
        gen_result = await _generate_image_with_transform(
            llm_prompt, scene, product_images, character_profiles,
            prompt_override=prompt_override,
        )
        new_url = gen_result["image_url"]
        new_prompt = gen_result["prompt_used"]
    elif prompt_override:
        new_url = await _call_image(prompt_override)
        new_prompt = prompt_override
    else:
        img_prompt = build_image_prompt(scene.get("visual_description", ""), image_style)
        new_url = await _call_image(img_prompt)
        new_prompt = img_prompt

    results = pipe["storyboard_results"]
    if isinstance(results, str):
        results = json.loads(results)
    for r in results:
        if r["scene_id"] == scene_id:
            r["image_url"] = new_url
            r["status"] = "completed"
            r["prompt_used"] = new_prompt
            break

    return await update_pipeline(pipeline_id, storyboard_results=results)


async def generate_videos(pipeline_id: str) -> dict:
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")

    script = pipe["script_result"]
    if isinstance(script, str):
        script = json.loads(script)
    storyboard = pipe["storyboard_results"]
    if isinstance(storyboard, str):
        storyboard = json.loads(storyboard)

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    scenes = script.get("scenes", [])
    sb_map = {r["scene_id"]: r for r in storyboard}

    video_ratio = config.get("video_ratio", "16:9")
    generate_audio = config.get("generate_audio", False)
    video_quality = config.get("video_quality", "standard")

    product_images = pipe.get("product_images")
    if isinstance(product_images, str):
        product_images = json.loads(product_images)
    character_profiles = pipe.get("character_profiles")
    if isinstance(character_profiles, str):
        character_profiles = json.loads(character_profiles)

    use_enhanced = bool(character_profiles or product_images)

    await update_pipeline(pipeline_id, status="running", current_step="video")
    try:
        video_tasks = []
        for scene in scenes:
            sb = sb_map.get(scene["scene_id"], {})
            storyboard_url = sb.get("image_url", "")
            dur = int(scene.get("duration", "5s").replace("s", ""))

            if use_enhanced:
                video_tasks.append((
                    scene["scene_id"],
                    _generate_video_with_transform(
                        scene, storyboard_url, dur,
                        product_images=product_images,
                        character_profiles=character_profiles,
                        generate_audio=generate_audio,
                        ratio=video_ratio,
                        quality=video_quality,
                    ),
                ))
            else:
                prompt = scene.get("visual_description", "")
                cam = scene.get("camera_movement", "")
                if cam:
                    prompt += f"，运镜：{cam}"
                video_tasks.append((
                    scene["scene_id"],
                    _call_video(
                        prompt, storyboard_url or None, dur,
                        generate_audio=generate_audio,
                        ratio=video_ratio,
                        quality=video_quality,
                    ),
                ))

        results = []
        for scene_id, coro in video_tasks:
            try:
                data = await coro
                results.append({
                    "scene_id": scene_id,
                    "task_id": data.get("task_id", ""),
                    "status": data.get("status", "processing"),
                    "video_url": data.get("video_url", ""),
                    "prompt_used": data.get("prompt_used", ""),
                    "reference_images_used": data.get("reference_images_used", []),
                    "first_frame_used": data.get("first_frame_used", ""),
                })
            except Exception as exc:
                results.append({"scene_id": scene_id, "task_id": "", "status": "failed", "error": str(exc)})

        return await update_pipeline(pipeline_id, video_results=results, status="paused")
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


async def _generate_video_with_transform(
    scene: dict,
    storyboard_url: str,
    duration: int,
    *,
    product_images: list[str] | None = None,
    character_profiles: list[dict] | None = None,
    generate_audio: bool = False,
    ratio: str = "16:9",
    quality: str = "standard",
    prompt_override: str | None = None,
) -> dict:
    """Use LLM to generate Seedance-optimized prompt, then call video API with reference images.

    Returns extra keys: prompt_used, reference_images_used, first_frame_used.
    """
    if prompt_override:
        optimized_prompt = prompt_override
    else:
        llm_prompt = build_scene_to_video_prompt(
            scene,
            product_images=product_images,
            character_profiles=character_profiles,
        )
        optimized_prompt = await _call_chat(llm_prompt)
        optimized_prompt = optimized_prompt.strip().strip('"').strip("'")

    ref_images = build_video_reference_images(
        scene,
        character_profiles=character_profiles,
        product_images=product_images,
    )

    result = await _call_video(
        optimized_prompt,
        duration=duration,
        first_frame=storyboard_url or None,
        reference_images=ref_images or None,
        generate_audio=generate_audio,
        ratio=ratio,
        quality=quality,
    )
    result["prompt_used"] = optimized_prompt
    result["reference_images_used"] = ref_images
    result["first_frame_used"] = storyboard_url
    return result


async def regenerate_video_scene(
    pipeline_id: str,
    scene_id: int,
    prompt_override: str | None = None,
) -> dict:
    """Regenerate a single video scene.

    If prompt_override is given, skip LLM prompt transformation and use it directly.
    """
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    script = pipe["script_result"]
    if isinstance(script, str):
        script = json.loads(script)
    scene = next((s for s in script.get("scenes", []) if s["scene_id"] == scene_id), None)
    if not scene:
        raise ValueError(f"Scene {scene_id} not found")

    storyboard = pipe["storyboard_results"]
    if isinstance(storyboard, str):
        storyboard = json.loads(storyboard)
    sb = next((r for r in storyboard if r["scene_id"] == scene_id), {})

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    dur = int(scene.get("duration", "5s").replace("s", ""))

    product_images = pipe.get("product_images")
    if isinstance(product_images, str):
        product_images = json.loads(product_images)
    character_profiles = pipe.get("character_profiles")
    if isinstance(character_profiles, str):
        character_profiles = json.loads(character_profiles)

    if character_profiles or product_images:
        data = await _generate_video_with_transform(
            scene, sb.get("image_url", ""), dur,
            product_images=product_images,
            character_profiles=character_profiles,
            generate_audio=config.get("generate_audio", False),
            ratio=config.get("video_ratio", "16:9"),
            quality=config.get("video_quality", "standard"),
            prompt_override=prompt_override,
        )
    elif prompt_override:
        data = await _call_video(
            prompt_override, sb.get("image_url") or None, dur,
            generate_audio=config.get("generate_audio", False),
            ratio=config.get("video_ratio", "16:9"),
            quality=config.get("video_quality", "standard"),
        )
        data["prompt_used"] = prompt_override
    else:
        prompt = scene.get("visual_description", "")
        cam = scene.get("camera_movement", "")
        if cam:
            prompt += f"，运镜：{cam}"
        data = await _call_video(
            prompt, sb.get("image_url") or None, dur,
            generate_audio=config.get("generate_audio", False),
            ratio=config.get("video_ratio", "16:9"),
            quality=config.get("video_quality", "standard"),
        )
        data["prompt_used"] = prompt

    results = pipe["video_results"]
    if isinstance(results, str):
        results = json.loads(results)
    found = False
    for r in results:
        if r["scene_id"] == scene_id:
            r["task_id"] = data.get("task_id", "")
            r["status"] = data.get("status", "processing")
            r["video_url"] = data.get("video_url", "")
            r["prompt_used"] = data.get("prompt_used", "")
            r["reference_images_used"] = data.get("reference_images_used", [])
            r["first_frame_used"] = data.get("first_frame_used", "")
            found = True
            break
    if not found:
        results.append({
            "scene_id": scene_id,
            "task_id": data.get("task_id", ""),
            "status": data.get("status", "processing"),
            "video_url": data.get("video_url", ""),
            "prompt_used": data.get("prompt_used", ""),
        })

    return await update_pipeline(pipeline_id, video_results=results)


# ──────────────────────────────────────────────
# Compose (FFmpeg)
# ──────────────────────────────────────────────

async def compose_final_video(pipeline_id: str) -> dict:
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")

    await update_pipeline(pipeline_id, status="running", current_step="compose")

    task_dir = DATA_ROOT / pipeline_id
    task_dir.mkdir(parents=True, exist_ok=True)

    video_results = pipe["video_results"]
    if isinstance(video_results, str):
        video_results = json.loads(video_results)

    script = pipe["script_result"]
    if isinstance(script, str):
        script = json.loads(script)
    scenes = script.get("scenes", [])

    clip_paths: list[Path] = []
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        for vr in sorted(video_results, key=lambda x: x.get("scene_id", 0)):
            url = vr.get("video_url", "")
            if not url:
                continue
            clip_path = task_dir / f"clip_{vr['scene_id']}.mp4"
            resp = await client.get(url)
            resp.raise_for_status()
            clip_path.write_bytes(resp.content)
            clip_paths.append(clip_path)

    if not clip_paths:
        await update_pipeline(pipeline_id, status="failed", error_message="No video clips to compose")
        raise ValueError("No video clips available")

    _generate_srt(task_dir / "subtitles.srt", scenes)

    concat_file = task_dir / "concat.txt"
    concat_file.write_text("\n".join(f"file '{p.name}'" for p in clip_paths), encoding="utf-8")

    final_path = task_dir / "final.mp4"
    srt_path = task_dir / "subtitles.srt"

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-vf", f"subtitles={srt_path.name}:force_style='FontSize=18,PrimaryColour=&Hffffff&'",
        "-c:a", "copy", str(final_path),
    ]
    try:
        subprocess.run(cmd, cwd=str(task_dir), check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, FileNotFoundError):
        cmd_simple = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", str(final_path),
        ]
        try:
            subprocess.run(cmd_simple, cwd=str(task_dir), check=True, capture_output=True, timeout=120)
        except FileNotFoundError:
            logger.warning("FFmpeg not available, skipping compose")
            await update_pipeline(pipeline_id, status="paused", current_step="done",
                                  error_message="FFmpeg not installed, clips available individually")
            return await get_pipeline(pipeline_id)

    final_url = f"/api/v1/content-studio/download/{pipeline_id}/final.mp4"
    return await update_pipeline(pipeline_id, final_video_url=final_url, current_step="done", status="completed")


def _generate_srt(srt_path: Path, scenes: list[dict]) -> None:
    lines = []
    offset_ms = 0
    for i, scene in enumerate(scenes):
        dur_s = int(scene.get("duration", "5s").replace("s", ""))
        narration = scene.get("narration", "")
        if not narration:
            offset_ms += dur_s * 1000
            continue
        start = _ms_to_srt(offset_ms)
        end = _ms_to_srt(offset_ms + dur_s * 1000)
        lines.append(f"{i + 1}\n{start} --> {end}\n{narration}\n")
        offset_ms += dur_s * 1000
    srt_path.write_text("\n".join(lines), encoding="utf-8")


def _ms_to_srt(ms: int) -> str:
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1000
    ms_rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"


# ──────────────────────────────────────────────
# ZIP download
# ──────────────────────────────────────────────

async def build_download_zip(pipeline_id: str) -> Path | None:
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        return None

    task_dir = DATA_ROOT / pipeline_id
    task_dir.mkdir(parents=True, exist_ok=True)

    zip_path = task_dir / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if pipe.get("copy_result"):
            zf.writestr("文案.md", pipe["copy_result"])
        if pipe.get("script_result"):
            script = pipe["script_result"]
            if not isinstance(script, str):
                script = json.dumps(script, ensure_ascii=False, indent=2)
            zf.writestr("脚本.json", script)

        for f in task_dir.iterdir():
            if f.suffix in (".mp4", ".png", ".jpg", ".srt") and f.name != "bundle.zip":
                zf.write(f, f.name)

    return zip_path


def get_file_path(pipeline_id: str, filename: str) -> Path | None:
    file_path = DATA_ROOT / pipeline_id / filename
    if file_path.exists() and file_path.is_file():
        return file_path
    return None


# ──────────────────────────────────────────────
# Cost estimation
# ──────────────────────────────────────────────

def estimate_cost(scene_count: int, avg_duration: int = 5) -> dict:
    llm_calls = scene_count * 2 + 2  # script analysis + prompt transforms (image + video) per scene
    image_cost = scene_count * 0.02
    char_face_cost = 0.02  # avg 1 character
    video_cost_fast = scene_count * avg_duration * 0.02
    video_cost_pro = scene_count * avg_duration * 0.10
    llm_cost = llm_calls * 0.005
    return {
        "scene_count": scene_count,
        "llm_calls": llm_calls,
        "llm_cost": round(llm_cost, 3),
        "image_cost": round(image_cost + char_face_cost, 2),
        "video_cost_fast": round(video_cost_fast, 2),
        "video_cost_pro": round(video_cost_pro, 2),
        "total_fast": round(image_cost + char_face_cost + video_cost_fast + llm_cost, 2),
        "total_pro": round(image_cost + char_face_cost + video_cost_pro + llm_cost, 2),
    }


# ──────────────────────────────────────────────
# Batch prompt transformation
# ──────────────────────────────────────────────

def _build_batch_image_prompt_request(
    scenes: list[dict],
    image_style: str,
    product_images: list[str] | None,
    character_profiles: list[dict] | None,
) -> str:
    """Build a single LLM prompt that transforms ALL scene descriptions at once."""
    style_hints = {
        "lifestyle_photo": "photorealistic lifestyle photography, natural lighting, warm tones",
        "cinematic": "cinematic film still, dramatic lighting, shallow depth of field",
        "vibrant": "vibrant commercial photography, bold colors, high contrast",
        "clean_modern": "clean modern product photography, minimalist, studio lighting",
        "warm_illustration": "warm digital illustration, soft pastel colors, gentle lighting",
    }
    hint = style_hints.get(image_style, style_hints["lifestyle_photo"])

    # Character reference block
    char_block = ""
    if character_profiles:
        char_lines = []
        for p in character_profiles:
            char_lines.append(f"  - {p['name']}：{p.get('gender', '')}，{p.get('age_range', '')}岁，{p.get('appearance', '')}")
        char_block = "\n## 人物档案（所有场景中同一人物的外貌描述用词必须完全一致）\n" + "\n".join(char_lines)

    product_block = ""
    if product_images:
        product_block = "\n## 产品要求\n有产品的场景，必须精确描述产品外观，确保不走形。\n"

    scene_lines = []
    for s in scenes:
        chars = s.get("characters", [])
        has_p = s.get("has_product", False)
        tags = []
        if chars:
            tags.append(f"人物: {', '.join(chars)}")
        if has_p:
            tags.append("含产品")
        tag_str = f" [{'; '.join(tags)}]" if tags else ""
        scene_lines.append(f"场景{s['scene_id']}{tag_str}: {s.get('visual_description', '')}")

    scenes_text = "\n".join(scene_lines)

    return f"""你是一位专业的 AI 图像生成提示词工程师。请将以下全部场景描述，逐一转换为高质量的英文图像生成提示词。
{char_block}
{product_block}

## 目标画面风格
{hint}

## 场景列表
{scenes_text}

## 规则
1. 每个场景输出一段独立的英文提示词，80-200 词
2. 结构：主体 → 动作/姿态 → 场景环境 → 光线色调 → 构图 → 画面风格
3. 人物外貌描述在所有场景中必须用完全相同的英文词（锚定一致性）
4. 产品外观描述在所有场景中必须用完全相同的英文词
5. 不要出现中文

请严格按以下格式输出（每个场景占一段，用 --- 分隔）：

SCENE_1:
[prompt text]
---
SCENE_2:
[prompt text]
---
..."""


def _parse_batch_prompts(raw: str, scene_count: int) -> list[str]:
    """Parse the batch prompt output into individual scene prompts."""
    raw = raw.strip()
    # Try splitting by --- or SCENE_N:
    parts = []
    if "---" in raw:
        segments = raw.split("---")
        for seg in segments:
            seg = seg.strip()
            # Remove SCENE_N: prefix
            for prefix_pattern in [f"SCENE_{i}:" for i in range(1, scene_count + 2)]:
                if seg.upper().startswith(prefix_pattern.upper()):
                    seg = seg[len(prefix_pattern):].strip()
                    break
            if seg:
                parts.append(seg)
    else:
        # Fallback: split by SCENE_N:
        import re
        segments = re.split(r'SCENE_\d+:', raw, flags=re.IGNORECASE)
        parts = [s.strip() for s in segments if s.strip()]

    # Pad or truncate to match scene count
    while len(parts) < scene_count:
        parts.append(parts[-1] if parts else "product photography scene")
    return parts[:scene_count]


# ──────────────────────────────────────────────
# Poll all video tasks
# ──────────────────────────────────────────────

async def poll_all_videos(pipeline_id: str, max_wait: int = 900) -> dict:
    """Wait for all video tasks in a pipeline to complete/fail."""
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")

    video_results = pipe.get("video_results")
    if isinstance(video_results, str):
        video_results = json.loads(video_results)
    if not video_results:
        raise ValueError("No video tasks to poll")

    pending_ids = {
        vr["task_id"]: vr["scene_id"]
        for vr in video_results
        if vr.get("task_id") and vr.get("status") not in ("succeeded", "completed", "failed", "error")
    }

    if not pending_ids:
        return await get_pipeline(pipeline_id)

    elapsed = 0
    interval = 10
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        while elapsed < max_wait and pending_ids:
            await asyncio.sleep(interval)
            elapsed += interval

            done_this_round = []
            for task_id in list(pending_ids.keys()):
                try:
                    resp = await client.get(f"{HUB_VIDEO_STATUS}/{task_id}")
                    resp.raise_for_status()
                    data = resp.json()
                    status = data.get("status", "")
                    if status in ("succeeded", "completed"):
                        for vr in video_results:
                            if vr["task_id"] == task_id:
                                vr["status"] = "succeeded"
                                vr["video_url"] = data.get("video_url", "")
                        done_this_round.append(task_id)
                    elif status in ("failed", "error"):
                        for vr in video_results:
                            if vr["task_id"] == task_id:
                                vr["status"] = "failed"
                                vr["error"] = data.get("error", "")
                        done_this_round.append(task_id)
                except Exception as exc:
                    logger.warning("Poll video %s failed: %s", task_id, exc)

            for tid in done_this_round:
                pending_ids.pop(tid, None)

            await update_pipeline(pipeline_id, video_results=video_results)
            interval = min(interval + 5, 30)

    return await get_pipeline(pipeline_id)


# ──────────────────────────────────────────────
# Auto-run: one-click full pipeline execution
# ──────────────────────────────────────────────

async def auto_run(
    pipeline_id: str,
    *,
    skip_copy: bool = False,
    skip_script: bool = False,
    wait_videos: bool = True,
    auto_compose: bool = True,
) -> dict:
    """Execute the full pipeline in one call.

    If script is already imported and copy is not needed, set skip_copy/skip_script=True.
    Steps: [copy] → [script] → analyze → characters → storyboard → video → [poll] → [compose]
    """
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")

    # Step 1: Generate copy (if needed)
    if not skip_copy and not pipe.get("copy_result"):
        logger.info("[auto_run] %s: generating copy...", pipeline_id)
        pipe = await generate_copy(pipeline_id)

    # Step 2: Generate script (if needed)
    if not skip_script and not pipe.get("script_result"):
        logger.info("[auto_run] %s: generating script...", pipeline_id)
        pipe = await generate_script(pipeline_id)

    # Step 3: Analyze script for characters/products
    script = pipe.get("script_result")
    if isinstance(script, str):
        script = json.loads(script)
    has_chars = any(s.get("characters") for s in (script or {}).get("scenes", []))
    if not has_chars:
        logger.info("[auto_run] %s: analyzing script...", pipeline_id)
        pipe = await analyze_script(pipeline_id)

    # Step 4: Generate character faces (if any)
    profiles = pipe.get("character_profiles")
    if isinstance(profiles, str):
        profiles = json.loads(profiles)
    if profiles and any(not p.get("face_url") for p in profiles):
        logger.info("[auto_run] %s: generating character faces...", pipeline_id)
        pipe = await generate_character_faces(pipeline_id)

    # Step 5: Generate storyboard
    logger.info("[auto_run] %s: generating storyboard...", pipeline_id)
    pipe = await generate_storyboard(pipeline_id)

    # Step 6: Generate videos
    logger.info("[auto_run] %s: generating videos...", pipeline_id)
    pipe = await generate_videos(pipeline_id)

    # Step 7: Wait for all videos to complete
    if wait_videos:
        logger.info("[auto_run] %s: waiting for videos...", pipeline_id)
        pipe = await poll_all_videos(pipeline_id)

    # Step 8: Compose final video
    if auto_compose:
        video_results = pipe.get("video_results")
        if isinstance(video_results, str):
            video_results = json.loads(video_results)
        all_done = all(
            vr.get("video_url") for vr in (video_results or [])
            if vr.get("status") != "failed"
        )
        if all_done:
            logger.info("[auto_run] %s: composing final video...", pipeline_id)
            pipe = await compose_final_video(pipeline_id)

    return pipe
