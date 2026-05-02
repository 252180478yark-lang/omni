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


def _avg_metric(materials: list[dict[str, Any]], key: str) -> float | None:
    values: list[float] = []
    for m in materials or []:
        v = m.get(key)
        if v is None:
            continue
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return sum(values) / len(values)


async def _resolve_pipeline_targets(
    pipeline_id: str,
    client: httpx.AsyncClient,
) -> tuple[str | None, str | None]:
    """通过 knowledge-engine 查 pipeline，提取 brief_id / digital_human_id。"""
    try:
        r = await client.get(
            f"{KE_BASE}/api/v1/content-studio/pipeline/{pipeline_id}",
        )
        if r.status_code != 200:
            return None, None
        data = r.json()
        return (
            data.get("brief_id") or None,
            data.get("digital_human_id") or None,
        )
    except Exception:
        return None, None


async def sync_review_to_brief_and_avatar(
    campaign: dict[str, Any],
    materials: list[dict[str, Any]],
    review_summary: str,
) -> dict[str, Any]:
    """复盘完成后将 ctr/cvr 回灌到 brief / digital_human。

    回灌路径优先级：
      1) campaign.brief_id / campaign.digital_human_id（显式挂载）
      2) materials[i].pipeline_id → 通过 ke 反查 pipeline.brief_id / pipeline.digital_human_id
         按 pipeline 聚合该 pipeline 内素材的 ctr/cvr 后回灌
    任一路径都没目标则返回 skipped，前端据此提示用户补绑定。
    """
    cmp_brief_id = campaign.get("brief_id")
    cmp_dh_id = campaign.get("digital_human_id")
    summary_clipped = (review_summary or "")[:1000]

    # 按 material 聚合到 pipeline（去重 pipeline_id）
    by_pipeline: dict[str, list[dict[str, Any]]] = {}
    for m in materials or []:
        pid = m.get("pipeline_id")
        if not pid:
            continue
        by_pipeline.setdefault(str(pid), []).append(m)

    if not (cmp_brief_id or cmp_dh_id or by_pipeline):
        return {
            "skipped": True,
            "reason": "no_pipeline_binding",
            "missing_binding": True,
            "message": "当前批次没有绑定 Brief / Avatar，也没有素材绑定 Pipeline，无法回灌 CTR/CVR。请在批次详情为素材补绑定 Pipeline。",
        }

    result: dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # ── 路径 1：campaign 级 ──
        if cmp_brief_id or cmp_dh_id:
            ctr = _avg_metric(materials, "ctr")
            cvr = _avg_metric(materials, "conversion_rate")
            samples = sum(1 for m in materials or [] if m.get("ctr") is not None)
            result["campaign_level"] = {
                "ctr": ctr, "cvr": cvr, "samples": samples,
                "brief_id": cmp_brief_id, "digital_human_id": cmp_dh_id,
            }
            if cmp_brief_id:
                try:
                    r = await client.patch(
                        f"{KE_BASE}/api/v1/content-studio/briefs/{cmp_brief_id}/metrics",
                        json={"ctr": ctr, "cvr": cvr, "samples": samples, "review_summary": summary_clipped},
                    )
                    result["campaign_level"]["brief_status"] = r.status_code
                except Exception as exc:
                    logger.warning("brief metrics sync (campaign) failed: %s", exc)
                    result["campaign_level"]["brief_status"] = "error"
            if cmp_dh_id:
                try:
                    r = await client.patch(
                        f"{KE_BASE}/api/v1/content-studio/digital-humans/{cmp_dh_id}/metrics",
                        json={"ctr": ctr, "cvr": cvr, "samples": max(samples, 1)},
                    )
                    result["campaign_level"]["dh_status"] = r.status_code
                except Exception as exc:
                    logger.warning("dh metrics sync (campaign) failed: %s", exc)
                    result["campaign_level"]["dh_status"] = "error"

        # ── 路径 2：material → pipeline → brief/avatar ──
        material_results: list[dict[str, Any]] = []
        unresolved_pipelines: list[str] = []
        for pid, mats in by_pipeline.items():
            brief_id, dh_id = await _resolve_pipeline_targets(pid, client)
            if not (brief_id or dh_id):
                unresolved_pipelines.append(pid)
                continue
            ctr_p = _avg_metric(mats, "ctr")
            cvr_p = _avg_metric(mats, "conversion_rate")
            samples_p = sum(1 for m in mats if m.get("ctr") is not None)
            entry: dict[str, Any] = {
                "pipeline_id": pid, "brief_id": brief_id, "digital_human_id": dh_id,
                "ctr": ctr_p, "cvr": cvr_p, "samples": samples_p,
            }
            # 跳过已经在 campaign 级别灌过的同一目标，避免重复
            if brief_id and brief_id != cmp_brief_id:
                try:
                    r = await client.patch(
                        f"{KE_BASE}/api/v1/content-studio/briefs/{brief_id}/metrics",
                        json={"ctr": ctr_p, "cvr": cvr_p, "samples": samples_p, "review_summary": summary_clipped},
                    )
                    entry["brief_status"] = r.status_code
                except Exception as exc:
                    logger.warning("brief metrics sync (material) failed: %s", exc)
                    entry["brief_status"] = "error"
            if dh_id and dh_id != cmp_dh_id:
                try:
                    r = await client.patch(
                        f"{KE_BASE}/api/v1/content-studio/digital-humans/{dh_id}/metrics",
                        json={"ctr": ctr_p, "cvr": cvr_p, "samples": max(samples_p, 1)},
                    )
                    entry["dh_status"] = r.status_code
                except Exception as exc:
                    logger.warning("dh metrics sync (material) failed: %s", exc)
                    entry["dh_status"] = "error"
            material_results.append(entry)

        if material_results:
            result["material_level"] = material_results
        if unresolved_pipelines and ("campaign_level" in result or material_results):
            result["unresolved_pipelines"] = unresolved_pipelines

    if "campaign_level" in result or "material_level" in result:
        return result
    return {
        "skipped": True,
        "reason": "pipeline_without_brief_or_avatar",
        "missing_binding": True,
        "message": "素材已绑定 Pipeline，但这些 Pipeline 没有关联 Brief / Avatar，无法回灌指标。请回到内容工坊或新建向导补齐绑定。",
        "pipeline_ids": list(by_pipeline.keys()),
    }


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
