"""Brief CRUD + KB dual-write + LLM-driven draft generation.

A Brief is the structured snapshot of a content strategy:
  USP（卖点）+ scenarios（场景）+ audience_profile（人群画像）+ tone_style（口播口吻）

Public functions
----------------
- create_brief / list_briefs / get_brief / update_brief / delete_brief
- derive_brief                 派生 v2，沿袭 parent_brief_id
- update_dmp_sop               把 chat 里得到的 SOP 文本回填到 brief
- update_metrics               飞轮回灌
- generate_draft               LLM + 三 KB 联合召回，给定产品+提示，一键产出 Brief 草稿
"""

from __future__ import annotations

import json
import logging
import re
import uuid

import httpx

from app.config import settings
from app.database import get_pool
from app.services.prompt_commons import (
    JSON_OUTPUT_DISCIPLINE,
    KB_AS_CREATIVE_MATERIAL,
    NO_AI_SLANG,
    format_kb_snippets,
)
from app.services.prompt_rules import log_feedback, render_rules_suffix

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 配置 & 内部工具
# ─────────────────────────────────────────────────────────

def _hub_chat_url() -> str:
    return f"{settings.ai_provider_hub_url.rstrip('/')}/api/v1/ai/chat"


def _ad_review_base() -> str:
    return settings.ad_review_service_url.rstrip("/")


def _knowledge_ingest_url() -> str:
    return f"http://localhost:{settings.service_port}/api/v1/knowledge/ingest"


def _kb_writer_id() -> str | None:
    """返回 brief 应写入的 KB id；若都未配置则返回 None。"""
    explicit = (settings.content_pipeline_kb_brief_writer or "").strip()
    if explicit:
        return explicit
    legacy = (settings.content_pipeline_kb_ids or "").strip()
    if legacy:
        return legacy.split(",")[0].strip() or None
    return None


def _tri_kb_ids() -> dict[str, str]:
    return {
        "ocean_engine": (settings.content_pipeline_kb_ocean_engine or "").strip(),
        "audience_report": (settings.content_pipeline_kb_audience_report or "").strip(),
        "content_strategy": (settings.content_pipeline_kb_content_strategy or "").strip(),
    }


def _brief_to_markdown(payload: dict) -> str:
    """渲染整份 Brief 为 Markdown，供 KB 入库与 chat 注入。"""
    scenarios = payload.get("scenarios") or []
    audience = payload.get("audience_profile") or {}
    tone = payload.get("tone_style") or {}
    extra = payload.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}

    parts: list[str] = []
    parts.append(f"# Brief: {payload.get('title', '未命名 Brief')}\n")
    if payload.get("product_name"):
        parts.append(f"> 产品：{payload['product_name']}  版本：v{payload.get('version', 1)}")
    if payload.get("parent_brief_id"):
        parts.append(f"> 派生自：{payload['parent_brief_id']}")
    parts.append("")

    parts.append("## 独特卖点 (USP)")
    usp_raw = payload.get("usp", "") or ""
    # 兼容三种格式：纯字符串 / 带换行的多条 / extra.usp_structured: [{point, evidence}]
    structured = extra.get("usp_structured")
    if structured and isinstance(structured, list):
        for i, item in enumerate(structured, 1):
            if not isinstance(item, dict):
                parts.append(f"{i}. {item}")
                continue
            point = item.get("point", "")
            evidence = item.get("evidence", "")
            line = f"{i}. **{point}**"
            if evidence:
                line += f"  — 依据：{evidence}"
            parts.append(line)
    elif usp_raw:
        parts.append(usp_raw)
    else:
        parts.append("—")
    parts.append("")

    parts.append("## 场景矩阵")
    if scenarios:
        for s in scenarios:
            if isinstance(s, dict):
                ctx = s.get("context") or s.get("scene") or ""
                trigger = s.get("trigger", "")
                pain = s.get("pain", "")
                evidence = s.get("evidence", "")
                line = f"- **{ctx}**"
                if trigger:
                    line += f"（触发：{trigger}）"
                if pain:
                    line += f" 痛点：{pain}"
                if evidence:
                    line += f"  — 依据：{evidence}"
                parts.append(line)
            else:
                parts.append(f"- {s}")
    else:
        parts.append("—")
    parts.append("")

    parts.append("## 目标人群")
    if audience:
        tags = audience.get("tags") or {}
        if tags:
            parts.append("- 标签：" + json.dumps(tags, ensure_ascii=False))
        insights = audience.get("insights") or {}
        if insights.get("motivation"):
            parts.append(f"- 动机：{insights['motivation']}")
        if insights.get("objection"):
            parts.append(f"- 反对意见：{insights['objection']}")
        if insights.get("language_style"):
            parts.append(f"- 语言风格：{insights['language_style']}")
        if audience.get("dmp_sop") or payload.get("dmp_sop"):
            sop = audience.get("dmp_sop") or payload.get("dmp_sop")
            parts.append("\n### 圈包 SOP\n" + (sop or "—"))
    else:
        parts.append("—")
    parts.append("")

    parts.append("## 口播口吻")
    if tone:
        parts.append("```json")
        parts.append(json.dumps(tone, ensure_ascii=False, indent=2))
        parts.append("```")
    else:
        parts.append("—")
    parts.append("")

    if payload.get("source_notes"):
        parts.append("## 备注\n" + payload["source_notes"])

    history = extra.get("review_history") or []
    if history:
        parts.append("\n## 投放效果日志")
        for h in history[-5:]:
            ctr = h.get("ctr")
            cvr = h.get("cvr")
            samples = h.get("samples")
            summary = (h.get("summary") or "").strip().splitlines()[0:2]
            parts.append(f"- ctr={ctr} cvr={cvr} samples={samples} | {' '.join(summary)}")

    return "\n".join(parts).rstrip() + "\n"


async def _ingest_brief_to_kb(brief: dict, *, replace_doc_id: str | None = None) -> str | None:
    """把 brief markdown 写入 KB（whole document）。返回 document_id 或 None。"""
    kb_id = _kb_writer_id()
    if not kb_id:
        return None

    try:
        kb_uuid = str(uuid.UUID(kb_id))
    except ValueError:
        logger.warning("Invalid brief KB id %s", kb_id)
        return None

    md = _brief_to_markdown(brief)
    title = f"[brief]{brief.get('title', '')[:80]}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if replace_doc_id:
                try:
                    await client.delete(
                        f"http://localhost:{settings.service_port}/api/v1/knowledge/documents/{replace_doc_id}"
                    )
                except Exception as exc:
                    logger.debug("brief KB doc delete %s: %s", replace_doc_id, exc)

            resp = await client.post(
                _knowledge_ingest_url(),
                json={
                    "kb_id": kb_uuid,
                    "title": title,
                    "text": md,
                    "source_type": "brief",
                },
            )
            if resp.status_code not in (200, 202):
                logger.warning("brief ingest %s failed: %s", brief.get("id"), resp.text[:200])
                return None
            data = resp.json().get("data") or {}
            task_id = data.get("task_id")
            if not task_id:
                return None

            import asyncio
            for _ in range(30):
                await asyncio.sleep(0.5)
                tr = await client.get(
                    f"http://localhost:{settings.service_port}/api/v1/knowledge/tasks/{task_id}"
                )
                if tr.status_code != 200:
                    continue
                payload = tr.json().get("data") or {}
                if payload.get("status") == "succeeded" and payload.get("document_id"):
                    return str(payload["document_id"])
                if payload.get("status") == "failed":
                    logger.warning("brief ingest task failed: %s", payload.get("error"))
                    return None
    except Exception as exc:
        logger.warning("brief ingest exception: %s", exc)
    return None


# ─────────────────────────────────────────────────────────
# 基础 CRUD
# ─────────────────────────────────────────────────────────

async def create_brief(payload: dict) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO content_studio.briefs
        (product_id, product_name, parent_brief_id, title, usp, scenarios,
         audience_profile, tone_style, source_notes, dmp_sop, extra)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, $11::jsonb)
        RETURNING *
        """,
        uuid.UUID(payload["product_id"]) if payload.get("product_id") else None,
        payload.get("product_name"),
        uuid.UUID(payload["parent_brief_id"]) if payload.get("parent_brief_id") else None,
        payload["title"],
        payload["usp"],
        json.dumps(payload.get("scenarios") or [], ensure_ascii=False),
        json.dumps(payload.get("audience_profile") or {}, ensure_ascii=False),
        json.dumps(payload.get("tone_style") or {}, ensure_ascii=False),
        payload.get("source_notes"),
        payload.get("dmp_sop"),
        json.dumps(payload.get("extra") or {}, ensure_ascii=False),
    )
    brief = dict(row)

    doc_id = await _ingest_brief_to_kb(brief)
    if doc_id:
        await pool.execute(
            "UPDATE content_studio.briefs SET kb_doc_id = $1 WHERE id = $2",
            uuid.UUID(doc_id), brief["id"],
        )
        brief["kb_doc_id"] = uuid.UUID(doc_id)

    return brief


async def list_briefs(
    limit: int = 50,
    offset: int = 0,
    *,
    product_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    pool = get_pool()
    where = []
    args: list = []
    if product_id:
        try:
            args.append(uuid.UUID(product_id))
            where.append(f"product_id = ${len(args)}")
        except ValueError:
            pass
    if status:
        args.append(status)
        where.append(f"status = ${len(args)}")
    sql = "SELECT * FROM content_studio.briefs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    args.extend([limit, offset])
    sql += f" ORDER BY created_at DESC LIMIT ${len(args)-1} OFFSET ${len(args)}"
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def get_brief(brief_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM content_studio.briefs WHERE id = $1",
        uuid.UUID(brief_id),
    )
    return dict(row) if row else None


async def update_brief(brief_id: str, payload: dict) -> dict | None:
    pool = get_pool()
    brief = await get_brief(brief_id)
    if not brief:
        return None

    merged = {
        "title": payload.get("title", brief["title"]),
        "usp": payload.get("usp", brief["usp"]),
        "scenarios": payload.get("scenarios", brief.get("scenarios") or []),
        "audience_profile": payload.get("audience_profile", brief.get("audience_profile") or {}),
        "tone_style": payload.get("tone_style", brief.get("tone_style") or {}),
        "source_notes": payload.get("source_notes", brief.get("source_notes")),
        "dmp_sop": payload.get("dmp_sop", brief.get("dmp_sop")),
        "status": payload.get("status", brief.get("status")),
        "extra": payload.get("extra", brief.get("extra") or {}),
    }
    row = await pool.fetchrow(
        """
        UPDATE content_studio.briefs
        SET title = $1,
            usp = $2,
            scenarios = $3::jsonb,
            audience_profile = $4::jsonb,
            tone_style = $5::jsonb,
            source_notes = $6,
            dmp_sop = $7,
            status = $8,
            extra = $9::jsonb,
            updated_at = NOW()
        WHERE id = $10
        RETURNING *
        """,
        merged["title"],
        merged["usp"],
        json.dumps(merged["scenarios"], ensure_ascii=False),
        json.dumps(merged["audience_profile"], ensure_ascii=False),
        json.dumps(merged["tone_style"], ensure_ascii=False),
        merged["source_notes"],
        merged["dmp_sop"],
        merged["status"],
        json.dumps(merged["extra"], ensure_ascii=False),
        uuid.UUID(brief_id),
    )
    if not row:
        return None

    updated = dict(row)
    new_doc_id = await _ingest_brief_to_kb(
        updated,
        replace_doc_id=str(updated["kb_doc_id"]) if updated.get("kb_doc_id") else None,
    )
    if new_doc_id and (str(updated.get("kb_doc_id") or "") != new_doc_id):
        await pool.execute(
            "UPDATE content_studio.briefs SET kb_doc_id = $1 WHERE id = $2",
            uuid.UUID(new_doc_id), updated["id"],
        )
        updated["kb_doc_id"] = uuid.UUID(new_doc_id)
    return updated


async def list_pipelines_using(brief_id: str) -> list[dict]:
    """所有引用该 Brief 的 pipelines（按时间倒序，含状态/标题）。"""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, title, status, current_step, digital_human_id, product_id,
               created_at, updated_at
        FROM content_studio.pipelines
        WHERE brief_id = $1
        ORDER BY created_at DESC
        LIMIT 200
        """,
        uuid.UUID(brief_id),
    )
    return [dict(r) for r in rows]


async def list_version_tree(brief_id: str) -> dict:
    """从某个 brief 出发返回完整版本树（向上找根 + 向下递归子孙）。"""
    pool = get_pool()
    cur = await get_brief(brief_id)
    if not cur:
        return {"root": None, "tree": []}

    # 向上找根
    while cur.get("parent_brief_id"):
        parent = await get_brief(str(cur["parent_brief_id"]))
        if not parent:
            break
        cur = parent
    root = cur

    rows = await pool.fetch(
        """
        WITH RECURSIVE sub AS (
          SELECT id, parent_brief_id, version, title, status, created_at
          FROM content_studio.briefs WHERE id = $1
          UNION ALL
          SELECT b.id, b.parent_brief_id, b.version, b.title, b.status, b.created_at
          FROM content_studio.briefs b
          INNER JOIN sub s ON b.parent_brief_id = s.id
        )
        SELECT * FROM sub ORDER BY version, created_at
        """,
        root["id"],
    )
    return {"root": root, "tree": [dict(r) for r in rows]}


async def delete_brief(brief_id: str) -> bool:
    pool = get_pool()
    brief = await get_brief(brief_id)
    if not brief:
        return False
    if brief.get("kb_doc_id"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.delete(
                    f"http://localhost:{settings.service_port}/api/v1/knowledge/documents/{brief['kb_doc_id']}"
                )
        except Exception:
            pass
    result = await pool.execute(
        "DELETE FROM content_studio.briefs WHERE id = $1",
        uuid.UUID(brief_id),
    )
    return result == "DELETE 1"


# ─────────────────────────────────────────────────────────
# 派生 / SOP / 飞轮回灌
# ─────────────────────────────────────────────────────────

async def derive_brief(brief_id: str, overrides: dict | None = None) -> dict | None:
    """复制一份 brief，version+1，parent_brief_id 指向源。"""
    pool = get_pool()
    src = await get_brief(brief_id)
    if not src:
        return None

    overrides = overrides or {}
    payload = {
        "product_id": str(src["product_id"]) if src.get("product_id") else None,
        "product_name": src.get("product_name"),
        "parent_brief_id": str(src["id"]),
        "title": overrides.get("title") or f"{src['title']} v{(src.get('version') or 1) + 1}",
        "usp": overrides.get("usp") or src["usp"],
        "scenarios": overrides.get("scenarios") or src.get("scenarios") or [],
        "audience_profile": overrides.get("audience_profile") or src.get("audience_profile") or {},
        "tone_style": overrides.get("tone_style") or src.get("tone_style") or {},
        "source_notes": overrides.get("source_notes") or src.get("source_notes"),
        "dmp_sop": overrides.get("dmp_sop") or src.get("dmp_sop"),
        "extra": {"derived_from": str(src["id"])},
    }
    new = await create_brief(payload)
    if new:
        await pool.execute(
            "UPDATE content_studio.briefs SET version = $1 WHERE id = $2",
            (src.get("version") or 1) + 1,
            new["id"],
        )
        new["version"] = (src.get("version") or 1) + 1
    return new


async def apply_dmp_sop(brief_id: str, sop_text: str) -> dict | None:
    return await update_brief(brief_id, {"dmp_sop": sop_text})


async def update_metrics(
    brief_id: str,
    *,
    ctr: float | None = None,
    cvr: float | None = None,
    samples: int | None = None,
    quality_score: float | None = None,
    review_summary: str | None = None,
) -> dict | None:
    """记录最近一次复盘指标到 brief.extra，便于飞轮聚合。"""
    pool = get_pool()
    current = await get_brief(brief_id)
    if not current:
        return None

    extra = current.get("extra") or {}
    if isinstance(extra, str):
        extra = json.loads(extra)
    history = list(extra.get("review_history") or [])
    history.append({
        "ctr": ctr,
        "cvr": cvr,
        "samples": samples,
        "summary": review_summary,
    })
    history = history[-20:]
    extra["review_history"] = history
    if ctr is not None:
        extra["last_ctr"] = ctr
    if cvr is not None:
        extra["last_cvr"] = cvr
    if samples is not None:
        extra["last_samples"] = samples
    if review_summary:
        extra["lessons_learned"] = review_summary[:2000]

    quality = float(quality_score) if quality_score is not None else float(current.get("quality_score") or 0)

    row = await pool.fetchrow(
        """
        UPDATE content_studio.briefs
        SET quality_score = $1,
            extra = $2::jsonb,
            updated_at = NOW()
        WHERE id = $3
        RETURNING *
        """,
        quality,
        json.dumps(extra, ensure_ascii=False),
        uuid.UUID(brief_id),
    )
    if not row:
        return None

    updated = dict(row)
    # 同步 KB doc（避免拉胯效果飞轮：KB 内的 brief 必须包含最新 lessons_learned）
    new_doc_id = await _ingest_brief_to_kb(
        updated,
        replace_doc_id=str(updated["kb_doc_id"]) if updated.get("kb_doc_id") else None,
    )
    if new_doc_id and (str(updated.get("kb_doc_id") or "") != new_doc_id):
        await pool.execute(
            "UPDATE content_studio.briefs SET kb_doc_id = $1 WHERE id = $2",
            uuid.UUID(new_doc_id), updated["id"],
        )
        updated["kb_doc_id"] = uuid.UUID(new_doc_id)
    return updated


# ─────────────────────────────────────────────────────────
# 一键生成（LLM + 三 KB 联合召回）
# ─────────────────────────────────────────────────────────

async def _fetch_product(product_id: str) -> dict | None:
    """ad-review 产品库查 product 元信息（容错：服务不在时返回 None）。"""
    if not product_id:
        return None
    url = f"{_ad_review_base()}/api/v1/ad-review/products/{product_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            body = r.json()
            return body.get("data") or body
    except Exception as exc:
        logger.debug("fetch_product failed: %s", exc)
        return None


async def _retrieve_tri_kb_with_fusion(
    queries_by_source: dict[str, tuple[str, str]],
    *,
    top_k_per_kb: int = 8,
    min_per_kb: int = 2,
    score_threshold: float = 0.30,
    total_limit: int = 10,
) -> tuple[list[dict], dict[str, list[dict]]]:
    """三 KB 联合检索 + 融合策略。

    入参：
      queries_by_source: {"ocean_engine": (kb_id, query_text), ...}

    返回：
      (merged_snippets, per_source_map)  ← per_source_map 只是给下游统计用

    融合策略：
      - 每 KB 候选池 8（~2.4x 最终量,给 score 过滤留空间）
      - 每 KB 保底 2（保证三个来源都在最终结果里）
      - score 阈值 0.30（创作类稍宽松）
      - 总量上限 10
    """
    try:
        from app.services.rag_chain import retrieve_multi_kb
    except Exception as exc:
        logger.debug("retrieve_multi_kb import failed: %s", exc)
        return [], {}

    valid: list[tuple[str, str, str]] = []  # (source_name, kb_id, query)
    for name, (kb_id, q) in queries_by_source.items():
        kb_id = (kb_id or "").strip()
        q = (q or "").strip()
        if kb_id and q:
            valid.append((name, kb_id, q))

    if not valid:
        return [], {}

    # retrieve_multi_kb 需要一个统一 query,但我们这里是每 KB 不同 query 的场景,
    # 所以分 KB 调用再自己合并 + 应用融合策略。
    per_kb_candidates: dict[str, list[dict]] = {}
    for source_name, kb_id, q in valid:
        snippets = await retrieve_multi_kb(
            q, [kb_id],
            top_k_per_kb=top_k_per_kb,
            min_per_kb=0,  # 单 KB 调用不需要保底
            score_threshold=0.0,  # 不过滤,交给外层统一处理
            total_limit=None,
            time_decay=(source_name == "content_strategy"),
            kb_name_map={kb_id: source_name},
        )
        # 截断内容长度
        for s in snippets:
            c = s.get("content") or ""
            if len(c) > 600:
                s["content"] = c[:600] + "..."
        per_kb_candidates[source_name] = snippets

    # 应用融合：每 KB 保底 min_per_kb 条不受 threshold 约束
    guaranteed: list[dict] = []
    candidates: list[dict] = []
    for source_name, _, _ in valid:
        hits = per_kb_candidates.get(source_name, [])
        for idx, s in enumerate(hits):
            if idx < min_per_kb:
                guaranteed.append(s)
            elif s["score"] >= score_threshold:
                candidates.append(s)

    merged = guaranteed + sorted(candidates, key=lambda x: x["score"], reverse=True)
    if total_limit and len(merged) > total_limit:
        g_count = len(guaranteed)
        if g_count >= total_limit:
            merged = merged[:total_limit]
        else:
            head = merged[:g_count]
            tail = sorted(merged[g_count:], key=lambda x: x["score"], reverse=True)
            merged = head + tail[: (total_limit - g_count)]

    return merged, per_kb_candidates


def _parse_brief_json(raw: str) -> dict:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
    if "```" in text:
        text = text.split("```", 1)[0]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]+\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


async def generate_draft(
    *,
    product_id: str | None,
    hints: dict | None = None,
    title: str | None = None,
) -> dict:
    """LLM + 三 KB 联合召回，输出 Brief 草稿（已落库 + KB 同步）。"""
    hints = hints or {}
    product = await _fetch_product(product_id) if product_id else None
    product_name = (
        hints.get("product_name")
        or (product or {}).get("name")
        or "未命名产品"
    )

    # 结构化输入：用 XML 分段，LLM 能明确区分"产品硬事实"vs"用户线索"vs"目标"
    product_lines: list[str] = []
    if product:
        product_lines.append(f'  <name>{product.get("name", "")}</name>')
        if product.get("sku"):
            product_lines.append(f'  <sku>{product["sku"]}</sku>')
        if product.get("price") is not None:
            product_lines.append(f'  <price>{product["price"]}</price>')
        if product.get("category"):
            product_lines.append(f'  <category>{product["category"]}</category>')
        if product.get("description"):
            product_lines.append(f'  <description>{product["description"]}</description>')

    product_xml = (
        "<product>\n" + "\n".join(product_lines) + "\n</product>"
        if product_lines else '<product empty="true" />'
    )

    hints_lines: list[str] = []
    if hints.get("category"):
        hints_lines.append(f'  <category_target>{hints["category"]}</category_target>')
    if hints.get("audience_hint"):
        hints_lines.append(f'  <audience_hint>{hints["audience_hint"]}</audience_hint>')
    if hints.get("goal"):
        hints_lines.append(f'  <goal>{hints["goal"]}</goal>')
    if hints.get("usp_hint"):
        hints_lines.append(f'  <usp_hint>{hints["usp_hint"]}</usp_hint>')

    hints_xml = (
        "<hints>\n" + "\n".join(hints_lines) + "\n</hints>"
        if hints_lines else '<hints empty="true" />'
    )

    seed_text = (
        f"{product_xml}\n\n{hints_xml}"
        if (product_lines or hints_lines)
        else '<product empty="true" />\n<hints empty="true" />\n<!-- 无产品信息,请基于品类常识推断 -->'
    )

    kb_ids = _tri_kb_ids()
    queries_by_source = {
        "ocean_engine": (kb_ids["ocean_engine"], f"{product_name} 巨量云图 人群画像 投放数据"),
        "audience_report": (kb_ids["audience_report"], f"{product_name} {hints.get('category', '')} 目标人群 偏好 行为"),
        "content_strategy": (kb_ids["content_strategy"], f"{product_name} 短视频 种草 文案 钩子 场景"),
    }

    # 三层融合：候选池 8/KB，保底 2/KB，threshold 0.30，总上限 10
    all_snippets, snippets_by_source = await _retrieve_tri_kb_with_fusion(
        queries_by_source,
        top_k_per_kb=8,
        min_per_kb=2,
        score_threshold=0.30,
        total_limit=10,
    )

    kb_block = format_kb_snippets(all_snippets)

    prompt = f"""你是资深内容投放操盘手。请基于以下信息，输出一份结构化的内容 Brief（中文）。

{KB_AS_CREATIVE_MATERIAL}

## 产品 / 业务输入
<user_input>
{seed_text}
</user_input>

## 知识库召回（来自三个 KB：ocean_engine 巨量云图 / audience_report 人群报告 / content_strategy 内容策略）
{kb_block}

{NO_AI_SLANG}

## 内容要求
- `usp_text`：3-5 行短句纯文本，直接可读。
- `usp_structured`：至少 3 条、至多 5 条。每条必须有 `point` / `evidence` / `priority`（1=最高）。`evidence` 字段不少于 10 字。
- `scenarios`：至少 3 条。每条必须有 `context` / `trigger` / `pain` / `evidence` / `priority`。
- `audience_profile.insights`：**必须同时包含** `motivation` / `objection` / `language_style` 三个字段，任一缺失即视为不合格。
- `audience_profile.tags`：若无数据支撑，用宽泛值（如 `"age": "未知"`）而非编造具体分段。
- `tone_style` 三个字段的取值必须从给定枚举中选（见 schema）。

{JSON_OUTPUT_DISCIPLINE}

## 输出 Schema
```json
{{
  "title": "简短标题，例如 '2026春季·XX面霜·25-35轻奢女性'",
  "usp_text": "用 3~5 行短句的形式给一段纯文本，便于直接显示",
  "usp_structured": [
    {{"point": "核心卖点（一句话）", "evidence": "来源说明（≥10 字）", "priority": 1}}
  ],
  "scenarios": [
    {{"context": "场景上下文", "trigger": "触发时机", "pain": "用户痛点", "evidence": "来源说明", "priority": 1}}
  ],
  "audience_profile": {{
    "tags": {{"age": "25-35", "gender": "F", "interest": ["护肤"], "consumption_level": "A3-A4"}},
    "insights": {{
      "motivation": "为什么会买",
      "objection": "可能犹豫的点",
      "language_style": "她们日常说话的方式举例"
    }},
    "dmp_package_id": null
  }},
  "tone_style": {{
    "style": "种草/品牌/促销/测评/温馨故事 之一",
    "tone": "casual/professional/exciting/analytical/emotional 之一",
    "pace": "fast/medium/slow 之一"
  }}
}}
```
"""

    # 飞轮：拼上累积规则
    brief_scope = {"product_id": product_id or "", "category": hints.get("category", "")}
    prompt += await render_rules_suffix("briefs.draft", brief_scope)

    raw = ""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                _hub_chat_url(),
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.6,
                },
            )
            resp.raise_for_status()
            chat_data = resp.json()
        raw = chat_data.get("content", "")
        await log_feedback("briefs.draft", input_ref=brief_scope, full_prompt=prompt, output=raw)
        parsed = _parse_brief_json(raw)
    except Exception as exc:
        logger.warning("Brief draft generation failed: %s", exc)
        # 兜底：写一份骨架，让用户手工填
        parsed = {
            "title": title or f"{product_name} 草稿",
            "usp": "（生成失败，请手工补齐 USP）",
            "scenarios": [],
            "audience_profile": {},
            "tone_style": {},
        }

    # USP：优先用 usp_text 作为可读文本；同时把 usp_structured 存到 extra
    usp_text = parsed.get("usp_text") or parsed.get("usp")
    usp_structured = parsed.get("usp_structured")
    if not usp_text and isinstance(usp_structured, list):
        # 用 structured 拼回字符串
        usp_text = "\n".join(
            f"{i+1}. {it.get('point', '')}"
            for i, it in enumerate(usp_structured) if isinstance(it, dict)
        )

    payload = {
        "product_id": product_id,
        "product_name": product_name,
        "title": title or parsed.get("title") or f"{product_name} 草稿",
        "usp": usp_text or "",
        "scenarios": parsed.get("scenarios") or [],
        "audience_profile": parsed.get("audience_profile") or {},
        "tone_style": parsed.get("tone_style") or {},
        "source_notes": (
            f"AI 生成草稿\n命中知识库：{', '.join(k for k, v in snippets_by_source.items() if v) or '无'}"
        ),
        "extra": {
            "ai_generated": True,
            "kb_hits": {k: len(v) for k, v in snippets_by_source.items()},
            "usp_structured": usp_structured or [],
        },
    }
    return await create_brief(payload)


# Backward compat: older import name
update_brief_metrics = update_metrics
