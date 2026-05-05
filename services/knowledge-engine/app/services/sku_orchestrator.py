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
    return f"{settings.ai_provider_hub_url.rstrip('/')}/api/v1/ai/chat"


_KB_IDS_CACHE: dict[str, str] | None = None


async def _tri_kb_ids_async() -> dict[str, str]:
    """三 KB id：先看 settings 显式配置；空则按 W3a kb_role 自动 fallback。

    role → tri_key 映射：
      authoritative → ocean_engine（运营手册类，云图 / 千川）
      private_doc → audience_report（自家事实，人群报告 / 复盘日记）
      template → content_strategy（爆款拆解 / 投放复盘）
    """
    global _KB_IDS_CACHE
    if _KB_IDS_CACHE is not None:
        return _KB_IDS_CACHE

    out = {
        "ocean_engine": (getattr(settings, "content_pipeline_kb_ocean_engine", "") or "").strip(),
        "audience_report": (getattr(settings, "content_pipeline_kb_audience_report", "") or "").strip(),
        "content_strategy": (getattr(settings, "content_pipeline_kb_content_strategy", "") or "").strip(),
    }
    if all(out.values()):
        _KB_IDS_CACHE = out
        return out

    # fallback: 从 kb_role 自动找；按 name 关键字 prefer 更精准的 KB
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id::text AS id, name, kb_role FROM knowledge.knowledge_bases WHERE kb_role IN ('authoritative', 'private_doc', 'template') ORDER BY created_at"
    )
    by_role: dict[str, list[dict]] = {}
    for r in rows:
        by_role.setdefault(r["kb_role"], []).append(dict(r))

    def _pick(role: str, prefer_keywords: list[str]) -> str:
        kbs = by_role.get(role) or []
        for kw in prefer_keywords:
            for kb in kbs:
                if kw in (kb.get("name") or ""):
                    return kb["id"]
        return kbs[0]["id"] if kbs else ""

    if not out["ocean_engine"]:
        out["ocean_engine"] = _pick("authoritative", ["云图", "巨量云图"])
    if not out["audience_report"]:
        out["audience_report"] = _pick("private_doc", ["人群", "人群分析"])
    if not out["content_strategy"]:
        out["content_strategy"] = _pick("template", ["切片", "爆款", "模板"])
    _KB_IDS_CACHE = out
    return out


def _tri_kb_ids() -> dict[str, str]:
    """同步版本，仅返 settings 配置（用于已加载的 orchestrator 调用）。
    需要 fallback 时调用 _tri_kb_ids_async。
    """
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


async def _llm_json(prompt: str, *, temperature: float = 0.5, max_tokens: int = 8000) -> dict:
    """调 ai-provider-hub，强制返回 JSON。失败抛异常。"""
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            _hub_chat_url(),
            json={
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
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

    prompt = f"""你是一位深耕**调味品与佐餐小菜行业**的资深产品策略分析师。你服务过的品类覆盖：基础调味料（酱油、醋、料酒、糖）、复合调味料（火锅底料、调味汁、拌饭酱）、日式调味料（味醂、寿司醋、日式酱油、味噌）、佐餐小菜（锦州小菜、酱腌菜、腌渍菜、下饭菜）。

你的**唯一任务**是：拿到一款产品的基础资料，**只做前置的产品侧分析**——把显性卖点、隐性卖点、独特卖点挖到位，把使用场景、场景心智、内容心智、产品心智、品牌心智这五个维度解剖到位。

## 严格边界（最重要的规则）

这份报告是整个内容生产链路的第一步。下游还有：知识库人群匹配、内容生成（脚本/分镜/视频）。因此你**绝对不做**：

1. ❌ 不描述人群——不写"宝妈/白领/小镇青年""年龄段"等
2. ❌ 不写文案/标题/钩子——不给文案例子、口播、Slogan
3. ❌ 不推荐内容形式——不说"适合做短视频/直播/图文"
4. ❌ 不推荐投放渠道——不提抖音/小红书/视频号/天猫/京东
5. ❌ 不写脚本——不给前 3 秒钩子、CTA
6. ❌ 不给内容主线——不做月度/季度内容排期建议

你**只做**：把产品本身读透 + 三层卖点（显性/隐性/USP）+ 5 心智维度（使用场景/场景心智/内容心智/产品心智/品牌心智）+ 结构化标签。

## 工作原则

1. **品类真话优先**：调味品/佐餐小菜是高复购、低决策成本、场景驱动品类。用调味品自己的逻辑（好不好吃、下不下饭、家人爱不爱吃、替代谁家的、省不省事）。
2. **合规红线不越**：涉及"零添加""减盐""有机""0 防腐剂""儿童酱油""健康""功效"等表述，必须标注合规风险等级（高/中/低）+ 替代表述建议。食品法规对调味品宣传边界严格。
3. **显性/隐性/USP 严格区分**：
   - 显性 = 用户不用买就能从包装/详情页/参数直接看到的（等级、酿造天数、原料产地、零添加、价格、容量、工艺、认证）
   - 隐性 = 买回家使用后才能感知到的（挂壁感、回甘、后味、不齁咸、开盖后久放、做菜不抢味、不腥不腻、凉菜第二天不出水）
   - USP = 在本品类里**只有这个产品能讲**或**只有这个品牌讲最有说服力**的一句话；必须通过**排他性检验**：竞品也能说就不是 USP
4. **心智不等于卖点**：卖点 20 个能占住的心智通常只有 1-2 个。
5. **实事求是**：资料不足时明确写"信息不足，需补充 XXX"，不编造。
6. **证据优先级**：用户评价原文/客服反馈 > 配料表/参数/规格/价格 > 包装与详情页 > 品牌自述 > 品类常识。无证据时标"信息不足"，不要把品类常识包装成产品卖点。
7. **关键词必须可检索**：每个卖点的 5 个核心关键词必须是工艺/口感/场景/对比/复购原因类**具体短语**；禁用"高端/优质/好吃/方便/健康/品质感"这类空泛词。
8. **场景只描述产品出现的位置**：必须是具体、可视化的生活/烹饪/食用画面，只写"产品在哪里、怎么被使用、解决了什么场景问题"；不写人群画像、不写传播建议。
9. **卖点必须判断强弱**：每个显性/隐性卖点必须给强度评分 1-5（综合证据强度、差异化、场景匹配、复购关联、合规安全度）。评分必须帮助判断这个卖点是否值得进入下游 KB 匹配。
10. **场景必须解释匹配逻辑**：每个卖点的匹配场景后必须补"匹配理由"，说明为什么这场景最能放大该卖点。

## SKU 资料

- 名称：{sku.get('name', '')}
- 品类：{sku.get('category', '')}
- 价格区间：{price_text or '未提供'}
- 规格：{sku.get('specifications') or '未提供'}
- 平台状态：{sku.get('status', '')}
- 增长分类：{sku.get('growth_class', '')}
- 老板备注：{sku.get('owner_notes') or '（无）'}

## 老板视角的卖点（必须重点参考）
{owner_sp_text}

{NO_AI_SLANG}

{JSON_OUTPUT_DISCIPLINE}

## 输出 JSON Schema（严格按此输出，不要 markdown 报告）

```json
{{
  "product_archive_summary": "150-250 字段落：品类定位、价格段位（入门/主流/中高端/高端）、SKU 结构、核心原料与工艺关键词、5-8 个高频关键词（正面/负面分开）。不描述人群。",

  "usp_explicit": [
    {{
      "point": "显性卖点名称（一句话）",
      "evidence": "证据来源：包装/详情页/参数/配料表/工艺/认证/价格/规格中的哪一项",
      "priority": 1,
      "perceivability": "高|中|低",
      "category_rarity": "独有|少见|普通|泛滥",
      "compliance_risk": "高|中|低",
      "strength_score": 4,
      "strength_reason": "评分理由 ≥10 字（综合证据/差异化/场景匹配/复购关联/合规）",
      "core_keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
      "matched_scenario": "具体可视化使用场景一句话",
      "match_reason": "为什么这个场景最能放大该显性卖点",
      "summary_30char": "30 字内说明这个卖点为什么成立",
      "tags": ["#显性", "#合规风险_中"]
    }}
  ],

  "usp_implicit": [
    {{
      "point": "隐性卖点名称",
      "evidence": "引用哪条用户评价原文/反馈/使用细节",
      "priority": 1,
      "discovery_difficulty": "一用就懂|用3次才懂|对比才懂",
      "rebuy_correlation": "强|中|弱",
      "strength_score": 4,
      "strength_reason": "...",
      "core_keywords": ["...", "...", "...", "...", "..."],
      "matched_scenario": "具体可视化生活场景一句话",
      "match_reason": "...",
      "summary_30char": "30 字内说明为什么会影响复购",
      "tags": ["#隐性", "#关联复购_强"]
    }}
  ],

  "usp_unique_candidates": [
    {{
      "candidate": "USP 候选一句话表述（≤15 字）",
      "exclusivity_basis": "为什么只有你能说（原料/产地/工艺/规格/历史/认证/地理标志/工厂/专利/创始人/非遗）",
      "competitor_check": "罗列 2-3 个主要竞品是否也能讲同样的话",
      "conclusion": "成立|不成立|需要补证据"
    }}
  ],

  "usp_unique": [
    {{
      "point": "推荐主打 USP（1 条）",
      "evidence": "为什么选它而不选另一条候选",
      "priority": 1,
      "selection_reason": "...",
      "tags": ["#USP", "#排他性_成立"]
    }}
  ],

  "not_recommended_usp": [
    {{
      "point": "不建议主打的卖点名称",
      "reason": "为什么不适合作为核心卖点",
      "risk_type": "品类泛滥|证据不足|合规风险|价格带冲突|竞品同质化|评价不支持",
      "handling": "删除|降级为辅助信息|需补证据后再判断"
    }}
  ],

  "mind_levels": {{
    "use_scenarios": [
      {{"scenario": "早餐佐粥", "penetration": "高|中|低|未渗透", "tags": ["#使用场景_早餐佐粥", "#渗透率_高"]}}
    ],
    "scenario_mind": [
      {{
        "scenario": "...",
        "match_reason": "产品属性与场景需求的匹配度",
        "competitive_landscape": "空位|红海|被占",
        "competitors": ["竞品 A", "竞品 B"],
        "leverage_usp": "对应第 1 部分哪条卖点",
        "tags": ["#场景心智_xx", "#占位格局_空位"]
      }}
    ],
    "content_mind": [
      {{
        "theme": "家常做饭|一人食|家人餐桌|宝妈辅食|减脂餐|露营野炊|中式快手菜|地域小吃|奶奶/妈妈的味道|从田间到餐桌|工艺溯源",
        "fit_point": "产品的什么属性对应母题的什么情绪",
        "conflict_point": "如有明显不契合也诚实指出，否则空字符串",
        "tags": ["#内容心智_xx"]
      }}
    ],
    "product_mind": [
      {{
        "need_expression": "凉拌必备的醋|蘸饺子的醋|下饭神器|咸菜佐粥神器|日式家常味|送长辈有面子的|家的味道|减盐不减鲜|纯酿不勾兑",
        "occupation_status": "已占位|正在占位|尚无占位|被竞品占位",
        "competitor_holding": "如果被竞品占位，列出是谁；否则空字符串",
        "gap": "如果目标抢占，当前距离心智还差什么（原料？工艺？认知？渠道铺货？）",
        "tags": ["#产品心智_xx", "#占位状态_xx"]
      }}
    ],
    "brand_mind": {{
      "currently_held": "基于现有资料能证明的当前已占住的品牌心智（老字号传承|区域正宗|医食同源|匠人手作|现代轻食|家常家味|极致性价比|精致生活|地方风味挖掘）",
      "potential_to_hold": "有潜力占住但尚未占住的",
      "missing_evidence": "缺什么证据/资产才能占住",
      "do_not_hold": "不建议强行占位的",
      "do_not_reason": "硬占会遇到什么天然冲突",
      "tags": ["#品牌心智_xx", "#占位_可"]
    }}
  }},

  "tag_summary": {{
    "category": ["#调味品", "#日式酱油", "#有机"],
    "explicit_usp": ["#显性_零添加", "#显性_玻璃瓶"],
    "implicit_usp": ["#隐性_180天发酵"],
    "usp_main": ["#USP_33年老北京日式工艺"],
    "use_scenarios": ["#使用场景_早餐佐粥", "#使用场景_凉拌"],
    "scenario_mind": ["#场景心智_厨房调味"],
    "content_mind": ["#内容心智_家常做饭"],
    "product_mind": ["#产品心智_纯酿不勾兑"],
    "brand_mind": ["#品牌心智_老字号传承"],
    "compliance_risk": ["#合规风险_有机_低"]
  }},

  "info_gaps": [
    {{
      "missing": "缺失的信息",
      "why_needed": "为什么需要它（影响哪一节的判断深度）",
      "where_to_get": "用户调研|客服记录|竞品详情页|天猫京东评价导出|行业报告|实地工厂走访"
    }}
  ]
}}
```

## 输出前自检（自检不通过先修正再输出）

1. 是否出现了目标人群画像、年龄、职业、圈层、城市层级等人群推断？有则删除。
2. 是否写了标题、口播、脚本、钩子、CTA、投放渠道或内容形式？有则删除。
3. 是否把品类共性当成了产品独特卖点？有则降级为显性或删除。
4. 是否每个显性/隐性卖点都有 5 个核心关键词和 1 个匹配场景？没有则补全。
5. 是否每个显性/隐性卖点都有卖点强度评分，并说明评分理由？没有则补全。
6. 是否每个匹配场景后都有匹配理由？没有则补全。
7. 是否所有 USP 候选都做了排他性检验和竞品反证检查？没有则补全。
8. 是否存在没有证据支撑的判断？有则标"信息不足"或"需补证据"，不要编。
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

    kb_ids = await _tri_kb_ids_async()
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

    kb_ids = await _tri_kb_ids_async()
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

    kb_ids = await _tri_kb_ids_async()
    snippets: list[dict] = []
    if kb_ids.get("ocean_engine"):
        # 多 query 召回再去重：操作向 + 5A 推送向 + 人群洞察向
        all_hits: list[dict] = []
        seen_ids: set[str] = set()
        for q in [
            "巨量云图 标签工厂 圈包 操作 step-by-step 自定义人群",
            "5A 人群资产 圈选 自定义人群 创建 推送 千川",
            "云图 人群洞察 标签 兴趣 行为 排除 预估包大小",
        ]:
            hits = await _retrieve_kb(kb_ids["ocean_engine"], q, top_k=6)
            for h in hits:
                cid = str(h.get("id") or h.get("chunk_id") or "")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_hits.append(h)
        snippets = all_hits[:12]  # 合并后限 12 条
    kb_block = format_kb_snippets(snippets) if snippets else "（云图 KB 无召回）"

    prompt = f"""你是巨量云图 DMP 圈包专家。给一个**完全不会用云图**的小白写一份从打开云图到圈包成功的全步骤手册。

## 人群画像
{json.dumps(profile, ensure_ascii=False, indent=2)}

## 云图知识库使用强约束（重要：覆盖任何"无效召回"的判断）

下面 `<kb_context>` 里的 chunks 是**云图官方 Playbook 操作步骤**（标签工厂 / 自定义人群 / 5A 资产 / 人群圈选 / 推送千川等）。

1. **必须使用** KB 里的**真实菜单路径、按钮名、字段名、操作动词** —— 不要凭空编菜单
2. KB 里提到的云图功能名词**原样保留**：「标签工厂」「自定义人群」「自定义人群分析」「5A 人群资产」「人群圈选」「标签圈选」「人群洞察」「人群夹」「关系资产」等
3. **特别注意**：KB chunks 来自不同行业的 Playbook（汽车/餐饮/通用），但**操作步骤本身是云图通用的** —— 你要做的是把这些 Playbook 的操作步骤**套用到当前调味品有机酱油** 上，不要因为 KB 不是调味品行业就判断为"无效召回"
4. 每步引用 KB 时用格式：`参考云图 KB: {{id前8位}}` 或 `[KB:{{id前8位}}#章节]`
5. **禁止编造**云图里不存在的菜单或功能名 —— 不确定就用 KB 里的原词

## 云图知识库召回内容（chunks）
{kb_block}

{NO_AI_SLANG}

## 输出要求

**写成 step 1, step 2... 的操作手册**，必须有 10 步左右，每步含 4 项：
- (a) **菜单路径**：在云图哪个页面 / 点哪个按钮（具体到 tab 名）
- (b) **选什么填什么**：标签具体值、过滤条件、数字范围
- (c) **为啥这么做**：让小白理解原理（这步对人群质量的影响）
- (d) **看哪里验证**：完成后界面什么变化（包大小变了 / 标签数量变了 / 人群预览长啥样）

10 步覆盖：
1. 登录入口 + 进入"人群洞察 → 人群圈选"模块的菜单路径
2. 选基础人群（性别 / 年龄 / 城市 / 设备）每项给具体值 + 解释
3. 加兴趣行为标签（带具体 tab 路径，如"食品 → 调味品 → 酱油"）
4. 加 5A 资产人群交叉（A1-A5 哪几级合适 + 为啥这级）
5. 加排除条件（已购 / 反感 / 黑名单 + 怎么导入排除包）
6. 看预估包大小（在哪显示 / 多大算合适 / 太小怎么放宽 / 太大怎么收紧）
7. 保存到"我的人群"（命名规则建议，如"sku-X-曝光-A2A3-202605"）
8. 复制到千川 / 抖加做投放（哪步导出 / 怎么对齐定向 / 包同步频率）
9. 触达节奏（每周触达 N 次 / 停留 N 天 / 反感后多久可重新触达）
10. 数据反馈看哪几个指标（CTR / CVR / 5A 资产流转率 + 在云图哪个报表查）

## 风格强制
- 每步开头用具体动词（"打开""点击""勾选""填入""保存"），不用"建议""可以"
- 数字必须具体（不写"较多"，写"500-2000 万"；不写"频次合适"，写"每周 2-3 次"）
- 引用 KB 内容标注 "（参考云图 KB）"
- 用"咱""你"，不用"用户""贵司"

## 输出格式
纯 markdown 文本，可直接放入 brief.dmp_sop 字段。**长度 800-1500 字**。直接输出 markdown，不要前后引号或代码块。
"""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                _hub_chat_url(),
                json={
                    "provider": "gemini",
                    "model": "gemini-3-flash-preview",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 3000,
                },
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

    kb_ids = await _tri_kb_ids_async()
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
