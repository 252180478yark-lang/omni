"""SKU 内容编排器 — 把 17 步链路从 SKU 起点跑到 Brief + Pipeline。

阶段（state machine）：
  1. selling_points       三类卖点分析（基于 mvp_sku 主数据 + 老板手填卖点）
  2. audience_match       匹配人群（KB 检索 + LLM）
  3. audience_profile     人群画像分析
  4. dmp_sop              圈包策略
  5. content_preference   人群偏好内容分析（喜欢看什么）
  6. purpose_routing      目的分流（曝光 / 种草 / 收割）— 可由老板预指定
  7. script_brief         把以上产物拼成 Brief 草稿（落库）
  8. pipeline_linked      用 brief_id 起一个 content-studio pipeline
  9. completed

每步独立可重跑，状态全写 content_studio.sku_orchestrations 表。
失败任意一步：current_step 保留，status='failed'，error_message 写入。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.database import get_pool
from app.services.briefs import generate_draft as briefs_generate_draft
from app.services.content_studio import create_pipeline as cs_create_pipeline
from app.services.prompt_commons import (
    JSON_OUTPUT_DISCIPLINE,
    KB_AS_CREATIVE_MATERIAL,
    NO_AI_SLANG,
    format_kb_snippets,
)
from app.services.prompt_templates import PURPOSE_PLAYBOOK, get_purpose_block

logger = logging.getLogger(__name__)


STEPS_ORDER: list[str] = [
    "selling_points",
    "audience_match",
    "audience_profile",
    "dmp_sop",
    "content_preference",
    "purpose_routing",
    "script_brief",
    "pipeline_linked",
    "completed",
]


def _hub_chat_url() -> str:
    return f"{settings.ai_hub_url.rstrip('/')}/api/v1/ai/chat/completions"


def _tri_kb_ids() -> dict[str, str]:
    """同 briefs._tri_kb_ids：直接读 settings 中的三 KB id。"""
    return {
        "ocean_engine": (getattr(settings, "content_pipeline_kb_ocean_engine", "") or "").strip(),
        "audience_report": (getattr(settings, "content_pipeline_kb_audience_report", "") or "").strip(),
        "content_strategy": (getattr(settings, "content_pipeline_kb_content_strategy", "") or "").strip(),
    }


# ─────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────

async def create_orchestration(
    *,
    sku_id: str,
    title: str | None = None,
    target_purpose: str | None = None,
) -> dict:
    """创建编排任务。如果目标 purpose 已知，可一并传入；否则在 purpose_routing 步由 LLM 推荐。"""
    if target_purpose and target_purpose not in PURPOSE_PLAYBOOK:
        raise ValueError(f"invalid target_purpose: {target_purpose}")
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO content_studio.sku_orchestrations
            (sku_id, title, status, current_step, target_purpose)
        VALUES ($1, $2, 'in_progress', 'selling_points', $3)
        RETURNING *
        """,
        sku_id,
        title or f"SKU {sku_id} 内容编排",
        target_purpose,
    )
    return _serialize(row)


async def get_orchestration(orch_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM content_studio.sku_orchestrations WHERE id = $1",
        uuid.UUID(orch_id),
    )
    return _serialize(row) if row else None


async def list_orchestrations(
    *,
    sku_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    pool = get_pool()
    if sku_id:
        rows = await pool.fetch(
            """SELECT * FROM content_studio.sku_orchestrations
               WHERE sku_id = $1
               ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            sku_id, limit, offset,
        )
    else:
        rows = await pool.fetch(
            """SELECT * FROM content_studio.sku_orchestrations
               ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
            limit, offset,
        )
    return [_serialize(r) for r in rows]


async def _update_step(
    orch_id: str,
    *,
    step: str | None = None,
    status: str | None = None,
    error_message: str | None = None,
    **field_updates: Any,
) -> dict:
    pool = get_pool()
    sets: list[str] = []
    vals: list[Any] = []
    idx = 1
    if step is not None:
        sets.append(f"current_step = ${idx}"); idx += 1; vals.append(step)
    if status is not None:
        sets.append(f"status = ${idx}"); idx += 1; vals.append(status)
    if error_message is not None:
        sets.append(f"error_message = ${idx}"); idx += 1; vals.append(error_message)
    for key, val in field_updates.items():
        if isinstance(val, (dict, list)):
            sets.append(f"{key} = ${idx}::jsonb"); idx += 1
            vals.append(json.dumps(val, ensure_ascii=False))
        else:
            sets.append(f"{key} = ${idx}"); idx += 1; vals.append(val)
    if not sets:
        row = await pool.fetchrow(
            "SELECT * FROM content_studio.sku_orchestrations WHERE id = $1",
            uuid.UUID(orch_id),
        )
        return _serialize(row) if row else {}
    sql = (
        "UPDATE content_studio.sku_orchestrations SET "
        + ", ".join(sets)
        + f" WHERE id = ${idx} RETURNING *"
    )
    vals.append(uuid.UUID(orch_id))
    row = await pool.fetchrow(sql, *vals)
    return _serialize(row) if row else {}


def _serialize(row: Any) -> dict:
    if row is None:
        return {}
    d = dict(row)
    if "id" in d and isinstance(d["id"], uuid.UUID):
        d["id"] = str(d["id"])
    if d.get("linked_brief_id") and isinstance(d["linked_brief_id"], uuid.UUID):
        d["linked_brief_id"] = str(d["linked_brief_id"])
    if d.get("linked_pipeline_id") and isinstance(d["linked_pipeline_id"], uuid.UUID):
        d["linked_pipeline_id"] = str(d["linked_pipeline_id"])
    for jk in (
        "selling_points_result",
        "matched_audience_result",
        "audience_profile_result",
        "audience_content_pref_result",
        "script_result",
        "step_meta",
    ):
        if isinstance(d.get(jk), str):
            try:
                d[jk] = json.loads(d[jk])
            except Exception:
                pass
    if isinstance(d.get("created_at"), datetime):
        d["created_at"] = d["created_at"].isoformat()
    if isinstance(d.get("updated_at"), datetime):
        d["updated_at"] = d["updated_at"].isoformat()
    return d


# ─────────────────────────────────────────────────────────
# 工具：fetch SKU + 调 LLM
# ─────────────────────────────────────────────────────────

async def _fetch_sku(sku_id: str) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, category, status, push_tier,
               owner_selling_points, owner_notes, price_min, price_max,
               specifications,
               total_stock, growth_class, douyin_product_id, douyin_url
        FROM public.mvp_sku WHERE id = $1
        """,
        sku_id,
    )
    if not row:
        raise ValueError(f"SKU not found: {sku_id}")
    d = dict(row)
    if isinstance(d.get("owner_selling_points"), str):
        try:
            d["owner_selling_points"] = json.loads(d["owner_selling_points"])
        except Exception:
            d["owner_selling_points"] = []
    return d


async def _retrieve_kb(kb_id: str, query: str, top_k: int = 6) -> list[dict]:
    """走 knowledge-engine 内部 service 直接召回（同进程）。"""
    if not kb_id:
        return []
    try:
        from app.services.rag_chain import retrieve_only

        return await retrieve_only(query, kb_id, top_k=top_k)
    except Exception as exc:
        logger.debug("kb retrieve failed: kb=%s q=%s err=%s", kb_id, query[:40], exc)
        return []


async def _llm_json(prompt: str, *, temperature: float = 0.5) -> dict:
    """调 ai-provider-hub，强制返回 JSON。失败抛异常。"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            _hub_chat_url(),
            json={
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    raw = (data.get("content") or "").strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1]
    if "```" in raw:
        raw = raw.split("```", 1)[0]
    return json.loads(raw.strip())


# ─────────────────────────────────────────────────────────
# 各步实现
# ─────────────────────────────────────────────────────────

async def step_selling_points(orch_id: str) -> dict:
    """Step 1: 三类卖点分析（显性 / 隐性 / 独特）。"""
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    sku = await _fetch_sku(orch["sku_id"])

    owner_sp = sku.get("owner_selling_points") or []
    owner_sp_text = "\n".join(
        f"- {(it.get('text') if isinstance(it, dict) else str(it))}"
        for it in owner_sp if it
    ) or "（老板未填卖点，请基于品类常识与产品名推断）"

    price_text = ""
    if sku.get("price_min") is not None or sku.get("price_max") is not None:
        price_text = f"{sku.get('price_min') or ''}-{sku.get('price_max') or ''}"

    prompt = f"""你是资深消费品营销操盘手。请基于这个 SKU 的硬事实 + 老板视角输入，分析三类卖点。

## SKU 主数据
- 名称：{sku.get('name', '')}
- 品类：{sku.get('category', '')}
- 价格区间：{price_text or '未提供'}
- 规格：{sku.get('specifications') or '未提供'}
- 平台状态：{sku.get('status', '')}
- 增长分类：{sku.get('growth_class', '')}
- 老板备注：{sku.get('owner_notes') or '（无）'}

## 老板视角的卖点（必须重点参考）
{owner_sp_text}

## 三类卖点分类标准（关键）
- **显性卖点（usp_explicit）**：客户从商品图、详情页、或第一句话就能看出来的事实。例：包装规格、价格、外观、口感描述、配料表关键字。
- **隐性卖点（usp_implicit）**：需要解释、类比、或讲故事才能让用户感知的优势。例：发酵工艺、研发周期、原料产地、技术认证。
- **独特卖点（usp_unique）**：这个 SKU 区别于同品类竞品的地方。例：独家专利、首创工艺、品牌历史、创始人理念、独家原料。

{NO_AI_SLANG}

{JSON_OUTPUT_DISCIPLINE}

## 输出 Schema
```json
{{
  "usp_explicit": [
    {{"point": "显性卖点（一句话）", "evidence": "为什么属于显性（≥10 字）", "priority": 1}}
  ],
  "usp_implicit": [
    {{"point": "隐性卖点", "evidence": "为什么属于隐性", "priority": 1}}
  ],
  "usp_unique": [
    {{"point": "独特卖点", "evidence": "为什么属于独特", "priority": 1}}
  ]
}}
```
要求：每类至少 2 条（独特至少 1 条），priority 从 1 开始升序。
"""
    try:
        result = await _llm_json(prompt, temperature=0.4)
    except Exception as exc:
        logger.exception("step_selling_points failed: %s", exc)
        return await _update_step(
            orch_id, status="failed", error_message=f"selling_points: {exc}",
        )

    return await _update_step(
        orch_id,
        step="audience_match",
        status="in_progress",
        error_message=None,
        selling_points_result=result,
    )


async def step_audience_match(orch_id: str) -> dict:
    """Step 2: 基于卖点 + KB 检索匹配人群。"""
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    sku = await _fetch_sku(orch["sku_id"])
    sp = orch.get("selling_points_result") or {}

    sp_summary = " | ".join(
        it.get("point", "")
        for cat in ("usp_explicit", "usp_implicit", "usp_unique")
        for it in (sp.get(cat) or [])
    )[:500]

    kb_ids = _tri_kb_ids()
    audience_kb = kb_ids.get("audience_report", "")
    query = f"{sku.get('name', '')} {sku.get('category', '')} 目标人群 兴趣 行为"
    snippets = await _retrieve_kb(audience_kb, query, top_k=6) if audience_kb else []
    kb_block = format_kb_snippets(snippets) if snippets else "（人群报告 KB 无召回）"

    prompt = f"""你是消费品人群洞察师。基于 SKU 卖点和人群报告 KB，判断该 SKU 最匹配的目标人群（≥2 个、≤4 个）。

## SKU 信息
- 名称：{sku.get('name', '')}
- 品类：{sku.get('category', '')}
- 卖点摘要：{sp_summary or '（待补全）'}

## 知识库召回（人群报告）
{KB_AS_CREATIVE_MATERIAL}
{kb_block}

{NO_AI_SLANG}

{JSON_OUTPUT_DISCIPLINE}

## 输出 Schema
```json
{{
  "candidates": [
    {{
      "name": "人群标签（如 25-35 居家烹饪精致妈妈）",
      "size_estimate": "粗估规模（如 大/中/小 或 100w 量级）",
      "match_reason": "为什么这个 SKU 适配（≥30 字）",
      "matched_selling_points": ["命中的卖点 1", "命中的卖点 2"],
      "priority": 1
    }}
  ],
  "primary_audience": "首选人群名（candidates 中之一）"
}}
```
"""
    try:
        result = await _llm_json(prompt, temperature=0.4)
    except Exception as exc:
        logger.exception("step_audience_match failed: %s", exc)
        return await _update_step(
            orch_id, status="failed", error_message=f"audience_match: {exc}",
        )

    return await _update_step(
        orch_id,
        step="audience_profile",
        status="in_progress",
        error_message=None,
        matched_audience_result=result,
    )


async def step_audience_profile(orch_id: str) -> dict:
    """Step 3: 人群画像分析（基于首选人群 + KB 深挖）。"""
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    matched = orch.get("matched_audience_result") or {}
    primary = matched.get("primary_audience") or ""
    candidates = matched.get("candidates") or []
    primary_obj = next((c for c in candidates if c.get("name") == primary), candidates[0] if candidates else {})

    kb_ids = _tri_kb_ids()
    snippets: list[dict] = []
    if kb_ids.get("audience_report"):
        snippets += await _retrieve_kb(kb_ids["audience_report"], f"{primary} 画像 行为 偏好", top_k=4)
    if kb_ids.get("ocean_engine"):
        snippets += await _retrieve_kb(kb_ids["ocean_engine"], f"{primary} 5A 资产 转化路径", top_k=3)
    kb_block = format_kb_snippets(snippets) if snippets else "（KB 无召回，请基于品类常识推断）"

    prompt = f"""你是 5A 人群画像分析师。请输出对该人群的结构化画像。

## 首选人群
- 名称：{primary}
- 匹配理由：{primary_obj.get('match_reason', '')}
- 命中卖点：{', '.join(primary_obj.get('matched_selling_points') or [])}

## 知识库召回（人群报告 + 巨量云图）
{KB_AS_CREATIVE_MATERIAL}
{kb_block}

{NO_AI_SLANG}

{JSON_OUTPUT_DISCIPLINE}

## 输出 Schema
```json
{{
  "tags": {{
    "age": "25-35",
    "gender": "F/M/全/其它",
    "tier": "一二线/三四线/全",
    "consumption_level": "A1-A2 / A2-A3 / A3-A4 / A4-A5"
  }},
  "insights": {{
    "motivation": "为什么会买（≥30 字）",
    "objection": "可能犹豫的点（≥20 字）",
    "language_style": "她们日常说话举例（≥20 字，给出真实口吻片段）"
  }},
  "scenarios": [
    {{"context": "场景上下文", "trigger": "触发时机", "pain": "痛点", "evidence": "来源", "priority": 1}}
  ],
  "channels": ["主要触达渠道（如 抖音 / 小红书 / 朋友圈 / 微信群）"]
}}
```
要求：scenarios 至少 3 条；insights 三字段必填。
"""
    try:
        result = await _llm_json(prompt, temperature=0.5)
    except Exception as exc:
        logger.exception("step_audience_profile failed: %s", exc)
        return await _update_step(
            orch_id, status="failed", error_message=f"audience_profile: {exc}",
        )

    return await _update_step(
        orch_id,
        step="dmp_sop",
        status="in_progress",
        error_message=None,
        audience_profile_result=result,
    )


async def step_dmp_sop(orch_id: str) -> dict:
    """Step 4: 圈包策略（基于画像 → 给出 DMP 圈包思路）。"""
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    matched = orch.get("matched_audience_result") or {}
    profile = orch.get("audience_profile_result") or {}

    kb_ids = _tri_kb_ids()
    snippets: list[dict] = []
    if kb_ids.get("ocean_engine"):
        snippets += await _retrieve_kb(
            kb_ids["ocean_engine"],
            f"{matched.get('primary_audience', '')} DMP 标签 圈包 行为",
            top_k=5,
        )
    kb_block = format_kb_snippets(snippets) if snippets else "（云图 KB 无召回）"

    prompt = f"""你是巨量云图 DMP 圈包专家。基于人群画像，给一份可直接照做的圈包 SOP。

## 人群画像
{json.dumps(profile, ensure_ascii=False, indent=2)}

## 知识库召回（巨量云图）
{KB_AS_CREATIVE_MATERIAL}
{kb_block}

{NO_AI_SLANG}

## 输出要求
- 输出**纯 markdown 文本**（不是 JSON），可直接放入 brief.dmp_sop 字段。
- 至少包含：(1) 推荐圈包标签组合（兴趣 + 行为 + 5A 阶段交叉）；(2) 排除条件；(3) 预估包大小级别；(4) 圈包后建议的触达节奏（每周触达 N 次、停留 N 天）。
- 长度 200-400 字。

直接输出 markdown，不要前后引号或代码块。
"""
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                _hub_chat_url(),
                json={"messages": [{"role": "user", "content": prompt}], "temperature": 0.4},
            )
            resp.raise_for_status()
            sop = (resp.json().get("content") or "").strip()
    except Exception as exc:
        logger.exception("step_dmp_sop failed: %s", exc)
        return await _update_step(
            orch_id, status="failed", error_message=f"dmp_sop: {exc}",
        )

    return await _update_step(
        orch_id,
        step="content_preference",
        status="in_progress",
        error_message=None,
        dmp_sop_result=sop,
    )


async def step_content_preference(orch_id: str) -> dict:
    """Step 5: 这个人群在抖音/小红书喜欢看什么。"""
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    profile = orch.get("audience_profile_result") or {}

    kb_ids = _tri_kb_ids()
    snippets: list[dict] = []
    primary_keywords = " ".join(profile.get("channels") or [])
    if kb_ids.get("content_strategy"):
        snippets += await _retrieve_kb(
            kb_ids["content_strategy"],
            f"{primary_keywords} 短视频 钩子 选题 内容形式",
            top_k=6,
        )
    kb_block = format_kb_snippets(snippets) if snippets else "（内容策略 KB 无召回）"

    prompt = f"""你是短视频内容研究员。基于人群画像 + 内容策略 KB，输出该人群偏好的内容画像。

## 人群画像
{json.dumps(profile, ensure_ascii=False, indent=2)}

## 知识库召回（内容策略）
{KB_AS_CREATIVE_MATERIAL}
{kb_block}

{NO_AI_SLANG}

{JSON_OUTPUT_DISCIPLINE}

## 输出 Schema
```json
{{
  "topics": ["话题1", "话题2", "话题3", "话题4"],
  "formats": ["剧情", "口播", "测评", "Vlog", "情景再现"],
  "styles": ["治愈", "搞笑", "反差", "干货", "温情"],
  "hooks": [
    "前 3 秒钩子模板 1（具体可用句式）",
    "前 3 秒钩子模板 2",
    "前 3 秒钩子模板 3"
  ],
  "do_nots": ["禁忌 1", "禁忌 2"]
}}
```
要求：topics ≥ 3，formats / styles / hooks ≥ 3。
"""
    try:
        result = await _llm_json(prompt, temperature=0.5)
    except Exception as exc:
        logger.exception("step_content_preference failed: %s", exc)
        return await _update_step(
            orch_id, status="failed", error_message=f"content_preference: {exc}",
        )

    return await _update_step(
        orch_id,
        step="purpose_routing",
        status="in_progress",
        error_message=None,
        audience_content_pref_result=result,
    )


async def step_purpose_routing(orch_id: str, *, override_purpose: str | None = None) -> dict:
    """Step 6: 目的分流。

    若 orchestration.target_purpose 已指定，直接确认。
    若未指定且 override_purpose 也未给，调 LLM 推荐。
    """
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    purpose = override_purpose or orch.get("target_purpose")

    if purpose:
        if purpose not in PURPOSE_PLAYBOOK:
            return await _update_step(
                orch_id, status="failed",
                error_message=f"invalid target_purpose: {purpose}",
            )
        return await _update_step(
            orch_id,
            step="script_brief",
            status="in_progress",
            error_message=None,
            target_purpose=purpose,
        )

    # LLM 推荐目的
    matched = orch.get("matched_audience_result") or {}
    profile = orch.get("audience_profile_result") or {}
    sku = await _fetch_sku(orch["sku_id"])

    prompt = f"""你是抖音电商投放策略师。基于 SKU 状态 + 人群画像，推荐这次内容应该走哪个目的。

## SKU 状态
- 名称：{sku.get('name', '')}
- 增长分类：{sku.get('growth_class', '')}（excellent=已起量 / good=稳定 / declining=衰退 / optimizing=待优化）
- 当前主推等级：{sku.get('push_tier', '')}

## 人群
- 首选：{matched.get('primary_audience', '')}
- 5A 等级（来自画像）：{(profile.get('tags') or {}).get('consumption_level', '')}

## 三个目的
- **awareness 曝光**：泛人群第一次认识，A1 层级；适合新品/翻红期
- **planting 种草**：A2-A3 兴趣 → 询问，建立产品好感；适合主推/优化期
- **conversion 收割**：A4 行动，强转化；适合大促/爆品续命/库存清理

{JSON_OUTPUT_DISCIPLINE}

## 输出 Schema
```json
{{
  "recommended": "awareness 或 planting 或 conversion",
  "reason": "推荐理由（≥40 字）",
  "alternatives": ["次选目的（如 conversion）"]
}}
```
"""
    try:
        result = await _llm_json(prompt, temperature=0.3)
        purpose = result.get("recommended")
        if purpose not in PURPOSE_PLAYBOOK:
            purpose = "planting"  # 兜底
    except Exception as exc:
        logger.warning("step_purpose_routing LLM failed, fallback to planting: %s", exc)
        purpose = "planting"
        result = {"recommended": purpose, "reason": "LLM 调用失败，使用默认值"}

    step_meta = orch.get("step_meta") or {}
    if isinstance(step_meta, str):
        try:
            step_meta = json.loads(step_meta)
        except Exception:
            step_meta = {}
    step_meta["purpose_routing"] = result

    return await _update_step(
        orch_id,
        step="script_brief",
        status="in_progress",
        error_message=None,
        target_purpose=purpose,
        step_meta=step_meta,
    )


async def step_script_brief(orch_id: str) -> dict:
    """Step 7: 把所有产物拼成 hints，调 briefs.generate_draft 落 Brief。"""
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    sku = await _fetch_sku(orch["sku_id"])
    sp = orch.get("selling_points_result") or {}
    matched = orch.get("matched_audience_result") or {}
    profile = orch.get("audience_profile_result") or {}
    pref = orch.get("audience_content_pref_result") or {}
    dmp_sop = orch.get("dmp_sop_result") or ""
    purpose = orch.get("target_purpose")

    # 拼 hints —— 把前 5 步沉淀的产物全部塞进去
    hints = {
        "product_name": sku.get("name", ""),
        "category": sku.get("category", ""),
        "audience_hint": matched.get("primary_audience", ""),
        "goal": PURPOSE_PLAYBOOK.get(purpose, {}).get("intent") if purpose else "",
        "usp_hint": " | ".join(
            it.get("point", "")
            for cat in ("usp_explicit", "usp_implicit", "usp_unique")
            for it in (sp.get(cat) or [])
        )[:500],
        "audience_profile_hint": profile,
        "audience_content_preference_hint": pref,
        "dmp_sop_hint": dmp_sop,
    }

    try:
        brief = await briefs_generate_draft(
            product_id=None,
            sku_id=orch["sku_id"],
            hints=hints,
            title=orch.get("title"),
            target_purpose=purpose,
        )
        # 用三类 USP / 偏好内容 / DMP SOP 把 brief 字段补齐（generate_draft 已给基础结构，但显式覆盖更稳）
        from app.services.briefs import update_brief
        brief_id = str(brief["id"])
        await update_brief(brief_id, {
            "usp_explicit": sp.get("usp_explicit") or [],
            "usp_implicit": sp.get("usp_implicit") or [],
            "usp_unique": sp.get("usp_unique") or [],
            "audience_content_preference": pref,
            "dmp_sop": dmp_sop,
            "sku_id": orch["sku_id"],
        })
    except Exception as exc:
        logger.exception("step_script_brief failed: %s", exc)
        return await _update_step(
            orch_id, status="failed", error_message=f"script_brief: {exc}",
        )

    return await _update_step(
        orch_id,
        step="pipeline_linked",
        status="in_progress",
        error_message=None,
        linked_brief_id=str(brief["id"]),
        script_result={"brief_id": str(brief["id"]), "title": brief.get("title")},
    )


async def step_pipeline_linked(orch_id: str) -> dict:
    """Step 8: 用 brief_id 起一个 content-studio pipeline。"""
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    if not orch.get("linked_brief_id"):
        return await _update_step(
            orch_id, status="failed",
            error_message="pipeline_linked: 缺 brief_id（前一步未完成）",
        )

    sku = await _fetch_sku(orch["sku_id"])
    title = f"{sku.get('name', orch['sku_id'])}·{PURPOSE_PLAYBOOK.get(orch.get('target_purpose'), {}).get('label', '内容')}"

    try:
        pipe = await cs_create_pipeline(
            title=title,
            source_text="",
            config={"copy_style": "grassplanting", "pace": "medium"},
            brief_id=orch["linked_brief_id"],
            sku_id=orch["sku_id"],
            skip_final_concat=True,  # 老板要的是分镜视频自己剪
        )
    except Exception as exc:
        logger.exception("step_pipeline_linked failed: %s", exc)
        return await _update_step(
            orch_id, status="failed", error_message=f"pipeline_linked: {exc}",
        )

    return await _update_step(
        orch_id,
        step="completed",
        status="completed",
        error_message=None,
        linked_pipeline_id=str(pipe["id"]),
    )


# ─────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────

STEP_FN_MAP = {
    "selling_points": step_selling_points,
    "audience_match": step_audience_match,
    "audience_profile": step_audience_profile,
    "dmp_sop": step_dmp_sop,
    "content_preference": step_content_preference,
    "purpose_routing": step_purpose_routing,
    "script_brief": step_script_brief,
    "pipeline_linked": step_pipeline_linked,
}


async def run_step(orch_id: str, step: str | None = None) -> dict:
    """跑一步。step=None 时跑当前 current_step。失败不抛，写库。"""
    orch = await get_orchestration(orch_id)
    if not orch:
        raise ValueError("Orchestration not found")
    target_step = step or orch.get("current_step")
    if target_step == "completed":
        return orch
    fn = STEP_FN_MAP.get(target_step)
    if not fn:
        raise ValueError(f"unknown step: {target_step}")
    return await fn(orch_id)


async def advance(orch_id: str) -> dict:
    """从 current_step 一直跑到 completed 或 failed（连续推进）。"""
    while True:
        orch = await get_orchestration(orch_id)
        if not orch:
            raise ValueError("Orchestration not found")
        if orch["status"] in ("completed", "failed"):
            return orch
        cur = orch.get("current_step")
        if cur == "completed" or cur not in STEP_FN_MAP:
            return orch
        await run_step(orch_id, cur)
