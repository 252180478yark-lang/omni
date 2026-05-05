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
from app.services.prompt_commons import (
    KB_AS_CREATIVE_MATERIAL,
    KB_AS_STYLE_SAMPLE,
    format_kb_snippets,
    format_style_samples,
)
from app.services.prompt_rules import log_feedback, render_rules_suffix
from app.services.prompt_templates import (
    build_copy_prompt,
    build_character_face_prompt,
    build_image_prompt,
    build_scene_to_image_prompt,
    build_scene_to_video_prompt,
    build_script_analysis_prompt,
    build_script_prompt,
    build_typed_reference_images,
    build_video_reference_images,
)

logger = logging.getLogger(__name__)

DATA_ROOT = Path("/app/data/content-studio")
HUB_BASE = settings.ai_provider_hub_url.rstrip("/")
HUB_CHAT = f"{HUB_BASE}/api/v1/ai/chat"
HUB_IMAGE = f"{HUB_BASE}/api/v1/ai/images/generate"
HUB_VIDEO = f"{HUB_BASE}/api/v1/ai/videos/generate"
HUB_VIDEO_STATUS = f"{HUB_BASE}/api/v1/ai/videos/status"
TARGET_SCENE_COUNT = 10

_HTTP_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)


# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────

async def create_pipeline(
    title: str,
    source_text: str,
    config: dict,
    *,
    product_id: str | None = None,
    brief_id: str | None = None,
    digital_human_id: str | None = None,
    sku_id: str | None = None,
    audience_package: dict | None = None,
    extra_reference_images: list[dict] | None = None,
    skip_final_concat: bool = False,
) -> dict:
    pool = get_pool()
    resolved_source = source_text
    resolved_audience_pkg = audience_package
    resolved_sku_id = sku_id
    if brief_id:
        brief = await pool.fetchrow(
            """SELECT title, usp, scenarios, audience_profile, tone_style, dmp_sop, sku_id
               FROM content_studio.briefs WHERE id = $1""",
            uuid.UUID(brief_id),
        )
        if brief:
            if not resolved_source:
                resolved_source = (
                    f"Brief: {brief['title']}\n"
                    f"USP: {brief['usp']}\n"
                    f"Scenarios: {json.dumps(brief.get('scenarios') or [], ensure_ascii=False)}\n"
                    f"Audience: {json.dumps(brief.get('audience_profile') or {}, ensure_ascii=False)}\n"
                    f"Tone: {json.dumps(brief.get('tone_style') or {}, ensure_ascii=False)}\n"
                )
            # 自动带入 audience_package：若调用方未显式传入，则从 brief.audience_profile 提取
            if not resolved_audience_pkg:
                ap = brief.get("audience_profile") or {}
                if not isinstance(ap, dict):
                    ap = {}
                pkg_id = ap.get("dmp_package_id")
                if pkg_id:
                    resolved_audience_pkg = {
                        "package_id": pkg_id,
                        "name": ap.get("dmp_package_name") or pkg_id,
                        "tags": ap.get("tags") or {},
                        "notes": (brief.get("dmp_sop") or "")[:200],
                    }
            # 若 brief 已绑 sku_id 且调用方未显式覆盖，自动继承
            if not resolved_sku_id and brief.get("sku_id"):
                resolved_sku_id = brief["sku_id"]
    row = await pool.fetchrow(
        """INSERT INTO content_studio.pipelines
           (title, source_text, config, product_id, brief_id, digital_human_id,
            sku_id, audience_package, extra_reference_images, skip_final_concat)
           VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10)
           RETURNING *""",
        title,
        resolved_source,
        json.dumps(config, ensure_ascii=False),
        uuid.UUID(product_id) if product_id else None,
        uuid.UUID(brief_id) if brief_id else None,
        uuid.UUID(digital_human_id) if digital_human_id else None,
        resolved_sku_id,
        json.dumps(resolved_audience_pkg or {}, ensure_ascii=False),
        json.dumps(extra_reference_images or [], ensure_ascii=False),
        skip_final_concat,
    )
    return dict(row)


async def set_character_avatar_map(pipeline_id: str, mapping: dict[str, str]) -> dict:
    """覆盖 pipeline.character_avatar_map：scene 角色名 → digital_human_id。"""
    cleaned: dict[str, str] = {}
    for k, v in (mapping or {}).items():
        key = str(k).strip()
        val = str(v).strip() if v else ""
        if not key:
            continue
        if val:
            try:
                uuid.UUID(val)  # 校验合法 uuid
            except ValueError:
                raise ValueError(f"invalid avatar uuid for character '{key}': {val}")
            cleaned[key] = val
    result = await update_pipeline(pipeline_id, character_avatar_map=cleaned)
    if not result:
        raise ValueError("Pipeline not found")
    return result


async def set_extra_reference_images(pipeline_id: str, refs: list[dict]) -> dict:
    """覆盖 pipeline 的临时上传参考图列表（不污染 Avatar/产品库）。"""
    cleaned: list[dict] = []
    for r in refs or []:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        ref_type = r.get("type") or "reference"
        if ref_type not in ("character", "product", "scene", "style", "reference"):
            ref_type = "reference"
        cleaned.append({
            "url": url,
            "type": ref_type,
            "weight": float(r.get("weight", 1.0)),
        })
    result = await update_pipeline(pipeline_id, extra_reference_images=cleaned)
    if not result:
        raise ValueError("Pipeline not found")
    return result


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
                  product_id, brief_id, digital_human_id, created_at, updated_at
           FROM content_studio.pipelines ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
        limit, offset,
    )
    return [dict(r) for r in rows]


async def update_pipeline(pipeline_id: str, **fields: object) -> dict | None:
    # 状态切到非失败态时若 caller 未管 error_message，自动清掉残留旧错
    # （否则上一次 failed 留的 error_message 会一直残留）
    if (
        fields.get("status") in ("paused", "running", "completed")
        and "error_message" not in fields
    ):
        fields["error_message"] = None
    pool = get_pool()
    sets = []
    vals = []
    idx = 1
    for key, val in fields.items():
        if key in ("id", "created_at"):
            continue
        if key in ("script_result", "storyboard_results", "video_results", "config",
                    "cost_estimate", "actual_cost", "product_images", "character_profiles",
                    "extra_reference_images", "audience_package", "character_avatar_map"):
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

async def _call_chat(
    prompt: str,
    system: str = "",
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    json_mode: bool = False,
    flywheel_node: str | None = None,
    flywheel_scope: dict | None = None,
) -> str:
    """调 ai-provider-hub 的 chat 端点。

    json_mode=True 时强制 JSON 输出。

    flywheel_node 传入节点 id 时,自动完成 3 件事:
      1. prompt 末尾拼上累积规则 suffix
      2. 正常调 LLM
      3. log_feedback 留痕（供前端后续反馈）
    """
    if flywheel_node:
        try:
            prompt = prompt + await render_rules_suffix(flywheel_node, flywheel_scope)
        except Exception:
            pass

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict = {"messages": messages, "temperature": temperature}
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(HUB_CHAT, json=payload)
        resp.raise_for_status()
        data = resp.json()
    content = data.get("content", "")
    if json_mode and not str(content).strip():
        for key in ("message", "text", "output"):
            alt = data.get(key)
            if isinstance(alt, str) and alt.strip():
                content = alt
                break
        if not str(content).strip():
            logger.warning("empty json_mode chat response keys=%s body=%s", list(data.keys()), str(data)[:500])

    if flywheel_node:
        try:
            await log_feedback(
                flywheel_node,
                input_ref=flywheel_scope,
                full_prompt=prompt,
                output=content,
            )
        except Exception:
            pass
    return content


async def _call_image_with_prompt(
    prompt: str,
    model: str | None = None,
    *,
    provider: str | None = None,
    reference_images: list[dict] | None = None,
) -> dict:
    """Call image generation and return both URL and the prompt used."""
    url = await _call_image(prompt, model=model, provider=provider, reference_images=reference_images)
    return {"image_url": url, "prompt_used": prompt}


def _stage_model(pipe: dict | None, stage: str) -> tuple[str | None, str | None]:
    """Extract (provider, model) for a named pipeline stage from pipe.config.models.

    Stages: copy, script, face, storyboard, video.
    Returns (None, None) to let the hub pick its default.
    """
    if not pipe:
        return None, None
    config = pipe.get("config")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = {}
    if not isinstance(config, dict):
        return None, None
    models = config.get("models") or {}
    if not isinstance(models, dict):
        return None, None
    sel = models.get(stage)
    if not isinstance(sel, dict):
        return None, None
    provider = (sel.get("provider") or None) or None
    model = (sel.get("model") or None) or None
    return provider, model


def _dedupe_refs(reference_images: list[dict] | None) -> list[dict]:
    if not reference_images:
        return []
    seen: set[str] = set()
    result: list[dict] = []
    for ref in reference_images:
        url = str(ref.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append({
            "url": url,
            "type": ref.get("type", "reference"),
            "weight": float(ref.get("weight", 1.0)),
        })
    return result


async def _call_image(
    prompt: str,
    *,
    model: str | None = None,
    provider: str | None = None,
    reference_images: list[dict] | None = None,
) -> str:
    payload: dict = {
        "prompt": prompt,
        "size": "1536x1024",
        "quality": "high",
        "n": 1,
    }
    if model:
        payload["model"] = model
    if provider:
        payload["provider"] = provider
    refs = _dedupe_refs(reference_images)
    if refs:
        payload["reference_images"] = refs
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
    provider: str | None = None,
    model: str | None = None,
    reference_images: list[str | dict] | None = None,
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
        "duration": min(max(int(duration or 5), 4), 15),
        "ratio": ratio,
        "aspect_ratio": ratio,
        "generate_audio": generate_audio,
        "mode": mode,
        "quality": quality,
    }
    if not provider:
        provider = "seedance"
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model
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
    script_prov, script_mdl = _stage_model(pipe, "script")

    for scene in scenes:
        if use_enhanced:
            llm_prompt = build_scene_to_image_prompt(
                scene, image_style=image_style,
                product_images=product_images, character_profiles=character_profiles,
            )
            optimized = await _call_chat(
                llm_prompt, provider=script_prov, model=script_mdl,
                flywheel_node="content.scene_to_image",
                flywheel_scope={"image_style": image_style, "pipeline_id": pipeline_id},
            )
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
    script_prov, script_mdl = _stage_model(pipe, "script")

    for scene in scenes:
        sb = sb_map.get(scene["scene_id"], {})
        storyboard_url = sb.get("image_url", "")

        if use_enhanced:
            llm_prompt = build_scene_to_video_prompt(
                scene, product_images=product_images, character_profiles=character_profiles,
            )
            optimized = await _call_chat(
                llm_prompt, provider=script_prov, model=script_mdl,
                flywheel_node="content.scene_to_video",
                flywheel_scope={"pipeline_id": pipeline_id},
            )
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


async def import_script(pipeline_id: str, script: dict, *, copy_result: str | None = None) -> dict:
    """Import a script generated externally (e.g. from knowledge Q&A module)."""
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    fields: dict = {
        "script_result": script,
        "current_step": "analyze",
        "status": "paused",
        "error_message": None,
    }
    if copy_result is not None:
        fields["copy_result"] = copy_result
    return await update_pipeline(pipeline_id, **fields)


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
    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    avatar_guidance = (config.get("avatar_generation_guidance") or "").strip()

    await update_pipeline(pipeline_id, status="running", current_step="analyze")
    try:
        prompt = build_script_analysis_prompt(script, avatar_guidance=avatar_guidance)
        prompt += await render_rules_suffix("content.script_analysis", {"pipeline_id": pipeline_id})
        prov, mdl = _stage_model(pipe, "script")
        raw = await _call_chat(prompt, provider=prov, model=mdl, temperature=0.2, json_mode=True)
        await log_feedback(
            "content.script_analysis",
            input_ref={"pipeline_id": pipeline_id},
            full_prompt=prompt,
            output=raw,
        )
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

    # ── 角色 → Avatar 映射（优先使用 character_avatar_map；其次 digital_human_id） ──
    char_map_raw = pipe.get("character_avatar_map") or {}
    if isinstance(char_map_raw, str):
        try:
            char_map_raw = json.loads(char_map_raw)
        except Exception:
            char_map_raw = {}
    char_map: dict[str, str] = {
        str(k).strip(): str(v).strip() for k, v in (char_map_raw or {}).items() if v
    }

    pool = get_pool()

    async def _avatar_face(avatar_id: str) -> tuple[str, str | None]:
        """Return (primary_face_url, name)."""
        try:
            dh = await pool.fetchrow(
                "SELECT id, name, seed_face_url, face_urls FROM content_studio.digital_humans WHERE id = $1",
                uuid.UUID(avatar_id),
            )
        except Exception:
            return "", None
        if not dh:
            return "", None
        face_urls = dh.get("face_urls") or []
        if isinstance(face_urls, str):
            face_urls = json.loads(face_urls)
        face = (face_urls[0] if face_urls else None) or dh["seed_face_url"] or ""
        return str(face), dh.get("name")

    # 已有 profiles：把映射里的角色直接贴 face_url，避免再走 LLM 生成
    if profiles and char_map:
        for p in profiles:
            avatar_id = char_map.get(p.get("name") or "") or char_map.get(p.get("id") or "")
            if avatar_id:
                face_url, _ = await _avatar_face(avatar_id)
                if face_url:
                    p["face_url"] = face_url
                    p["avatar_id"] = avatar_id
                    p["is_virtual_avatar"] = True
        # 若全部角色都已贴上脸，可以直接 paused 进 storyboard
        if all(p.get("face_url") for p in profiles):
            return await update_pipeline(
                pipeline_id,
                character_profiles=profiles,
                current_step="storyboard",
                status="paused",
            )

    if not profiles and pipe.get("digital_human_id"):
        dh = await pool.fetchrow(
            "SELECT id, name, seed_face_url, face_urls, gender, age_range FROM content_studio.digital_humans WHERE id = $1",
            pipe["digital_human_id"],
        )
        if dh:
            face_urls = dh.get("face_urls") or []
            if isinstance(face_urls, str):
                face_urls = json.loads(face_urls)
            face = (face_urls[0] if face_urls else None) or dh["seed_face_url"]
            profiles = [{
                "id": f"dh_{str(dh['id'])[:8]}",
                "name": dh.get("name", "数字人"),
                "gender": dh.get("gender", ""),
                "age_range": dh.get("age_range", ""),
                "appearance": "固定数字人形象",
                "scene_ids": [],
                "face_url": face,
                "avatar_id": str(dh["id"]),
                "is_virtual_avatar": True,
            }]
    if not profiles:
        return await update_pipeline(pipeline_id, current_step="storyboard", status="paused")

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    image_style = config.get("image_style", "lifestyle_photo")
    avatar_guidance = (config.get("avatar_generation_guidance") or "").strip()

    await update_pipeline(pipeline_id, status="running", current_step="characters")
    try:
        face_prov, face_mdl = _stage_model(pipe, "face")
        tasks = []
        for profile in profiles:
            if profile.get("face_url"):
                tasks.append(None)
            else:
                prompt = build_character_face_prompt(
                    profile,
                    image_style,
                    avatar_guidance=avatar_guidance,
                )
                tasks.append(_call_image(prompt, provider=face_prov, model=face_mdl))

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
    # 飞轮：按 copy_style 细分 scope
    copy_scope = {"copy_style": config.get("copy_style", "grassplanting"), "pipeline_id": pipeline_id}
    prompt += await render_rules_suffix("content.copy", copy_scope)

    await update_pipeline(pipeline_id, status="running", current_step="copy")
    try:
        prov, mdl = _stage_model(pipe, "copy")
        copy_text = await _call_chat(prompt, provider=prov, model=mdl)
        await log_feedback("content.copy", input_ref=copy_scope, full_prompt=prompt, output=copy_text)
        return await update_pipeline(pipeline_id, copy_result=copy_text, current_step="script", status="paused")
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


def _banned_words() -> list[str]:
    raw = (settings.content_pipeline_banned_words or "").strip()
    if not raw:
        return []
    return [w.strip() for w in raw.split(",") if w.strip()]


def _hits_banned_words(script: dict, banned: list[str]) -> list[str]:
    if not banned:
        return []
    hits: set[str] = set()
    for scene in script.get("scenes") or []:
        narration = (scene.get("narration") or "")
        for w in banned:
            if w and w in narration:
                hits.add(w)
    return sorted(hits)


def _normalize_and_validate_scene_count(script: dict) -> int:
    scenes = script.get("scenes") if isinstance(script, dict) else None
    if not isinstance(scenes, list):
        return 0
    for idx, scene in enumerate(scenes, 1):
        if isinstance(scene, dict):
            scene["scene_id"] = idx
    return len(scenes)


async def _retrieve_tri_kb_context(brief: dict | None) -> tuple[list[dict], list[str]]:
    """三 KB 联合召回 + 反 AI 语料。

    返回 (kb_snippets, voice_samples)：
      - kb_snippets: list[dict]，每个 dict 含 source/id/content/score，供 format_kb_snippets()
        渲染为 <kb_context> XML。source ∈ {ocean_engine, audience_report, content_strategy, history}
      - voice_samples: list[str]，口播语感样本（非事实引用，供 format_style_samples() 渲染）

    若 brief 为空或 KB 未配置则返回空列表，不挡流程。
    """
    if not brief:
        return [], []

    try:
        from app.services.rag_chain import retrieve_multi_kb, retrieve_only
    except Exception:
        return [], []

    usp = brief.get("usp") or ""
    scenarios = brief.get("scenarios") or []
    if isinstance(scenarios, str):
        try:
            scenarios = json.loads(scenarios)
        except Exception:
            scenarios = []
    audience = brief.get("audience_profile") or {}
    if isinstance(audience, str):
        try:
            audience = json.loads(audience)
        except Exception:
            audience = {}
    extra = brief.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}

    queries = {
        "ocean_engine": (settings.content_pipeline_kb_ocean_engine, usp[:300]),
        "audience_report": (
            settings.content_pipeline_kb_audience_report,
            json.dumps(audience.get("insights") or audience, ensure_ascii=False)[:300],
        ),
        "content_strategy": (
            settings.content_pipeline_kb_content_strategy,
            " ".join(
                (s.get("context") or s.get("scene") or "") if isinstance(s, dict) else str(s)
                for s in scenarios
            )[:300] or usp[:300],
        ),
    }

    # 三层融合策略：候选池 8/KB，保底 2/KB，threshold 0.30，总上限 10
    TOP_K_PER_KB = 8
    MIN_PER_KB = 2
    SCORE_THRESHOLD = 0.30
    TOTAL_LIMIT = 10

    per_kb_candidates: dict[str, list[dict]] = {}
    for name, (kb_id, query) in queries.items():
        kb_id = (kb_id or "").strip()
        if not kb_id or not query:
            continue
        try:
            hits = await retrieve_multi_kb(
                query, [kb_id],
                top_k_per_kb=TOP_K_PER_KB,
                min_per_kb=0,
                score_threshold=0.0,
                total_limit=None,
                time_decay=(name == "content_strategy"),
                kb_name_map={kb_id: name},
            )
        except Exception as exc:
            logger.debug("tri-KB retrieve %s failed: %s", name, exc)
            continue
        for h in hits:
            c = h.get("content") or ""
            if len(c) > 400:
                h["content"] = c[:400] + "..."
        per_kb_candidates[name] = hits

    # 融合
    guaranteed: list[dict] = []
    candidates: list[dict] = []
    for name in queries.keys():
        hits = per_kb_candidates.get(name, [])
        for idx, s in enumerate(hits):
            if idx < MIN_PER_KB:
                guaranteed.append(s)
            elif s["score"] >= SCORE_THRESHOLD:
                candidates.append(s)

    snippets = guaranteed + sorted(candidates, key=lambda x: x["score"], reverse=True)
    if TOTAL_LIMIT and len(snippets) > TOTAL_LIMIT:
        g_count = len(guaranteed)
        if g_count >= TOTAL_LIMIT:
            snippets = snippets[:TOTAL_LIMIT]
        else:
            head = snippets[:g_count]
            tail = sorted(snippets[g_count:], key=lambda x: x["score"], reverse=True)
            snippets = head + tail[: (TOTAL_LIMIT - g_count)]

    # 历史复盘经验作为 "history" 来源的一条特殊 snippet（不参与融合,直接插入）
    lessons = (extra.get("lessons_learned") or "").strip()
    if lessons:
        snippets.append({
            "source": "history",
            "kb_id": "",
            "id": "last_review",
            "content": f"最近一次复盘要点：{lessons[:600]}",
            "score": 1.0,
            "title": None,
        })

    # 反 AI 语料（风格样本，不是事实）- 直接 retrieve_only 单 KB 拿 3 条即可
    voice_examples: list[str] = []
    anti_ai_kb = (settings.anti_ai_corpus_kb_id or "").strip()
    if anti_ai_kb:
        try:
            samples = await retrieve_only(usp[:200] or "口播 真人 自然 语气", anti_ai_kb, top_k=3)
            for s in samples:
                t = (s.get("content") or "")[:300]
                if t:
                    voice_examples.append(t)
        except Exception as exc:
            logger.debug("anti-ai KB retrieve failed: %s", exc)

    return snippets, voice_examples


async def generate_script(pipeline_id: str) -> dict:
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")
    if not pipe.get("copy_result"):
        raise ValueError("Copy text not generated yet")

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    banned = _banned_words()

    # ── tri-KB 联合召回（基于 brief） ──
    brief: dict | None = None
    if pipe.get("brief_id"):
        try:
            from app.services import briefs as briefs_svc
            brief = await briefs_svc.get_brief(str(pipe["brief_id"]))
        except Exception as exc:
            logger.debug("brief fetch failed: %s", exc)

    kb_snippets, voice_examples = await _retrieve_tri_kb_context(brief)
    # 统一 XML 格式 + 角色规则。即使无召回也渲染为 empty 标记,让 LLM 明确知道没资料。
    kb_block = format_kb_snippets(kb_snippets)
    kb_context_text = (
        f"\n\n{KB_AS_CREATIVE_MATERIAL}\n\n"
        f"## 知识库召回（三 KB：ocean_engine / audience_report / content_strategy + history）\n"
        f"{kb_block}"
    )
    # 风格样本（反 AI 语料）—— 单独的 STYLE_SAMPLE 角色规则,防止被当成事实引用
    if voice_examples:
        style_block = format_style_samples(voice_examples)
        kb_context_text += f"\n\n{KB_AS_STYLE_SAMPLE}\n\n{style_block}"

    # voice_examples 已通过 kb_context_text 以 STYLE_SAMPLE 规则注入,
    # 不再传给 build_script_prompt (避免双重注入)。
    target_purpose = brief.get("target_purpose") if brief else None
    prompt = build_script_prompt(
        pipe["copy_result"], config,
        banned_words=banned,
        voice_examples=None,
        target_purpose=target_purpose,
    )
    if kb_context_text:
        prompt = prompt + kb_context_text

    # 飞轮：拼上累积规则（按 pace + image_style 细分 scope）
    script_scope = {
        "pace": config.get("pace", "medium"),
        "image_style": config.get("image_style", "lifestyle_photo"),
        "pipeline_id": pipeline_id,
    }
    prompt += await render_rules_suffix("content.script", script_scope)

    await update_pipeline(pipeline_id, status="running", current_step="script")
    try:
        prov, mdl = _stage_model(pipe, "script")
        raw = await _call_chat(prompt, provider=prov, model=mdl, temperature=0.6, json_mode=True)
        await log_feedback("content.script", input_ref=script_scope, full_prompt=prompt, output=raw)
        script = _parse_script_json(raw)

        hits = _hits_banned_words(script, banned)
        if hits:
            logger.info("anti-AI banned words hit: %s; regenerating once", hits)
            corrective = (
                f"\n\n## 上一版命中以下口播禁用词：{', '.join(hits)}\n"
                "请重新生成完整脚本，narration 中绝对不能出现这些词，"
                "改用更口语化、生活化、真实感强的中文表达。"
            )
            raw2 = await _call_chat(prompt + corrective, provider=prov, model=mdl, temperature=0.6, json_mode=True)
            script = _parse_script_json(raw2)

        scene_count = _normalize_and_validate_scene_count(script)
        if scene_count != TARGET_SCENE_COUNT:
            logger.info("script scene count=%s; regenerating once for target=%s", scene_count, TARGET_SCENE_COUNT)
            corrective = (
                f"\n\n## 上一版 scene 数量不符合闭环验收要求\n"
                f"上一版输出了 {scene_count} 个 scenes。请重新生成完整脚本："
                f"必须恰好 {TARGET_SCENE_COUNT} 个 scenes，scene_id 从 1 到 {TARGET_SCENE_COUNT} 连续编号，"
                "并保持同一主角与同一产品在所有相关场景中肉眼可识别。"
            )
            raw3 = await _call_chat(prompt + corrective, provider=prov, model=mdl, temperature=0.6, json_mode=True)
            script = _parse_script_json(raw3)
            scene_count = _normalize_and_validate_scene_count(script)
        if scene_count != TARGET_SCENE_COUNT:
            raise ValueError(f"Script must contain exactly {TARGET_SCENE_COUNT} scenes, got {scene_count}")

        return await update_pipeline(
            pipeline_id,
            script_result=script,
            current_step="storyboard",
            status="paused",
            error_message=None,
        )
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


def _parse_script_json(raw: str) -> dict:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
        if "```" in text:
            text = text.split("```", 1)[0]
    elif text.startswith("```"):
        text = text.split("```", 1)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        if "```" in text:
            text = text.split("```", 1)[0]
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return json.loads(text.strip())


def _split_extra_refs(extras: list[dict] | None) -> tuple[list[str], list[str]]:
    """把 pipeline.extra_reference_images 拆成 (character_urls, product_urls)。"""
    char_urls: list[str] = []
    prod_urls: list[str] = []
    for r in extras or []:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        t = (r.get("type") or "reference").lower()
        if t == "character":
            char_urls.append(url)
        elif t == "product":
            prod_urls.append(url)
    return char_urls, prod_urls


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
    extra_refs = pipe.get("extra_reference_images") or []
    if isinstance(extra_refs, str):
        extra_refs = json.loads(extra_refs)
    extra_char_urls, extra_prod_urls = _split_extra_refs(extra_refs)

    # 合并：临时上传的产品图也追加进 product_images（不污染 DB）
    effective_product_images = list(product_images or []) + extra_prod_urls

    # 任何场景需要人脸 / 产品时硬校验：缺一即拒
    needs_character = any(s.get("characters") for s in scenes)
    needs_product = any(s.get("has_product") for s in scenes)
    strict_reference_mode = bool(config.get("strict_reference_mode", False))

    has_char_ref = bool(
        (character_profiles and any(p.get("face_url") for p in character_profiles))
        or extra_char_urls
        or pipe.get("digital_human_id")
    )
    has_product_ref = bool(effective_product_images)

    if strict_reference_mode and needs_character and not has_char_ref:
        raise ValueError(
            "缺少人脸参考图：请从数字人脸库选择 Avatar，或为本流水线临时上传 1~3 张人脸参考图"
        )
    if strict_reference_mode and needs_product and not has_product_ref:
        raise ValueError(
            "缺少产品参考图：请上传产品白底图，或为本流水线临时上传 1~3 张产品参考图"
        )

    use_enhanced = bool(character_profiles or effective_product_images)

    await update_pipeline(pipeline_id, status="running", current_step="storyboard")
    try:
        script_prov, script_mdl = _stage_model(pipe, "script")
        img_prov, img_mdl = _stage_model(pipe, "storyboard")
        tasks = []
        for scene in scenes:
            if use_enhanced:
                llm_prompt = build_scene_to_image_prompt(
                    scene,
                    image_style=image_style,
                    product_images=effective_product_images,
                    character_profiles=character_profiles,
                )
                tasks.append(_generate_image_with_transform(
                    llm_prompt, scene, effective_product_images, character_profiles,
                    extra_char_urls=extra_char_urls,
                    chat_provider=script_prov, chat_model=script_mdl,
                    image_provider=img_prov, image_model=img_mdl,
                ))
            else:
                img_prompt = build_image_prompt(scene.get("visual_description", ""), image_style)
                tasks.append(_call_image_with_prompt(img_prompt, provider=img_prov, model=img_mdl))

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

        return await update_pipeline(
            pipeline_id,
            storyboard_results=results,
            current_step="video",
            status="paused",
            error_message=None,
        )
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


async def _generate_image_with_transform(
    llm_prompt: str,
    scene: dict,
    product_images: list[str] | None,
    character_profiles: list[dict] | None,
    prompt_override: str | None = None,
    *,
    extra_char_urls: list[str] | None = None,
    chat_provider: str | None = None,
    chat_model: str | None = None,
    image_provider: str | None = None,
    image_model: str | None = None,
) -> dict:
    """Transform scene → optimized image prompt → generate image.

    Returns {"image_url": ..., "prompt_used": ...} so user can review.
    """
    if prompt_override:
        optimized_prompt = prompt_override
    else:
        optimized_prompt = await _call_chat(
            llm_prompt, provider=chat_provider, model=chat_model,
            flywheel_node="content.scene_to_image",
            flywheel_scope={"scene_id": scene.get("scene_id")},
        )
        optimized_prompt = optimized_prompt.strip().strip('"').strip("'")

    ref_notes = []
    if scene.get("has_product") and product_images:
        ref_notes.append("the product shown must exactly match the provided reference")
    if scene.get("characters") and (character_profiles or extra_char_urls):
        ref_notes.append("all character faces must match their reference portraits")
    if ref_notes:
        optimized_prompt += f". IMPORTANT: {', '.join(ref_notes)}"

    typed_refs = build_typed_reference_images(
        scene,
        character_profiles=character_profiles,
        product_images=product_images,
    )
    # 把 pipeline 临时上传的人脸参考图追加进去（避免漏挂）
    if extra_char_urls:
        existing = {r.get("url") for r in typed_refs}
        for u in extra_char_urls:
            if u and u not in existing:
                typed_refs.append({"url": u, "type": "character", "weight": 0.8})
    url = await _call_image(
        optimized_prompt,
        provider=image_provider, model=image_model,
        reference_images=typed_refs,
    )
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

    script_prov, script_mdl = _stage_model(pipe, "script")
    img_prov, img_mdl = _stage_model(pipe, "storyboard")

    if character_profiles or product_images:
        llm_prompt = build_scene_to_image_prompt(
            scene, image_style=image_style,
            product_images=product_images, character_profiles=character_profiles,
        )
        gen_result = await _generate_image_with_transform(
            llm_prompt, scene, product_images, character_profiles,
            prompt_override=prompt_override,
            chat_provider=script_prov, chat_model=script_mdl,
            image_provider=img_prov, image_model=img_mdl,
        )
        new_url = gen_result["image_url"]
        new_prompt = gen_result["prompt_used"]
    elif prompt_override:
        new_url = await _call_image(prompt_override, provider=img_prov, model=img_mdl)
        new_prompt = prompt_override
    else:
        img_prompt = build_image_prompt(scene.get("visual_description", ""), image_style)
        new_url = await _call_image(img_prompt, provider=img_prov, model=img_mdl)
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


async def regenerate_storyboard_scenes(
    pipeline_id: str,
    scene_ids: list[int],
    prompt_override: str | None = None,
) -> dict:
    """Regenerate selected storyboard images without rerunning all scenes.

    并行触发，避免 N 段 × 单段耗时的串行累积。
    """
    unique_scene_ids = list(dict.fromkeys(int(sid) for sid in scene_ids))
    if not unique_scene_ids:
        return await get_pipeline(pipeline_id) or {}
    coros = [
        regenerate_storyboard_scene(pipeline_id, sid, prompt_override=prompt_override)
        for sid in unique_scene_ids
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    for sid, r in zip(unique_scene_ids, results):
        if isinstance(r, Exception):
            logger.warning("regenerate storyboard scene %s failed: %s", sid, r)
    final = await get_pipeline(pipeline_id)
    if not final:
        raise ValueError("Pipeline not found")
    return final


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
        script_prov, script_mdl = _stage_model(pipe, "script")
        video_prov, video_mdl = _stage_model(pipe, "video")
        video_tasks = []
        # N 张分镜图 → N-1 段视频。段 i 的 first=storyboard[i]，last=storyboard[i+1]。
        # 最后一个 scene 的图只作上一段的 last_frame，不再单独出视频。
        for i, scene in enumerate(scenes[:-1]):
            sb = sb_map.get(scene["scene_id"], {})
            storyboard_url = sb.get("image_url", "")
            next_sb = sb_map.get(scenes[i + 1]["scene_id"], {})
            last_frame_url = next_sb.get("image_url", "")
            dur = int(scene.get("duration", "5s").replace("s", ""))

            if use_enhanced:
                video_tasks.append((
                    scene["scene_id"],
                    _generate_video_with_transform(
                        scene, storyboard_url, dur,
                        last_frame_url=last_frame_url or None,
                        product_images=product_images,
                        character_profiles=character_profiles,
                        generate_audio=generate_audio,
                        ratio=video_ratio,
                        quality=video_quality,
                        chat_provider=script_prov, chat_model=script_mdl,
                        video_provider=video_prov, video_model=video_mdl,
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
                        provider=video_prov, model=video_mdl,
                        last_frame=last_frame_url or None,
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

        return await update_pipeline(
            pipeline_id,
            video_results=results,
            status="paused",
            error_message=None,
        )
    except Exception as exc:
        await update_pipeline(pipeline_id, status="failed", error_message=str(exc))
        raise


async def _generate_video_with_transform(
    scene: dict,
    storyboard_url: str,
    duration: int,
    *,
    last_frame_url: str | None = None,
    product_images: list[str] | None = None,
    character_profiles: list[dict] | None = None,
    generate_audio: bool = False,
    ratio: str = "16:9",
    quality: str = "standard",
    prompt_override: str | None = None,
    chat_provider: str | None = None,
    chat_model: str | None = None,
    video_provider: str | None = None,
    video_model: str | None = None,
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
        optimized_prompt = await _call_chat(
            llm_prompt, provider=chat_provider, model=chat_model,
            flywheel_node="content.scene_to_video",
            flywheel_scope={"scene_id": scene.get("scene_id")},
        )
        optimized_prompt = optimized_prompt.strip().strip('"').strip("'")

    ref_images = build_video_reference_images(
        scene,
        character_profiles=character_profiles,
        product_images=product_images,
    )
    typed_refs = build_typed_reference_images(
        scene,
        character_profiles=character_profiles,
        product_images=product_images,
    )

    result = await _call_video(
        optimized_prompt,
        duration=duration,
        provider=video_provider, model=video_model,
        first_frame=storyboard_url or None,
        last_frame=last_frame_url or None,
        reference_images=typed_refs or ref_images or None,
        generate_audio=generate_audio,
        ratio=ratio,
        quality=quality,
    )
    result["prompt_used"] = optimized_prompt
    result["reference_images_used"] = ref_images
    result["first_frame_used"] = storyboard_url
    result["last_frame_used"] = last_frame_url or ""
    return result


async def regenerate_video_scene(
    pipeline_id: str,
    scene_id: int,
    prompt_override: str | None = None,
    *,
    last_frame_scene_id: int | None = None,
    user_hint: str | None = None,
) -> dict:
    """Regenerate a single video scene.

    If prompt_override is given, skip LLM prompt transformation and use it directly.
    If user_hint is given (老板的修改意见), append it as a hard requirement to the prompt.
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

    # 老板的修改意见 → 升级为 prompt_override（拼到 visual_description 或已有 override 之后）
    if user_hint:
        hint_block = f"\n\n## 必须遵守的修改要求\n{user_hint}\n（这是用户对上一版的不满意点，新版必须按此调整）"
        if prompt_override:
            prompt_override = prompt_override + hint_block
        else:
            base = scene.get("visual_description", "")
            cam = scene.get("camera_movement", "")
            if cam:
                base += f"，运镜：{cam}"
            prompt_override = base + hint_block

    storyboard = pipe["storyboard_results"]
    if isinstance(storyboard, str):
        storyboard = json.loads(storyboard)
    sb = next((r for r in storyboard if r["scene_id"] == scene_id), {})
    last_sb = next((r for r in storyboard if r["scene_id"] == last_frame_scene_id), {}) if last_frame_scene_id else {}
    last_frame_url = last_sb.get("image_url") or ""

    config = pipe["config"] if isinstance(pipe["config"], dict) else json.loads(pipe["config"] or "{}")
    dur = int(scene.get("duration", "5s").replace("s", ""))

    product_images = pipe.get("product_images")
    if isinstance(product_images, str):
        product_images = json.loads(product_images)
    character_profiles = pipe.get("character_profiles")
    if isinstance(character_profiles, str):
        character_profiles = json.loads(character_profiles)

    script_prov, script_mdl = _stage_model(pipe, "script")
    video_prov, video_mdl = _stage_model(pipe, "video")

    if character_profiles or product_images:
        data = await _generate_video_with_transform(
            scene, sb.get("image_url", ""), dur,
            last_frame_url=last_frame_url,
            product_images=product_images,
            character_profiles=character_profiles,
            generate_audio=config.get("generate_audio", False),
            ratio=config.get("video_ratio", "16:9"),
            quality=config.get("video_quality", "standard"),
            prompt_override=prompt_override,
            chat_provider=script_prov, chat_model=script_mdl,
            video_provider=video_prov, video_model=video_mdl,
        )
    elif prompt_override:
        data = await _call_video(
            prompt_override, sb.get("image_url") or None, dur,
            provider=video_prov, model=video_mdl,
            last_frame=last_frame_url or None,
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
            provider=video_prov, model=video_mdl,
            last_frame=last_frame_url or None,
            generate_audio=config.get("generate_audio", False),
            ratio=config.get("video_ratio", "16:9"),
            quality=config.get("video_quality", "standard"),
        )
        data["prompt_used"] = prompt

    results = pipe["video_results"]
    if isinstance(results, str):
        results = json.loads(results)
    if not isinstance(results, list):
        results = []
    found = False
    for r in results:
        if r["scene_id"] == scene_id:
            r["task_id"] = data.get("task_id", "")
            r["status"] = data.get("status", "processing")
            r["video_url"] = data.get("video_url", "")
            r["prompt_used"] = data.get("prompt_used", "")
            r["reference_images_used"] = data.get("reference_images_used", [])
            r["first_frame_used"] = data.get("first_frame_used", "")
            r["last_frame_used"] = data.get("last_frame_used", last_frame_url)
            found = True
            break
    if not found:
        results.append({
            "scene_id": scene_id,
            "task_id": data.get("task_id", ""),
            "status": data.get("status", "processing"),
            "video_url": data.get("video_url", ""),
            "prompt_used": data.get("prompt_used", ""),
            "reference_images_used": data.get("reference_images_used", []),
            "first_frame_used": data.get("first_frame_used", sb.get("image_url", "")),
            "last_frame_used": data.get("last_frame_used", last_frame_url),
        })

    return await update_pipeline(pipeline_id, video_results=results)


async def regenerate_video_scenes(
    pipeline_id: str,
    scene_ids: list[int],
    prompt_override: str | None = None,
    *,
    use_next_scene_as_last_frame: bool = False,
    user_hint: str | None = None,
) -> dict:
    """Create/regenerate video tasks for selected scenes only.

    并行触发（asyncio.gather），单段 30s × 5 段 = 30s，而非串行 150s。
    user_hint 是老板对上一版的修改意见，会以"必须遵守"形式附加到 prompt。
    """
    unique_scene_ids = list(dict.fromkeys(int(sid) for sid in scene_ids))
    if not unique_scene_ids:
        return await get_pipeline(pipeline_id) or {}

    coros = [
        regenerate_video_scene(
            pipeline_id,
            sid,
            prompt_override=prompt_override,
            last_frame_scene_id=(sid + 1 if use_next_scene_as_last_frame else None),
            user_hint=user_hint,
        )
        for sid in unique_scene_ids
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    for sid, r in zip(unique_scene_ids, results):
        if isinstance(r, Exception):
            logger.warning("regenerate video scene %s failed: %s", sid, r)

    final = await get_pipeline(pipeline_id)
    if not final:
        raise ValueError("Pipeline not found")
    return final


# ──────────────────────────────────────────────
# Compose (FFmpeg)
# ──────────────────────────────────────────────

async def compose_final_video(pipeline_id: str) -> dict:
    pipe = await get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError("Pipeline not found")

    # 老板可选『跳过合成』——只要 10 段独立视频，自己拿去剪。
    if pipe.get("skip_final_concat"):
        logger.info("pipeline %s skip_final_concat=True; mark as completed without ffmpeg", pipeline_id)
        return await update_pipeline(
            pipeline_id,
            current_step="done",
            status="completed",
            error_message=None,
        )

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
