"""Digital human (Avatar) library service.

公开能力：
  - CRUD：create_digital_human / list_digital_humans / get_digital_human /
          update_digital_human / delete_digital_human
  - 生命周期：promote_digital_human / archive_digital_human
  - 投放飞轮回灌：update_metrics
  - AI 生成：generate_from_refs（基于参考图自动出多角度底图）
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import httpx

from app.config import settings
from app.database import get_pool

logger = logging.getLogger(__name__)


def _hub_image_url() -> str:
    return f"{settings.ai_provider_hub_url.rstrip('/')}/api/v1/ai/images/generate"


# ─────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────

async def create_digital_human(payload: dict) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO content_studio.digital_humans
        (name, seed_face_url, face_urls, gender, age_range, style_tags,
         identity_anchor, source_pipeline_id, source_scene_id, extra)
        VALUES ($1, $2, $3::jsonb, $4, $5, $6::jsonb, $7, $8, $9, $10::jsonb)
        RETURNING *
        """,
        payload["name"],
        payload["seed_face_url"],
        json.dumps(payload.get("face_urls") or [payload["seed_face_url"]], ensure_ascii=False),
        payload.get("gender"),
        payload.get("age_range"),
        json.dumps(payload.get("style_tags") or [], ensure_ascii=False),
        payload.get("identity_anchor"),
        uuid.UUID(payload["source_pipeline_id"]) if payload.get("source_pipeline_id") else None,
        payload.get("source_scene_id"),
        json.dumps(payload.get("extra") or {}, ensure_ascii=False),
    )
    return dict(row)


async def list_digital_humans(
    limit: int = 50,
    offset: int = 0,
    *,
    status: str | None = None,
    sort: str = "ctr",
) -> list[dict]:
    pool = get_pool()
    where = []
    args: list = []
    if status:
        args.append(status)
        where.append(f"status = ${len(args)}")

    order = {
        "ctr": "ctr_avg DESC",
        "cvr": "cvr_avg DESC",
        "quality": "quality_score DESC",
        "recent": "updated_at DESC",
    }.get(sort, "ctr_avg DESC")

    sql = "SELECT * FROM content_studio.digital_humans"
    if where:
        sql += " WHERE " + " AND ".join(where)
    args.extend([limit, offset])
    sql += f" ORDER BY {order} NULLS LAST, created_at DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def get_digital_human(dh_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM content_studio.digital_humans WHERE id = $1",
        uuid.UUID(dh_id),
    )
    return dict(row) if row else None


async def update_digital_human(dh_id: str, payload: dict) -> dict | None:
    pool = get_pool()
    current = await get_digital_human(dh_id)
    if not current:
        return None
    row = await pool.fetchrow(
        """
        UPDATE content_studio.digital_humans
        SET name = $1,
            seed_face_url = $2,
            face_urls = $3::jsonb,
            gender = $4,
            age_range = $5,
            style_tags = $6::jsonb,
            identity_anchor = $7,
            status = $8,
            extra = $9::jsonb,
            updated_at = NOW()
        WHERE id = $10
        RETURNING *
        """,
        payload.get("name", current["name"]),
        payload.get("seed_face_url", current["seed_face_url"]),
        json.dumps(payload.get("face_urls", current.get("face_urls") or []), ensure_ascii=False),
        payload.get("gender", current.get("gender")),
        payload.get("age_range", current.get("age_range")),
        json.dumps(payload.get("style_tags", current.get("style_tags") or []), ensure_ascii=False),
        payload.get("identity_anchor", current.get("identity_anchor")),
        payload.get("status", current.get("status")),
        json.dumps(payload.get("extra", current.get("extra") or {}), ensure_ascii=False),
        uuid.UUID(dh_id),
    )
    return dict(row) if row else None


async def delete_digital_human(dh_id: str) -> bool:
    pool = get_pool()
    current = await get_digital_human(dh_id)
    if not current:
        return False
    # 仅 draft / archived 允许硬删
    status = current.get("status") or "active"
    if status not in ("draft", "archived"):
        raise ValueError(f"refuse to delete avatar in status='{status}', archive it first")

    result = await pool.execute(
        "DELETE FROM content_studio.digital_humans WHERE id = $1",
        uuid.UUID(dh_id),
    )
    return result == "DELETE 1"


# ─────────────────────────────────────────────────────────
# 生命周期
# ─────────────────────────────────────────────────────────

_VALID_STATUSES = ("draft", "active", "testing", "approved", "promoted", "archived")
_APPROVED_LIKE = {"approved", "promoted"}  # 兼容历史"promoted"枚举值


def is_approved_like(status: str | None) -> bool:
    return (status or "").lower() in _APPROVED_LIKE


async def promote_digital_human(dh_id: str, to_status: str | None = None) -> dict | None:
    """手动晋级：默认走 draft → testing → approved（PRD 标准命名）。

    历史 promoted 视同 approved。
    """
    pool = get_pool()
    current = await get_digital_human(dh_id)
    if not current:
        return None

    cur = (current.get("status") or "draft").lower()
    if to_status:
        target = to_status.lower()
    else:
        target = {
            "draft": "testing",
            "testing": "approved",
            "active": "approved",
            "promoted": "approved",
            "approved": "approved",
            "archived": "active",
        }.get(cur, "approved")
    if target not in _VALID_STATUSES:
        raise ValueError(f"invalid target status: {target}")

    row = await pool.fetchrow(
        "UPDATE content_studio.digital_humans SET status = $1, updated_at = NOW() WHERE id = $2 RETURNING *",
        target, uuid.UUID(dh_id),
    )
    return dict(row) if row else None


async def archive_digital_human(dh_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE content_studio.digital_humans SET status = 'archived', updated_at = NOW() WHERE id = $1 RETURNING *",
        uuid.UUID(dh_id),
    )
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────
# 飞轮指标回灌
# ─────────────────────────────────────────────────────────

async def update_metrics(
    dh_id: str,
    *,
    ctr: float | None = None,
    cvr: float | None = None,
    samples: int = 1,
    quality_score: float | None = None,
) -> dict | None:
    pool = get_pool()
    current = await get_digital_human(dh_id)
    if not current:
        return None

    n_old = int(current.get("usage_count") or 0)
    n_new = n_old + max(samples, 1)

    def _avg(old: float | None, new: float | None) -> float:
        old_v = float(old or 0)
        if new is None:
            return old_v
        return (old_v * n_old + float(new) * samples) / n_new

    new_ctr = _avg(current.get("ctr_avg"), ctr)
    new_cvr = _avg(current.get("cvr_avg"), cvr)
    quality = float(quality_score) if quality_score is not None else float(current.get("quality_score") or 0)

    status = current.get("status") or "active"
    if (
        status in ("active", "testing", "draft")
        and n_new >= settings.avatar_promote_min_samples
        and new_ctr >= settings.avatar_promote_min_ctr
    ):
        status = "approved"

    extra = current.get("extra") or {}
    if isinstance(extra, str):
        extra = json.loads(extra)
    low_streak = int(extra.get("consecutive_low") or 0)
    if ctr is not None and ctr < settings.avatar_promote_min_ctr * 0.5:
        low_streak += 1
    elif ctr is not None:
        low_streak = 0
    extra["consecutive_low"] = low_streak
    if low_streak >= settings.avatar_archive_consecutive_low:
        status = "archived"

    row = await pool.fetchrow(
        """
        UPDATE content_studio.digital_humans
        SET ctr_avg = $1,
            cvr_avg = $2,
            quality_score = $3,
            usage_count = $4,
            status = $5,
            extra = $6::jsonb,
            updated_at = NOW()
        WHERE id = $7
        RETURNING *
        """,
        new_ctr,
        new_cvr,
        quality,
        n_new,
        status,
        json.dumps(extra, ensure_ascii=False),
        uuid.UUID(dh_id),
    )
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────
# AI 生成多角度底图
# ─────────────────────────────────────────────────────────

_DEFAULT_ANGLE_PROMPTS: dict[str, str] = {
    "front": "正面半身肖像，平视镜头，五官完整清晰居中，自然表情轻微微笑，肩膀放松",
    "45": "45 度侧脸半身肖像，脸部斜对镜头，眼神看向镜头侧前方，微微抬头，五官轮廓立体",
    "side": "90 度完整侧脸半身肖像，脸部侧对镜头，鼻梁和下颌线清晰，眼神看向侧前方",
    "half_body": "半身全景，从腰部以上拍摄，正面平视，展示上身身形比例与日常穿搭，手臂自然垂放",
}


async def generate_from_refs(
    *,
    name: str,
    appearance_desc: str = "",
    reference_images: list[str] | None = None,
    angles: tuple[str, ...] = ("front", "45", "side", "half_body"),
    gender: str | None = None,
    age_range: str | None = None,
    style_tags: list[str] | None = None,
    identity_anchor: str | None = None,
) -> dict:
    """基于参考图 + 人设描述，并发生成多角度底图，落库为 draft Avatar。"""
    refs = [r for r in (reference_images or []) if r]
    if not appearance_desc and not refs:
        raise ValueError("appearance_desc 或 reference_images 至少需要其一")

    base_desc = appearance_desc.strip() or "数字人形象"
    # 使用正向措辞而非反向提示（"无 AI 痕迹" 这类反向提示对部分模型会反向起作用）。
    style_hint = (
        "手机竖屏摄影质感，自然日光，纯色浅色干净背景，五官清晰立体，"
        "皮肤纹理真实自然，普通人像摄影风格，photorealistic"
    )

    typed_refs: list[dict] = [
        {"url": url, "type": "character", "weight": 1.0 if i == 0 else 0.7}
        for i, url in enumerate(refs[:4])
    ]

    async def _gen_one(angle: str) -> tuple[str, str]:
        angle_hint = _DEFAULT_ANGLE_PROMPTS.get(angle, angle)
        prompt = (
            f"{base_desc}。{angle_hint}。{style_hint}。"
            "保持五官、发型、肤色与参考图完全一致。"
        )
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    _hub_image_url(),
                    json={
                        "prompt": prompt,
                        "size": "1024x1024",
                        "quality": "high",
                        "n": 1,
                        "reference_images": typed_refs or None,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            images = data.get("images") or []
            return angle, (images[0].get("url", "") if images else "")
        except Exception as exc:
            logger.warning("avatar gen %s failed: %s", angle, exc)
            return angle, ""

    pairs = await asyncio.gather(*(_gen_one(a) for a in angles))
    face_urls = [u for _, u in pairs if u]

    if not face_urls:
        # 兜底：直接采用参考图
        face_urls = refs[:4]
    if not face_urls:
        raise RuntimeError("无法生成任何底图（请检查参考图或 image provider 配置）")

    seed_face_url = face_urls[0]
    payload = {
        "name": name,
        "seed_face_url": seed_face_url,
        "face_urls": face_urls,
        "gender": gender,
        "age_range": age_range,
        "style_tags": style_tags or [],
        "identity_anchor": identity_anchor or appearance_desc[:200],
        "extra": {
            "ai_generated": True,
            "angles": list(angles),
            "reference_images": refs,
        },
    }
    avatar = await create_digital_human(payload)
    avatar.setdefault("status", "draft")
    return avatar


async def list_pipelines_using(avatar_id: str) -> list[dict]:
    """所有用过该 Avatar 的 pipelines。"""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, title, status, current_step, brief_id, product_id,
               created_at, updated_at
        FROM content_studio.pipelines
        WHERE digital_human_id = $1
        ORDER BY created_at DESC
        LIMIT 200
        """,
        uuid.UUID(avatar_id),
    )
    return [dict(r) for r in rows]


async def promote_from_pipeline(
    pipeline_id: str,
    character_name: str,
    new_avatar_name: str,
) -> dict | None:
    """把现有 pipeline 中某个角色"另存为 Avatar"。"""
    pool = get_pool()
    pipe = await pool.fetchrow(
        "SELECT id, character_profiles FROM content_studio.pipelines WHERE id = $1",
        uuid.UUID(pipeline_id),
    )
    if not pipe:
        return None
    profiles = pipe["character_profiles"]
    if isinstance(profiles, str):
        profiles = json.loads(profiles)
    if not profiles:
        return None
    profile = next((p for p in profiles if p.get("name") == character_name), None)
    if not profile or not profile.get("face_url"):
        return None
    payload = {
        "name": new_avatar_name,
        "seed_face_url": profile["face_url"],
        "face_urls": [profile["face_url"]],
        "gender": profile.get("gender"),
        "age_range": profile.get("age_range"),
        "identity_anchor": profile.get("appearance"),
        "source_pipeline_id": str(pipe["id"]),
    }
    return await create_digital_human(payload)
