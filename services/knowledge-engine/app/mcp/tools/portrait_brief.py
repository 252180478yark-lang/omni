"""sku-pipeline step 3.5 + 3.6：人群生活状态画像 + 编导 brief。

- generate_audience_portrait：老板选中 audience_record → 四路定向 KB 召回 →
  生活状态画像（可信度分级标注）+ 专属卖点重构 + 情绪触点矩阵 → 落 pipeline.audience_portraits
- generate_director_brief：画像 → V7.2 产品化编导备忘录（一件事/起伏≠反转/卖点种情绪/
  算法信号三向量/可选 AI 出片提示词）→ 落 pipeline.scripts kind='director_brief'

设计 spec：docs/superpowers/specs/2026-06-11-audience-portrait-director-brief-design.md
"""
from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

from app.database import get_pool
from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.mcp.tools.media import (
    AUDIENCE_KB_ID,
    _format_kb_recall,
    _multi_query_recall,
)
from app.services import pipeline_lineage, rag_chain
from app.services.ai_hub_client import AIHubClient

# ============ step 3.5 检索 ============

# 路②固定生活维度后缀（spec §4.2）
_LIFE_DIMENSIONS = [
    "日常作息", "内容偏好", "触媒习惯", "消费决策", "价格敏感",
    "家庭角色", "节点场景", "兴趣爱好", "标签云", "热点内容", "BGM 偏好",
]
_EMOTION_CROWDS = [
    "一触即疯", "怀旧梦核", "血脉觉醒", "打破诡谲",
    "多巴胺爽感", "唤醒自愈", "重塑内核", "超绝松弛感",
]


async def _portrait_recall(record: dict, matrix_md: str) -> tuple[str, dict]:
    """四路定向召回（spec §4.2 表），返回 (kb_recall_md, recall_meta)。"""
    name = record.get("name") or ""
    kb_doc = record.get("kb_doc") or ""
    layer_tags = record.get("layer_tags") or []

    # 路①：本圈层深挖 —— 直打来源文档，context_window 拉邻块（≤30）
    route1_queries = [q for q in dict.fromkeys([f"{kb_doc} {name}".strip(), name]) if q]
    route1: list[dict] = []
    for q in route1_queries:
        try:
            hits = await rag_chain.retrieve_multi_kb(
                q, [AUDIENCE_KB_ID],
                top_k_per_kb=15, total_limit=15,
                rerank=True, context_window=True,
            )
            for h in hits:
                h.setdefault("query_origin", q)
            route1.extend(hits)
        except Exception:
            logger.exception("portrait route1 recall failed: %s", q)
    seen: set = set()
    route1_dedup = []
    for h in route1:
        if h.get("id") in seen:
            continue
        seen.add(h.get("id"))
        route1_dedup.append(h)
    route1_dedup = route1_dedup[:30]

    # 路②：生活维度扫描（≤24）
    route2_queries = [f"{name} {d}" for d in _LIFE_DIMENSIONS]
    for tag in layer_tags[:2]:
        route2_queries += [f"{tag} 内容偏好", f"{tag} 消费决策"]

    # 路③：八大情绪交叉（≤12）
    route3_queries = [f"{name} {e}" for e in _EMOTION_CROWDS[:4]] + [
        "8大情绪人群 " + name,
        "情绪人群 画像 " + (layer_tags[0] if layer_tags else "食饮"),
    ]

    # 路④：卖点反打 —— 从 matrix 抓 USP/推荐主打行做 query（≤12）
    usp_lines = re.findall(r"(?:USP|推荐主打)[^\n]{0,60}", matrix_md or "")[:4]
    route4_queries = [re.sub(r"[#*`\[\]【】]", " ", l).strip() for l in usp_lines if l.strip()]

    async def _maybe_recall(queries: list[str], max_chunks: int) -> list[dict]:
        if not queries:
            return []
        return await _multi_query_recall(
            queries=queries, kb_id=AUDIENCE_KB_ID,
            top_k_per_query=2, max_chunks=max_chunks,
        )

    route2, route3, route4 = await asyncio.gather(
        _maybe_recall(route2_queries, 24),
        _maybe_recall(route3_queries, 12),
        _maybe_recall(route4_queries, 12),
    )

    # 合并去重（路① 优先保留）
    merged: list[dict] = []
    seen2: set = set()
    for h in route1_dedup + route2 + route3 + route4:
        if h.get("id") in seen2:
            continue
        seen2.add(h.get("id"))
        merged.append(h)

    meta = {
        "mode": "four_route",
        "routes": {
            "circle_deep": len(route1_dedup),
            "life_dims": len(route2),
            "emotion_cross": len(route3),
            "usp_resonance": len(route4),
        },
        "queries": route1_queries + route2_queries + route3_queries + route4_queries,
        "chunk_count": len(merged),
    }
    return _format_kb_recall(merged), meta


# ============ 确定性校验 ============

_KB_MARK_RE = re.compile(r"\[KB[:：][^\]]+\]")
_INFER_MARK_RE = re.compile(r"🧠")
_SPECULATE_MARK_RE = re.compile(r"⚠️?\s*推测")


def _validate_portrait_markers(portrait_md: str) -> list[str]:
    """标记配额闸（spec §4.2 防臆想三道闸之二）。返回警告列表（空 = 过）。"""
    warnings: list[str] = []
    m = re.search(
        r"^#{1,6}[^\n]*第\s*1\s*部分(.*?)(?=^#{1,6}[^\n]*第\s*2\s*部分|\Z)",
        portrait_md, re.S | re.M,
    )
    if not m:
        m = re.search(r"第\s*1\s*部分(.*?)(?=第\s*2\s*部分|$)", portrait_md, re.S)
    section1 = m.group(1) if m else portrait_md
    kb_n = len(_KB_MARK_RE.findall(section1))
    infer_n = len(_INFER_MARK_RE.findall(section1))
    spec_total = len(_SPECULATE_MARK_RE.findall(portrait_md))
    marked = kb_n + infer_n + len(_SPECULATE_MARK_RE.findall(section1))
    if marked == 0:
        warnings.append("⚠ 第 1 部分没有任何可信度标记（[KB:]/🧠/⚠️），违反防臆想铁律，建议重跑")
    elif kb_n / marked < 0.5:
        warnings.append(
            f"⚠ 第 1 部分 [KB:] 占比 {kb_n}/{marked} 不足 50%——检索没召回到足够的料，"
            "建议补圈层 KB 后重跑（不要硬用）"
        )
    if spec_total > 5:
        warnings.append(f"⚠ 全文 ⚠️推测 共 {spec_total} 处（>5），该人群 KB 料薄，建议补料后重跑")
    return warnings


# V7.2 禁用词 8 类（确定性扫描；标题/正文/置顶都查）。
# 完整 8 类清单以 config/prompts/director_brief.system.md「禁用词」节为准——
# 这里只收"裸子串匹配不误伤"的子集，改任一边记得对照另一边防漂移。
_BANNED_WORDS = [
    "品质生活", "匠心", "臻选", "焕新", "赋能", "甄选", "尊享",
    "家人们", "宝子们", "绝绝子", "YYDS", "闭眼入",
    "不买后悔", "手慢无", "赶紧下单", "你值得拥有", "无限回购",
    "治疗", "治愈", "预防疾病", "抗癌", "排毒", "杀菌", "消炎",
    "劣质", "有毒", "黑心", "致癌", "科技与狠活",
    "全网最低", "双击666", "点赞关注不迷路", "评论区扣1",
]
_BRIEF_REQUIRED_SECTIONS = ["第 0 部分", "第 1 部分", "第 2 部分", "第 3 部分", "第 4 部分"]


def _validate_brief(brief_md: str, *, include_ai_mapping: bool) -> list[str]:
    """brief 结构 + 禁用词确定性校验。返回警告列表（空 = 过）。"""
    warnings: list[str] = []
    for sec in _BRIEF_REQUIRED_SECTIONS:
        if sec not in brief_md:
            warnings.append(f"⚠ 缺「{sec}」——结构不完整，建议重跑")
    if include_ai_mapping and "第 5 部分" not in brief_md:
        warnings.append("⚠ include_ai_mapping=True 但缺「第 5 部分」AI 出片提示词，建议重跑")
    if "自检" not in brief_md:
        warnings.append("⚠ 缺尾部自检段——可能输出被截断，建议重跑或调低篇幅")
    hits = [w for w in _BANNED_WORDS if w in brief_md]
    # "治愈系"是合法内容风格词（人群内容偏好高频），只拦裸"治愈"（医疗宣称语境）
    if "治愈" in hits and not re.search(r"治愈(?!系)", brief_md):
        hits.remove("治愈")
    if hits:
        warnings.append(f"⚠ 命中禁用词：{hits}——人工复核或重跑")
    return warnings


# ============ step 3.5 tool ============

@tool_with_audit(mcp, require_approval=False)
async def generate_audience_portrait(
    audience_record_id: str,
    extra_context: str | None = None,
    kb_recall_override: str | None = None,
) -> dict:
    """生成人群生活状态画像（sku-pipeline step 3.5）。

    输入老板从 step 3 选中的 audience_record，对该人群做四路定向 KB 二次召回
    （本圈层深挖 / 生活维度扫描 / 八大情绪交叉 / 卖点反打），输出 5 部分画像：

    - 第 0 部分：人群速写
    - 第 1 部分：生活状态画像（时间轴/场景库/触媒+算法信号原料/消费决策/情绪底色）
    - 第 2 部分：该人群专属卖点重构（三层拆解 + 对这群人说的那句话）
    - 第 3 部分：情绪触点矩阵（正向/负向阻断+化解/触达时间窗）
    - 第 4 部分：信息缺口

    防臆想铁律：每句标 [KB:文档名] / 🧠推演 / ⚠️推测；配额闸超标会在
    validation_warnings 里提示补 KB 重跑。

    返回后自动落库 pipeline.audience_portraits（draft，多版本不覆盖）。

    Args:
        audience_record_id: step 3 落库的人群 record id（老板选中的那个）
        extra_context: 一次性临时要求（如"重点写她周末的状态"）
        kb_recall_override: 显式覆盖 KB 召回（老板手贴 chunks 时用）

    Returns:
        {ok, result: {portrait_md, portrait_id, sku_id, audience_record_id,
         recall_meta, validation_warnings}, trace, next_step_hint(generate_director_brief)}
    """
    record = await pipeline_lineage.get_audience_record(audience_record_id)
    if not record:
        return {
            "ok": False,
            "error": f"audience_record 未找到: {audience_record_id}",
            "hint": "先跑 generate_audience_match（step 3），或调 pipeline_list_audience_records 看现有 record",
        }
    sku_id = record.get("sku_id")
    matrix_run_id = record.get("matrix_run_id")
    audience_run_id = record.get("audience_run_id")

    matrix_run = await pipeline_lineage.get_matrix_run(matrix_run_id) if matrix_run_id else None
    matrix_md = (matrix_run or {}).get("matrix_md") or ""
    if not matrix_md:
        return {
            "ok": False,
            "error": f"该 record 的上游卖点矩阵缺失（matrix_run_id={matrix_run_id}）",
            "hint": "链路断了：先跑 step 2 generate_selling_points_matrix",
        }

    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT id, name, category, price_min, price_max, specifications, "
        "owner_selling_points, platform_status, growth_class "
        "FROM mvp_sku WHERE id = $1",
        sku_id,
    )
    sku_md = (
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '（未分类，调味品）'}\n"
        f"- 规格：{sku['specifications'] or '（无）'}\n"
    ) if sku else f"- sku_id：{sku_id}（mvp_sku 查无，仅按矩阵推进）\n"

    # === 检索 ===
    if kb_recall_override and kb_recall_override.strip():
        kb_recall_md = kb_recall_override.strip()
        recall_meta = {"mode": "override", "queries": [], "chunk_count": 0}
    else:
        kb_recall_md, recall_meta = await _portrait_recall(record, matrix_md)

    # === LLM ===
    reasons = record.get("match_reasons") or []
    reasons_md = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(reasons)) or "  （无）"
    sys_msg = prompts.load("audience_portrait.system")
    user_msg = prompts.render(
        "audience_portrait.user",
        sku_md=sku_md,
        matrix_md=matrix_md.strip(),
        audience_name=record.get("name") or "（未命名）",
        audience_kb_doc=record.get("kb_doc") or "（无）",
        audience_layer_tags=" / ".join(record.get("layer_tags") or []) or "（无）",
        audience_match_reasons_md=reasons_md,
        audience_kb_chunk=(record.get("kb_chunk_text") or "（无）").strip(),
        kb_recall=kb_recall_md,
        extra_context=extra_context.strip() if extra_context else "（无）",
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model_for_tool("generate_audience_portrait")
    # 2026-06-12 300→360：给足 hub 代理重试预算（同 generate_audience_match 注释）
    client = AIHubClient(timeout=360.0)
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3.1-pro-preview"),
        temperature=model_cfg.get("temperature", 0.4),
        max_tokens=model_cfg.get("max_tokens", 10000),
        enforce_human_voice=True,
    )
    portrait_md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()

    validation_warnings = _validate_portrait_markers(portrait_md)

    portrait_id = await pipeline_lineage.save_audience_portrait(
        audience_record_id=audience_record_id,
        audience_run_id=audience_run_id,
        matrix_run_id=matrix_run_id,
        sku_id=sku_id,
        portrait_md=portrait_md,
        recall_meta=recall_meta,
        validation_warnings=validation_warnings,
        extra_context=extra_context,
        kb_recall_override=kb_recall_override,
        model_provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3.1-pro-preview"),
        final_prompt=final_prompt,
        cost_estimate="1 quota call (~30-50k input + 6-10k output tokens) + 四路定向 KB 召回",
    )
    if not portrait_id:
        validation_warnings = list(validation_warnings) + [
            "⚠ 画像未成功落库（portrait_id 为空，可能输出为空或 DB 异常）——别直接调 step 3.6，先重跑本步"
        ]

    result = {
        "ok": True,
        "result": {
            "portrait_md": portrait_md,
            "portrait_id": portrait_id,
            "sku_id": sku_id,
            "audience_record_id": audience_record_id,
            "audience_name": record.get("name"),
            "recall_meta": recall_meta,
            "validation_warnings": validation_warnings,
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3.1-pro-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.4),
                "max_tokens": model_cfg.get("max_tokens", 10000),
                "audience_kb_id": AUDIENCE_KB_ID,
                "queries_used": len(recall_meta.get("queries") or []),
                "chunks_recalled": recall_meta.get("chunk_count"),
                "portrait_id": portrait_id,
            },
            cost_estimate="1 quota call (~30-50k input + 6-10k output tokens) + 四路定向 KB 召回",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_director_brief",
        suggested_args={"portrait_id": portrait_id},
        human_text="step 3.6 编导 brief — 老板审完画像（生活状态贴不贴真实、卖点重构对不对味）后，"
                   "调 generate_director_brief 出编导备忘录（可传 idea_seed='想拍的事'）",
    )


# ============ step 3.6 tool ============

@tool_with_audit(mcp, require_approval=False)
async def generate_director_brief(
    portrait_id: str,
    idea_seed: str | None = None,
    include_ai_mapping: bool = True,
    ai_prompt_count: int | None = None,
    target_model: str = "generic",
    extra_context: str | None = None,
    num_variants: int = 1,
) -> dict:
    """生成编导备忘录（sku-pipeline step 3.6）。

    输入 step 3.5 的人群画像，输出 V7.2 风格「今天拍什么」备忘录（真人编导直接能拍）：
    第 0 人群描述 / 第 1 今天拍什么（一件事+两次偏+卖点藏哪）/ 第 2 分段拍摄备忘 /
    第 3 算法信号三向量（画面/文案/音乐，让抖音算法把内容映射对人群）/ 第 4 发的时候 /
    第 5 AI 出片提示词（一大段故事描述，可关；ai_prompt_count 控制拆几大块，按模型实测调）/ 尾部 12 项自检。

    落库 pipeline.scripts（kind='director_brief'，挂 portrait_id 全血缘，多版本不覆盖）。

    Args:
        portrait_id: step 3.5 落库的画像 id
        idea_seed: 可选"想拍的事"（如"闺女给妈寄酱油"）；不给则 LLM 从画像场景库自选一件事
        include_ai_mapping: 默认 True 带第 5 部分 AI 出片提示词；False 省 token
        ai_prompt_count: 第 5 部分拆几大块提示词（None=按目标模型档案的单次生成时长自行定块数并说明；显式传值强制）
        target_model: 目标出片模型（generic/veo/seedance/jimeng，对应 config/prompts/video_model_profiles/<model>.md 档案；未知名回退 generic）
        extra_context: 一次性临时要求
        num_variants: 1-3 个创意方案并行（temperature 递增 +0.1）

    Returns:
        {ok, result: {variants:[{script_id, brief_md, variant_label, validation_warnings}],
         sku_id, portrait_id}, trace, usage_note}
    """
    portrait = await pipeline_lineage.get_audience_portrait(portrait_id)
    if not portrait:
        return {
            "ok": False,
            "error": f"portrait 未找到: {portrait_id}",
            "hint": "先跑 generate_audience_portrait（step 3.5），或查 pipeline.audience_portraits",
        }
    sku_id = portrait.get("sku_id")
    record = await pipeline_lineage.get_audience_record(portrait["audience_record_id"])
    audience_name = (record or {}).get("name") or "（未命名人群）"

    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT id, name, category, specifications FROM mvp_sku WHERE id = $1", sku_id
    )
    sku_md = (
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '（未分类，调味品）'}\n"
        f"- 规格：{sku['specifications'] or '（无）'}\n"
    ) if sku else f"- sku_id：{sku_id}\n"

    if not include_ai_mapping:
        ai_directive = "本次任务**不要输出第 5 部分**（整节跳过、连标题都不写；自检照常 12 项）。"
        _pc = None
    elif ai_prompt_count is None:
        ai_directive = (
            "本次任务**要求输出第 5 部分 AI 出片提示词**：拆块数**按下方模型档案的单次生成时长自行决定**"
            "（总时长 ÷ 单次时长向上取整），并在第 5 部分开头一句话说明\"按 X 模型单次约 Ns，拆 N 块\"。"
            "每块标题 `### 提示词块 X（时间范围）`，块开头重述人物外观+场景+风格锚，块内连续故事描述，块尾写结束帧状态。"
        )
        _pc = None
    else:
        _pc = max(1, min(10, int(ai_prompt_count)))
        if _pc == 1:
            ai_directive = (
                "本次任务**要求输出第 5 部分 AI 出片提示词**：整条视频写成 **1 大段**连续故事描述"
                "（英文，细节拉满，时间戳贯穿，真人感锚内嵌，段尾负向词）。"
            )
        else:
            ai_directive = (
                f"本次任务**要求输出第 5 部分 AI 出片提示词**：按时间均分拆成 **{_pc} 大块**"
                "（每块标题 `### 提示词块 X（时间范围）`，块开头重述人物外观+场景+风格锚，"
                "块内仍是连续故事描述，块尾写结束帧状态）。"
            )

    _tm = (target_model or "generic").strip().lower()
    try:
        target_model_profile = prompts.load(f"video_model_profiles/{_tm}")
    except FileNotFoundError:
        logger.warning("video_model_profile 未找到: %s，回退 generic", _tm)
        _tm = "generic"
        target_model_profile = prompts.load("video_model_profiles/generic")

    sys_msg = prompts.load("director_brief.system")
    user_msg = prompts.render(
        "director_brief.user",
        sku_md=sku_md,
        audience_name=audience_name,
        portrait_md=(portrait.get("portrait_md") or "").strip(),
        idea_seed=idea_seed.strip() if idea_seed else "（无）",
        ai_mapping_directive=ai_directive,
        target_model_profile=target_model_profile,
        extra_context=extra_context.strip() if extra_context else "（无）",
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model_for_tool("generate_director_brief")
    _n = max(1, min(3, int(num_variants or 1)))
    _base_temp = float(model_cfg.get("temperature", 0.7))
    _provider = model_cfg.get("provider", "gemini")
    _model = model_cfg.get("model", "gemini-3.1-pro-preview")
    _max_tokens = model_cfg.get("max_tokens", 12000)

    async def _call_one(variant_idx: int) -> dict:
        temp = round(_base_temp + variant_idx * 0.1, 2)
        # 2026-06-12 300→360：给足 hub 代理重试预算（同 generate_audience_match 注释）
        _client = AIHubClient(timeout=360.0)
        _resp = await _client.chat(
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            provider=_provider,
            model=_model,
            temperature=temp,
            max_tokens=_max_tokens,
            enforce_human_voice=True,
        )
        md = (
            ((_resp.get("choices") or [{}])[0].get("message") or {}).get("content")
            or _resp.get("text")
            or _resp.get("content")
            or ""
        ).strip()
        warnings = _validate_brief(md, include_ai_mapping=include_ai_mapping)
        sid = await pipeline_lineage.save_creative_pack(
            sku_id=sku_id,
            kind="director_brief",
            script_md=md,
            audience_record_id=portrait.get("audience_record_id"),
            audience_run_id=portrait.get("audience_run_id"),
            matrix_run_id=portrait.get("matrix_run_id"),
            portrait_id=portrait_id,
            extra_context=extra_context,
            model_provider=_provider,
            model=_model,
            final_prompt=final_prompt,
            cost_estimate=f"1 quota call (~10-20k input + 6-12k output tokens, temp={temp})",
        )
        if not sid:
            warnings = list(warnings) + ["⚠ brief 未成功落库（script_id 为空）——重跑本步，别直接拿去拍"]
        label = chr(ord("A") + variant_idx)
        return {
            "script_id": sid,
            "brief_md": md,
            "variant_label": f"方案 {label}",
            "validation_warnings": warnings,
        }

    raw_variants = await asyncio.gather(*[_call_one(i) for i in range(_n)])
    variants = list(raw_variants)

    result = {
        "ok": True,
        "result": {
            "variants": variants,
            "sku_id": sku_id,
            "portrait_id": portrait_id,
            "audience_name": audience_name,
            "include_ai_mapping": include_ai_mapping,
        },
        "trace": build_trace(
            provider=_provider,
            model=_model,
            prompt=final_prompt,
            params={
                "temperature": _base_temp,
                "max_tokens": _max_tokens,
                "num_variants": _n,
                "include_ai_mapping": include_ai_mapping,
                "ai_prompt_count": _pc,
                "target_model": _tm,
                "idea_seed": idea_seed,
            },
            cost_estimate=f"{_n} quota call(s) (~10-20k input + 6-12k output tokens each)",
        ),
    }
    result["result"]["target_model"] = _tm
    if include_ai_mapping:
        result["result"]["usage_note"] = (
            f"真人拍 → brief 第 0-4 部分直接发编导；AI 拍 → 第 5 部分大段提示词复制喂 {_tm} 模型"
            "（块数/写法不满意：调 ai_prompt_count 或 target_model 重跑；模型档案在 "
            "config/prompts/video_model_profiles/ 热加载可改）"
        )
    return result
