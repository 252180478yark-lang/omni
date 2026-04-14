from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from app.database import get_pool
from app.schemas import ReviewLogUpdate
from app.services.kb_sync import sync_review_to_kb
from app.services.review_engine import generate_review
from app.config import settings

router = APIRouter(prefix="/api/v1/ad-review/campaigns", tags=["ad-review-review"])

TAG_RE = re.compile(r"#[\w\u4e00-\u9fff\-]+")
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)


def _parse_tags(md: str) -> list[str]:
    return sorted(set(TAG_RE.findall(md or "")))


def _extract_suggestions_json(md: str) -> list | None:
    """Extract the last ```json``` code block and return it if it looks like suggestions."""
    blocks = _JSON_BLOCK_RE.findall(md or "")
    if not blocks:
        return None
    raw = blocks[-1].strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, list) and data and isinstance(data[0], dict) and "material_name" in data[0]:
        return data
    return None


async def _load_review_context(campaign_id: str) -> tuple[dict, list, list, list]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow(
            """
            SELECT c.*, p.name AS product_name, p.sku AS product_sku,
                   p.price AS product_price, p.margin_rate AS product_margin_rate
            FROM ad_review.campaigns c
            JOIN ad_review.products p ON p.id = c.product_id
            WHERE c.id = $1::uuid
            """,
            campaign_id,
        )
        if not camp:
            raise HTTPException(status_code=404, detail="批次不存在")
        audiences = await conn.fetch(
            "SELECT * FROM ad_review.audience_packs WHERE campaign_id = $1::uuid ORDER BY created_at",
            campaign_id,
        )
        materials = await conn.fetch(
            "SELECT * FROM ad_review.materials WHERE campaign_id = $1::uuid ORDER BY created_at",
            campaign_id,
        )
        groups = await conn.fetch(
            "SELECT * FROM ad_review.material_groups WHERE campaign_id = $1::uuid ORDER BY created_at",
            campaign_id,
        )

    aud_list: list[dict[str, Any]] = []
    for a in audiences:
        d = dict(a)
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except json.JSONDecodeError:
                d["tags"] = []
        aud_list.append(d)

    mat_list = [dict(m) for m in materials]
    grp_list = [dict(g) for g in groups]
    cdict = dict(camp)
    return cdict, aud_list, mat_list, grp_list


@router.post("/{campaign_id}/generate-review")
async def generate_review_sse(
    campaign_id: str,
    replace: bool = Query(False, description="为 true 时覆盖已有复盘"),
    kb_ids: str = Query("", description="逗号分隔的知识库ID列表"),
):
    kb_id_list = [x.strip() for x in kb_ids.split(",") if x.strip()] if kb_ids else None
    async def event_gen() -> AsyncIterator[dict[str, str]]:
        try:
            campaign, audiences, materials, groups = await _load_review_context(campaign_id)
        except HTTPException as e:
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "content": e.detail}, ensure_ascii=False),
            }
            return

        if not audiences:
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "content": "请先添加人群包"}, ensure_ascii=False),
            }
            return
        if not materials:
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "content": "请先导入素材 CSV"}, ensure_ascii=False),
            }
            return

        prev_suggestions = None
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                prev_review = await conn.fetchrow(
                    "SELECT ai_suggestions FROM ad_review.review_logs WHERE campaign_id = $1::uuid ORDER BY updated_at DESC LIMIT 1",
                    campaign_id,
                )
            if prev_review and prev_review["ai_suggestions"]:
                raw = prev_review["ai_suggestions"]
                prev_suggestions = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass

        buf: list[str] = []
        try:
            async for chunk in generate_review(campaign, audiences, materials, groups, prev_suggestions=prev_suggestions, kb_ids=kb_id_list):
                buf.append(chunk)
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False),
                }
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False),
            }
            return

        full_md = "".join(buf)
        tags = _parse_tags(full_md)
        suggestions = _extract_suggestions_json(full_md)
        rid = uuid.uuid4()
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if replace:
                        await conn.execute(
                            "UPDATE ad_review.campaigns SET review_log_id = NULL WHERE id = $1::uuid",
                            campaign_id,
                        )
                        await conn.execute(
                            "DELETE FROM ad_review.review_logs WHERE campaign_id = $1::uuid",
                            campaign_id,
                        )
                    await conn.execute(
                        """
                        INSERT INTO ad_review.review_logs
                          (id, campaign_id, content_md, experience_tags, generation_model, is_edited, ai_suggestions)
                        VALUES ($1::uuid, $2::uuid, $3, $4::jsonb, $5, FALSE, $6::jsonb)
                        """,
                        rid,
                        campaign_id,
                        full_md,
                        json.dumps(tags),
                        settings.review_model,
                        json.dumps(suggestions) if suggestions else None,
                    )
                    await conn.execute(
                        """
                        UPDATE ad_review.campaigns SET
                          review_log_id = $2::uuid,
                          status = 'reviewed',
                          updated_at = NOW()
                        WHERE id = $1::uuid
                        """,
                        campaign_id,
                        rid,
                    )
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "content": f"保存失败: {e!s}"}, ensure_ascii=False),
            }
            return

        yield {
            "event": "message",
            "data": json.dumps({"type": "done", "review_log_id": str(rid), "content": ""}, ensure_ascii=False),
        }

    return EventSourceResponse(event_gen())


@router.get("/{campaign_id}/review")
async def get_review(campaign_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM ad_review.review_logs
            WHERE campaign_id = $1::uuid
            ORDER BY updated_at DESC LIMIT 1
            """,
            campaign_id,
        )
        if not row:
            return {"review_log": None}
        d = dict(row)
        if isinstance(d.get("experience_tags"), str):
            try:
                d["experience_tags"] = json.loads(d["experience_tags"])
            except json.JSONDecodeError:
                d["experience_tags"] = []
        return {"review_log": d}


@router.put("/{campaign_id}/review")
async def update_review(campaign_id: str, body: ReviewLogUpdate):
    pool = await get_pool()
    tags = body.experience_tags if body.experience_tags else _parse_tags(body.content_md)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM ad_review.review_logs WHERE campaign_id = $1::uuid ORDER BY updated_at DESC LIMIT 1",
            campaign_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="尚无复盘日志，请先生成")
        rid = row["id"]
        await conn.execute(
            """
            UPDATE ad_review.review_logs SET
              content_md = $2,
              experience_tags = $3::jsonb,
              is_edited = TRUE,
              updated_at = NOW()
            WHERE id = $1::uuid
            """,
            rid,
            body.content_md,
            json.dumps(tags),
        )
        await conn.execute(
            "UPDATE ad_review.campaigns SET status = 'reviewed', updated_at = NOW() WHERE id = $1::uuid",
            campaign_id,
        )
    return {"ok": True}


@router.post("/{campaign_id}/review/sync-kb")
async def sync_kb(campaign_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow(
            """
            SELECT c.*, p.name AS product_name
            FROM ad_review.campaigns c
            JOIN ad_review.products p ON p.id = c.product_id
            WHERE c.id = $1::uuid
            """,
            campaign_id,
        )
        log = await conn.fetchrow(
            "SELECT * FROM ad_review.review_logs WHERE campaign_id = $1::uuid ORDER BY updated_at DESC LIMIT 1",
            campaign_id,
        )
        if not camp or not log:
            raise HTTPException(status_code=400, detail="请先保存复盘日志")

    review_log = dict(log)
    if isinstance(review_log.get("experience_tags"), str):
        try:
            review_log["experience_tags"] = json.loads(review_log["experience_tags"])
        except json.JSONDecodeError:
            review_log["experience_tags"] = []
    tags = review_log.get("experience_tags") or []
    if isinstance(tags, list):
        tag_strs = [str(t) for t in tags]
    else:
        tag_strs = []

    campaign = dict(camp)
    try:
        kb_id, doc_id = await sync_review_to_kb(review_log, campaign, tag_strs)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail="知识库服务不可用，请稍后重试。",
        ) from e

    async with pool.acquire() as conn:
        rid = review_log["id"]
        if doc_id:
            await conn.execute(
                """
                UPDATE ad_review.review_logs SET
                  kb_id = $2::uuid,
                  kb_document_id = $3::uuid,
                  kb_synced_at = NOW(),
                  updated_at = NOW()
                WHERE id = $1::uuid
                """,
                rid,
                kb_id,
                doc_id,
            )
        else:
            await conn.execute(
                """
                UPDATE ad_review.review_logs SET
                  kb_id = $2::uuid,
                  kb_synced_at = NOW(),
                  updated_at = NOW()
                WHERE id = $1::uuid
                """,
                rid,
                kb_id,
            )

    return {"ok": True, "kb_id": kb_id, "document_id": doc_id}
