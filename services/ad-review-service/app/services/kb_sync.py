"""复盘日志同步到知识引擎（ingest + 轮询 document_id）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

KE_BASE = settings.knowledge_engine_url.rstrip("/")
REVIEW_KB_NAME = "投放复盘经验库"


async def ensure_review_kb() -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{KE_BASE}/api/v1/knowledge/bases")
        resp.raise_for_status()
        body = resp.json()
        kbs = body.get("data") or []
        existing = next((kb for kb in kbs if kb.get("name") == REVIEW_KB_NAME), None)
        if existing:
            return str(existing["id"])

        create_resp = await client.post(
            f"{KE_BASE}/api/v1/knowledge/bases",
            json={
                "name": REVIEW_KB_NAME,
                "description": "投放复盘日志自动沉淀，包含历史投放数据分析、优化经验、素材效果对比等",
            },
        )
        create_resp.raise_for_status()
        created = create_resp.json().get("data") or {}
        if not created.get("id"):
            raise RuntimeError("创建知识库失败：未返回 id")
        return str(created["id"])


async def _wait_task_document(client: httpx.AsyncClient, task_id: str, timeout: float = 45.0) -> str | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        r = await client.get(f"{KE_BASE}/api/v1/knowledge/tasks/{task_id}")
        if r.status_code != 200:
            await asyncio.sleep(0.4)
            continue
        try:
            task = r.json().get("data") or {}
        except Exception:
            await asyncio.sleep(0.4)
            continue
        status = task.get("status")
        doc_id = task.get("document_id")
        if status == "succeeded" and doc_id:
            return str(doc_id)
        if status == "failed":
            logger.error("ingest task failed: %s", task.get("error"))
            return None
        await asyncio.sleep(0.4)
    return None


async def sync_review_to_kb(
    review_log: dict[str, Any],
    campaign: dict[str, Any],
    experience_tags: list[str],
) -> tuple[str, str | None]:
    kb_id = await ensure_review_kb()
    product_name = campaign.get("product_name", "")
    title = f"投放复盘-{product_name}-{campaign['start_date']}~{campaign['end_date']}"

    metadata_header = (
        "---\n"
        f"type: 投放复盘\n"
        f"product: {product_name}\n"
        f"period: {campaign['start_date']}~{campaign['end_date']}\n"
        f"total_cost: {campaign.get('total_cost')}\n"
        f"tags: {', '.join(experience_tags)}\n"
        "---\n\n"
    )
    content = metadata_header + (review_log.get("content_md") or "")

    async with httpx.AsyncClient(timeout=120.0) as client:
        old_doc = review_log.get("kb_document_id")
        if old_doc:
            try:
                await client.delete(f"{KE_BASE}/api/v1/knowledge/documents/{old_doc}")
            except Exception:
                pass

        ingest_resp = await client.post(
            f"{KE_BASE}/api/v1/knowledge/ingest",
            json={
                "kb_id": kb_id,
                "title": title,
                "text": content,
                "source_type": "ad_review",
            },
        )
        if ingest_resp.status_code not in (200, 202):
            detail = ingest_resp.text[:500]
            raise RuntimeError(f"知识库写入失败: {ingest_resp.status_code} {detail}")

        ingest_body = ingest_resp.json()
        data = ingest_body.get("data") or {}
        task_id = data.get("task_id")
        if not task_id:
            raise RuntimeError("知识库未返回 task_id")

        document_id = await _wait_task_document(client, str(task_id))
        return kb_id, document_id
