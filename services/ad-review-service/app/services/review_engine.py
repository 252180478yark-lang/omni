"""投放复盘生成：按视频目的分类分析 + 保本计算 + 归因三步法 + 流式输出。"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

AI_HUB_BASE = settings.ai_hub_url.rstrip("/")
KE_BASE = settings.knowledge_engine_url.rstrip("/")
VA_BASE = settings.video_analysis_url.rstrip("/")

PURPOSE_LABELS = {
    "organic": "自然流量",
    "seeding": "种草",
    "conversion": "转化",
}

# Purpose-specific weight adjustments for video analysis dimensions.
# Base weights: hook_power=0.20, content_value=0.15, visual_quality=0.10,
# editing_rhythm=0.10, audio_bgm=0.10, copy_script=0.10,
# interaction_design=0.10, algorithm_friendliness=0.10, commercial_potential=0.05
PURPOSE_DIMENSION_WEIGHTS: dict[str, dict[str, float]] = {
    "organic": {
        "hook_power": 0.25,
        "content_value": 0.20,
        "visual_quality": 0.10,
        "editing_rhythm": 0.10,
        "audio_bgm": 0.10,
        "copy_script": 0.05,
        "interaction_design": 0.10,
        "algorithm_friendliness": 0.05,
        "commercial_potential": 0.05,
    },
    "seeding": {
        "hook_power": 0.20,
        "content_value": 0.15,
        "visual_quality": 0.10,
        "editing_rhythm": 0.10,
        "audio_bgm": 0.10,
        "copy_script": 0.10,
        "interaction_design": 0.10,
        "algorithm_friendliness": 0.10,
        "commercial_potential": 0.05,
    },
    "conversion": {
        "hook_power": 0.20,
        "content_value": 0.10,
        "visual_quality": 0.05,
        "editing_rhythm": 0.10,
        "audio_bgm": 0.05,
        "copy_script": 0.15,
        "interaction_design": 0.10,
        "algorithm_friendliness": 0.10,
        "commercial_potential": 0.15,
    },
}


async def generate_review(
    campaign: dict,
    audiences: list,
    materials: list,
    groups: list | None = None,
    prev_suggestions: list | None = None,
    kb_ids: list[str] | None = None,
) -> AsyncIterator[str]:
    groups = groups or []
    data_summary = _build_data_summary(campaign, audiences, materials, groups)
    video_insights = await _fetch_video_analyses(materials, groups)
    group_analysis = _build_group_iteration_analysis(campaign, audiences, materials, groups)
    cross_pack = _build_cross_pack_comparison(audiences, materials)
    rag_context = await _rag_search_experience(campaign, audiences, materials=materials, groups=groups, kb_ids=kb_ids)
    prev_suggestions_text = _build_suggestion_comparison(prev_suggestions or [], materials)

    # ── Stage A: Structured JSON diagnosis (non-streaming) ──
    stage_a_prompt = _build_stage_a_prompt(
        data_summary=data_summary,
        video_insights=video_insights,
        group_analysis=group_analysis,
        cross_pack=cross_pack,
        rag_context=rag_context,
        audiences=audiences,
        campaign=campaign,
        prev_suggestions_text=prev_suggestions_text,
    )
    diagnosis_json = await _call_llm_json(stage_a_prompt, n_materials=len(materials))
    if diagnosis_json is None:
        logger.warning("Stage A failed to produce valid JSON, falling back to single-pass")
        fallback_prompt = _build_review_prompt(
            data_summary=data_summary,
            video_insights=video_insights,
            group_analysis=group_analysis,
            cross_pack=cross_pack,
            rag_context=rag_context,
            audiences=audiences,
            campaign=campaign,
            prev_suggestions_text=prev_suggestions_text,
        )
        async for chunk in _stream_llm(fallback_prompt):
            yield chunk
        return

    # ── Stage B: Render Markdown from diagnosis (streaming, more tokens) ──
    stage_b_prompt = _build_stage_b_prompt(diagnosis_json, data_summary)
    async for chunk in _stream_llm(stage_b_prompt, temperature=0.15, max_tokens=16384):
        yield chunk


# ── Stage 1: Data Summary ────────────────────────────────────────────

def _build_data_summary(
    campaign: dict, audiences: list, materials: list, groups: list,
) -> str:
    total_cost = sum(float(m.get("cost") or 0) for m in materials)
    product_price = float(campaign.get("product_price") or 0)
    margin_rate = float(campaign.get("product_margin_rate") or 0)

    lines = [
        f"产品: {campaign['product_name']}",
        f"SKU: {campaign.get('product_sku') or '未填写'}",
        f"产品单价: ￥{product_price:.2f}" if product_price else "产品单价: 未设置",
        f"毛利率: {margin_rate:.1%}" if margin_rate else "毛利率: 未设置",
    ]
    if product_price and margin_rate:
        breakeven_per_unit = product_price * margin_rate
        lines.append(f"单件毛利: ￥{breakeven_per_unit:.2f}（保本线基础）")
    lines += [
        f"投放周期: {campaign['start_date']} ~ {campaign['end_date']}",
        f"总消耗: ￥{total_cost:.2f}",
        "",
    ]

    group_map = {str(g["id"]): g for g in groups}

    for aud in audiences:
        aud_id = str(aud["id"])
        aud_materials = [m for m in materials if str(m.get("audience_pack_id")) == aud_id]
        lines.append(f"## 人群包: {aud['name']}")
        lines.append(f"描述: {aud.get('description') or ''}")
        lines.append(f"素材数: {len(aud_materials)}")
        lines.append("")

        sorted_mats = sorted(aud_materials, key=lambda m: float(m.get("cost") or 0), reverse=True)
        for m in sorted_mats:
            ctr = float(m.get("ctr") or 0)
            cr = float(m.get("completion_rate") or 0)
            p3 = float(m.get("play_3s_rate") or 0)
            cvr = float(m.get("conversion_rate") or 0)
            cpm = float(m.get("cpm") or 0)
            a3r = float(m.get("a3_ratio") or 0)
            ir = float(m.get("interaction_rate") or 0)

            # Determine video purpose from group
            gid = str(m.get("group_id") or "")
            grp = group_map.get(gid)
            purpose = grp.get("video_purpose", "seeding") if grp else "seeding"
            purpose_label = PURPOSE_LABELS.get(purpose, purpose)

            base = (
                f"- [{purpose_label}] {m['name']}: 消耗￥{m.get('cost') or 0}, "
                f"展示{m.get('impressions') or 0}, CPM=￥{cpm:.2f}, "
                f"点击率{ctr:.2%}, 完播率{cr:.2%}, 3秒率{p3:.2%}"
            )

            if cvr > 0:
                if purpose == "seeding":
                    base += f", A3转化率{cvr:.2%}"
                else:
                    base += f", 转化率{cvr:.2%}"
            cost_per = m.get("cost_per_result")
            if cost_per is not None:
                if purpose == "seeding":
                    base += f", A3转化成本￥{float(cost_per):.2f}"
                else:
                    base += f", 转化成本￥{float(cost_per):.2f}"
            if purpose == "conversion" and cvr > 0 and ctr > 0 and cpm > 0:
                cost_per_conv = cpm / (ctr * 1000) / cvr
                if product_price and margin_rate:
                    roi_line = product_price * margin_rate
                    if cost_per_conv <= roi_line:
                        base += f" ✅保本(毛利￥{roi_line:.2f})"
                    else:
                        base += f" ❌亏损(毛利￥{roi_line:.2f})"
            if ir > 0:
                base += f", 互动率{ir:.2%}"

            lines.append(base)
        lines.append("")

    return "\n".join(lines)


# ── Stage 2: Video Analyses ──────────────────────────────────────────

def _compute_purpose_overall(dims: dict, purpose: str) -> float:
    """Compute purpose-weighted overall score from base dimension scores."""
    weights = PURPOSE_DIMENSION_WEIGHTS.get(purpose, PURPOSE_DIMENSION_WEIGHTS["seeding"])
    total = 0.0
    for dim_key, w in weights.items():
        dim = dims.get(dim_key)
        if isinstance(dim, dict):
            total += float(dim.get("score", 0)) * w
    return round(total, 1)


async def _fetch_video_analyses(materials: list, groups: list | None = None) -> str:
    groups = groups or []
    group_map = {str(g["id"]): g for g in groups}

    insights: list[str] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for m in materials:
            vid = m.get("video_analysis_id")
            if not vid:
                continue
            try:
                resp = await client.get(f"{VA_BASE}/api/v1/video-analysis/videos/{vid}")
                if resp.status_code != 200:
                    continue
                body = resp.json()
                report = body.get("report") or {}
                scores = report.get("scores") or {}
                dims = scores.get("dimensions") or {}
                ai_insights = report.get("ai_insights") or {}

                gid = str(m.get("group_id") or "")
                grp = group_map.get(gid)
                purpose = grp.get("video_purpose", "seeding") if grp else "seeding"
                purpose_label = PURPOSE_LABELS.get(purpose, purpose)

                base_overall = scores.get("overall", 0)
                purpose_overall = _compute_purpose_overall(dims, purpose)

                lines = [f"### 素材「{m['name']}」视频全维度分析（目的: {purpose_label}）"]
                lines.append(f"总分: {base_overall}/10 | {purpose_label}加权分: {purpose_overall}/10")

                dim_labels = {
                    "hook_power": "钩子力", "content_value": "内容价值",
                    "visual_quality": "画面质量", "editing_rhythm": "剪辑节奏",
                    "audio_bgm": "音频BGM", "copy_script": "文案脚本",
                    "interaction_design": "互动设计", "algorithm_friendliness": "算法友好",
                    "commercial_potential": "商业潜力",
                }
                purpose_weights = PURPOSE_DIMENSION_WEIGHTS.get(purpose, {})
                lines.append("**各维度评分:**")
                for dim_key, dim_val in dims.items():
                    if isinstance(dim_val, dict):
                        label = dim_labels.get(dim_key, dim_key)
                        pw = purpose_weights.get(dim_key, dim_val.get("weight", 0))
                        lines.append(
                            f"- {label}: {dim_val.get('score', 0)}/10 "
                            f"(权重{pw:.0%}) — {dim_val.get('brief', '')}"
                        )
                        detail = dim_val.get("detail", "")
                        if detail:
                            lines.append(f"  详细: {detail}")

                summary = report.get("summary", "")
                if summary:
                    lines.append(f"\n**视频概述:** {summary}")

                hook = ai_insights.get("hook_analysis") or {}
                if isinstance(hook, dict) and (hook.get("type") or hook.get("description")):
                    lines.append(f"**钩子分析:** [{hook.get('type', '')}] {hook.get('description', '')}")
                    if hook.get("effectiveness"):
                        lines.append(f"  钩子效果: {hook['effectiveness']}")

                scene = ai_insights.get("scene_analysis") or ai_insights.get("scene_description") or ""
                if isinstance(scene, dict):
                    lines.append("**场景分析:**")
                    for sk, sv in scene.items():
                        lines.append(f"  - {sk}: {sv}")
                elif scene:
                    lines.append(f"**场景描述:** {scene}")

                performance = ai_insights.get("performance") or ai_insights.get("performer_analysis") or {}
                if isinstance(performance, dict):
                    lines.append("**表演分析:**")
                    for pk, pv in performance.items():
                        lines.append(f"  - {pk}: {pv}")

                visual = ai_insights.get("visual_elements") or {}
                if isinstance(visual, dict):
                    lines.append("**画面元素:**")
                    for vk, vv in visual.items():
                        if isinstance(vv, list):
                            lines.append(f"  - {vk}: {', '.join(str(x) for x in vv)}")
                        else:
                            lines.append(f"  - {vk}: {vv}")
                elif isinstance(visual, list):
                    lines.append(f"**画面元素:** {', '.join(str(x) for x in visual)}")

                bgm = ai_insights.get("bgm_analysis") or ai_insights.get("audio_analysis") or {}
                if isinstance(bgm, dict):
                    lines.append("**BGM/音频分析:**")
                    for bk, bv in bgm.items():
                        lines.append(f"  - {bk}: {bv}")

                script = ai_insights.get("script_outline") or ai_insights.get("script_analysis") or ""
                if isinstance(script, list):
                    lines.append(f"**脚本结构:** {' → '.join(str(s) for s in script)}")
                elif isinstance(script, dict):
                    lines.append("**脚本结构:**")
                    for sk2, sv2 in script.items():
                        lines.append(f"  - {sk2}: {sv2}")
                elif script:
                    lines.append(f"**脚本结构:** {script}")

                emotion = ai_insights.get("emotion_curve") or []
                if isinstance(emotion, list) and emotion:
                    peaks = [e for e in emotion if isinstance(e, dict) and float(e.get("value", 0)) > 7]
                    lows = [e for e in emotion if isinstance(e, dict) and float(e.get("value", 0)) < 4]
                    if peaks:
                        peak_strs = [f"{e.get('time', '?')}s={e.get('value', '?')}" for e in peaks[:3]]
                        lines.append(f"**情绪高点:** {', '.join(peak_strs)}")
                    if lows:
                        low_strs = [f"{e.get('time', '?')}s={e.get('value', '?')}" for e in lows[:3]]
                        lines.append(f"**情绪低点:** {', '.join(low_strs)}")

                tags = ai_insights.get("semantic_tags") or []
                if isinstance(tags, list) and tags:
                    lines.append(f"**语义标签:** {', '.join(str(t) for t in tags)}")

                suggestions_obj = report.get("improvement_suggestions") or {}
                actions = suggestions_obj.get("priority_actions") or []
                if isinstance(actions, list) and actions:
                    lines.append("**优先改进建议:**")
                    for action in actions[:5]:
                        if isinstance(action, dict):
                            lines.append(f"  - [{action.get('urgency', '')}] {action.get('suggestion', '')}")
                        else:
                            lines.append(f"  - {action}")

                insights.append("\n".join(lines))
            except Exception as e:
                logger.warning("Failed to fetch video analysis %s: %s", vid, e)

    return "\n\n".join(insights) if insights else "（无关联视频分析数据）"


# ── Stage 3: Group-based Type-specific Analysis ─────────────────────

def _build_group_iteration_analysis(
    campaign: dict, audiences: list, materials: list, groups: list,
) -> str:
    by_id: dict[str, dict] = {str(m["id"]): m for m in materials}
    group_map: dict[str, dict] = {str(g["id"]): g for g in groups}
    aud_map: dict[str, str] = {str(a["id"]): a["name"] for a in audiences}
    sections: list[str] = []

    product_price = float(campaign.get("product_price") or 0)
    margin_rate = float(campaign.get("product_margin_rate") or 0)

    # Organize: audience_pack_id → group_id → materials
    aud_group_mats: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    ungrouped: dict[str, list] = defaultdict(list)

    for m in materials:
        aid = str(m.get("audience_pack_id") or "")
        gid = str(m.get("group_id") or "")
        if gid and gid in group_map:
            aud_group_mats[aid][gid].append(m)
        else:
            ungrouped[aid].append(m)

    for aid, grp_mats in aud_group_mats.items():
        aud_name = aud_map.get(aid, aid)
        for gid, mats in grp_mats.items():
            g = group_map[gid]
            style = g.get("style_label", "")
            purpose = g.get("video_purpose", "seeding")
            purpose_label = PURPOSE_LABELS.get(purpose, purpose)

            chains = _build_chains(mats, by_id)
            total_mats = len(mats)
            total_chains = len(chains)

            lines = [
                f"### 人群包「{aud_name}」· 风格组「{style}」· 目的【{purpose_label}】"
                f"（{total_mats}条素材，{total_chains}个变种）"
            ]

            # Type-specific summary metrics
            lines.append(_type_specific_summary(mats, purpose, product_price, margin_rate))
            lines.append("")

            effective_tags: list[str] = []
            ineffective_tags: list[str] = []

            for chain in chains:
                root_name = chain[0]["name"]
                if len(chain) == 1:
                    lines.append(
                        f"- {root_name}: {_type_specific_mat_line(chain[0], purpose, product_price, margin_rate)}"
                    )
                    continue

                lines.append(f"**变种: {root_name}**（{len(chain)}版）")
                for i, m in enumerate(chain):
                    if i == 0:
                        lines.append(
                            f"- v{m.get('version', 1)}: "
                            f"{_type_specific_mat_line(m, purpose, product_price, margin_rate)}"
                        )
                        continue
                    prev = chain[i - 1]
                    tags = _safe_tags(m.get("change_tags"))
                    tag_str = f"[{', '.join(tags)}]" if tags else ""

                    # Compare primary KPI based on purpose
                    delta_str = _type_specific_delta(prev, m, purpose, product_price, margin_rate)

                    for t in tags:
                        if _kpi_improved(prev, m, purpose):
                            if t not in effective_tags:
                                effective_tags.append(t)
                        elif _kpi_declined(prev, m, purpose):
                            if t not in ineffective_tags:
                                ineffective_tags.append(t)

                    note = m.get("iteration_note") or ""
                    note_str = f" — {note}" if note else ""
                    lines.append(
                        f"- v{prev.get('version', '?')}→v{m.get('version', '?')} {tag_str}: "
                        f"{delta_str}{note_str}"
                    )

            if effective_tags:
                lines.append(f"**✅ 有效策略**: {', '.join(effective_tags)}")
            if ineffective_tags:
                lines.append(f"**❌ 无效策略**: {', '.join(ineffective_tags)}")

            sections.append("\n".join(lines))

    # Ungrouped iteration diffs
    ungrouped_diffs: list[str] = []
    for aid, mats in ungrouped.items():
        for m in mats:
            pid = m.get("parent_material_id")
            if not pid or str(pid) not in by_id:
                continue
            parent = by_id[str(pid)]
            tags = _safe_tags(m.get("change_tags"))
            tag_str = f"[{', '.join(tags)}]" if tags else ""
            old_ctr = float(parent.get("ctr") or 0)
            new_ctr = float(m.get("ctr") or 0)
            delta = ""
            if old_ctr > 0:
                pct = (new_ctr - old_ctr) / old_ctr * 100
                delta = f"({'+'if pct > 0 else ''}{pct:.1f}%)"
            ungrouped_diffs.append(
                f"- {m['name']}(v{m.get('version', '?')}) vs {parent['name']}(v{parent.get('version', '?')}) "
                f"{tag_str}: CTR {old_ctr:.2%}→{new_ctr:.2%} {delta}"
            )

    if ungrouped_diffs:
        sections.append("### 未分组素材迭代\n" + "\n".join(ungrouped_diffs))

    return "\n\n".join(sections) if sections else "（本批次无分组或迭代素材）"


def _safe_tags(val: Any) -> list[str]:
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _type_specific_summary(mats: list, purpose: str, price: float, margin: float) -> str:
    """Aggregate summary for a group, tailored to video purpose."""
    n = len(mats)
    if n == 0:
        return ""

    if purpose == "organic":
        avg_cr = sum(float(m.get("completion_rate") or 0) for m in mats) / n
        avg_p3 = sum(float(m.get("play_3s_rate") or 0) for m in mats) / n
        avg_ir = sum(float(m.get("interaction_rate") or 0) for m in mats) / n
        total_plays = sum(int(m.get("plays") or 0) for m in mats)
        return (
            f"组均值: 完播率{avg_cr:.2%}, 3秒率{avg_p3:.2%}, 互动率{avg_ir:.2%}, "
            f"总播放量{total_plays:,}"
        )

    if purpose == "seeding":
        avg_cpm = sum(float(m.get("cpm") or 0) for m in mats) / n
        avg_ctr = sum(float(m.get("ctr") or 0) for m in mats) / n
        avg_cvr = sum(float(m.get("conversion_rate") or m.get("a3_ratio") or 0) for m in mats) / n
        avg_cpr = sum(float(m.get("cost_per_result") or 0) for m in mats) / n
        return (
            f"组均值: CPM=￥{avg_cpm:.2f}, 点击率{avg_ctr:.2%}, "
            f"A3转化率{avg_cvr:.2%}, A3转化成本￥{avg_cpr:.2f}"
        )

    # conversion
    avg_cpm = sum(float(m.get("cpm") or 0) for m in mats) / n
    avg_ctr = sum(float(m.get("ctr") or 0) for m in mats) / n
    cvrs = [float(m.get("conversion_rate") or 0) for m in mats if m.get("conversion_rate")]
    avg_cvr = sum(cvrs) / len(cvrs) if cvrs else 0.0
    profitable = 0
    for m in mats:
        cc = _conv_cost(m)
        if cc is not None and price and margin and cc <= price * margin:
            profitable += 1
    breakeven_str = ""
    if price and margin:
        breakeven_str = f", 保本素材{profitable}/{n}"
    return (
        f"组均值: CPM=￥{avg_cpm:.2f}, 点击率{avg_ctr:.2%}, 转化率{avg_cvr:.2%}"
        f"{breakeven_str}"
    )


def _conv_cost(m: dict) -> float | None:
    """Calculate single conversion cost: CPM / (CTR × 1000) / CVR."""
    cpm = float(m.get("cpm") or 0)
    ctr = float(m.get("ctr") or 0)
    cvr = float(m.get("conversion_rate") or 0)
    if cpm > 0 and ctr > 0 and cvr > 0:
        return cpm / (ctr * 1000) / cvr
    return None


def _type_specific_mat_line(m: dict, purpose: str, price: float, margin: float) -> str:
    """Single material one-liner, tailored to purpose."""
    ctr = float(m.get("ctr") or 0)
    cr = float(m.get("completion_rate") or 0)
    cpm = float(m.get("cpm") or 0)

    if purpose == "organic":
        p3 = float(m.get("play_3s_rate") or 0)
        ir = float(m.get("interaction_rate") or 0)
        return f"完播{cr:.2%}, 3秒率{p3:.2%}, 互动率{ir:.2%}, 播放{m.get('plays') or 0}"

    if purpose == "seeding":
        cvr = float(m.get("conversion_rate") or m.get("a3_ratio") or 0)
        cpr = m.get("cost_per_result")
        line = f"CPM=￥{cpm:.2f}, CTR={ctr:.2%}, A3转化率={cvr:.2%}"
        if cpr is not None:
            line += f", A3转化成本=￥{float(cpr):.2f}"
        return line

    # conversion
    cvr = float(m.get("conversion_rate") or 0)
    cc = _conv_cost(m)
    line = f"CPM=￥{cpm:.2f}, CTR={ctr:.2%}, CVR={cvr:.2%}"
    if cc is not None:
        line += f", 单转化成本￥{cc:.2f}"
        if price and margin:
            roi_line = price * margin
            line += f" {'✅' if cc <= roi_line else '❌'}(保本线￥{roi_line:.2f})"
    return line


def _type_specific_delta(prev: dict, cur: dict, purpose: str, price: float, margin: float) -> str:
    """Version-over-version delta, tailored to purpose."""
    if purpose == "organic":
        old_cr = float(prev.get("completion_rate") or 0)
        new_cr = float(cur.get("completion_rate") or 0)
        old_p3 = float(prev.get("play_3s_rate") or 0)
        new_p3 = float(cur.get("play_3s_rate") or 0)
        return (
            f"完播{old_cr:.2%}→{new_cr:.2%}, "
            f"3秒率{old_p3:.2%}→{new_p3:.2%}"
        )

    if purpose == "seeding":
        old_ctr = float(prev.get("ctr") or 0)
        new_ctr = float(cur.get("ctr") or 0)
        old_cpm = float(prev.get("cpm") or 0)
        new_cpm = float(cur.get("cpm") or 0)
        old_cvr = float(prev.get("conversion_rate") or prev.get("a3_ratio") or 0)
        new_cvr = float(cur.get("conversion_rate") or cur.get("a3_ratio") or 0)
        old_cpr = float(prev.get("cost_per_result") or 0)
        new_cpr = float(cur.get("cost_per_result") or 0)
        return (
            f"CTR {old_ctr:.2%}→{new_ctr:.2%}, "
            f"CPM ￥{old_cpm:.2f}→￥{new_cpm:.2f}, "
            f"A3转化率 {old_cvr:.2%}→{new_cvr:.2%}, "
            f"A3成本 ￥{old_cpr:.2f}→￥{new_cpr:.2f}"
        )

    # conversion
    old_cc = _conv_cost(prev)
    new_cc = _conv_cost(cur)
    old_ctr = float(prev.get("ctr") or 0)
    new_ctr = float(cur.get("ctr") or 0)
    old_cvr = float(prev.get("conversion_rate") or 0)
    new_cvr = float(cur.get("conversion_rate") or 0)
    line = f"CTR {old_ctr:.2%}→{new_ctr:.2%}, CVR {old_cvr:.2%}→{new_cvr:.2%}"
    if old_cc is not None and new_cc is not None:
        line += f", 转化成本￥{old_cc:.2f}→￥{new_cc:.2f}"
        if price and margin:
            roi = price * margin
            line += f" {'✅' if new_cc <= roi else '❌'}"
    return line


def _kpi_improved(prev: dict, cur: dict, purpose: str) -> bool:
    if purpose == "organic":
        return float(cur.get("completion_rate") or 0) > float(prev.get("completion_rate") or 0)
    if purpose == "seeding":
        return float(cur.get("ctr") or 0) > float(prev.get("ctr") or 0)
    # conversion: lower cost is better
    old_cc = _conv_cost(prev)
    new_cc = _conv_cost(cur)
    if old_cc is not None and new_cc is not None:
        return new_cc < old_cc
    return float(cur.get("ctr") or 0) > float(prev.get("ctr") or 0)


def _kpi_declined(prev: dict, cur: dict, purpose: str) -> bool:
    if purpose == "organic":
        return float(cur.get("completion_rate") or 0) < float(prev.get("completion_rate") or 0)
    if purpose == "seeding":
        return float(cur.get("ctr") or 0) < float(prev.get("ctr") or 0)
    old_cc = _conv_cost(prev)
    new_cc = _conv_cost(cur)
    if old_cc is not None and new_cc is not None:
        return new_cc > old_cc
    return float(cur.get("ctr") or 0) < float(prev.get("ctr") or 0)


def _build_chains(mats: list, by_id: dict) -> list[list[dict]]:
    """Build iteration chains from a list of materials."""
    mat_ids = {str(m["id"]) for m in mats}
    child_map: dict[str, list[dict]] = defaultdict(list)
    roots: list[dict] = []

    for m in mats:
        pid = str(m.get("parent_material_id") or "")
        if pid and pid in mat_ids:
            child_map[pid].append(m)
        else:
            roots.append(m)

    for children in child_map.values():
        children.sort(key=lambda x: (int(x.get("version") or 0), str(x["id"])))

    chains: list[list[dict]] = []
    for root in roots:
        chain = [root]
        queue = [root]
        while queue:
            cur = queue.pop(0)
            kids = child_map.get(str(cur["id"]), [])
            chain.extend(kids)
            queue.extend(kids)
        chains.append(chain)

    return chains


# ── Stage 4: Cross-pack comparison ───────────────────────────────────

def _build_cross_pack_comparison(audiences: list, materials: list) -> str:
    """Find materials with same name across different audience packs and compare."""
    aud_map: dict[str, str] = {str(a["id"]): a["name"] for a in audiences}
    name_groups: dict[str, list[dict]] = defaultdict(list)

    for m in materials:
        name_groups[str(m["name"])].append(m)

    comparisons: list[str] = []
    for name, mats in name_groups.items():
        packs = {str(m["audience_pack_id"]) for m in mats}
        if len(packs) < 2:
            continue

        lines = [f"**素材「{name}」跨包投放对比:**"]
        sorted_mats = sorted(mats, key=lambda m: float(m.get("ctr") or 0), reverse=True)
        for m in sorted_mats:
            aid = str(m["audience_pack_id"])
            aud_name = aud_map.get(aid, aid)
            ctr = float(m.get("ctr") or 0)
            cpm = float(m.get("cpm") or 0)
            cr = float(m.get("completion_rate") or 0)
            cost = float(m.get("cost") or 0)
            lines.append(
                f"- {aud_name}: CTR {ctr:.2%}, CPM ￥{cpm:.2f}, 完播 {cr:.2%}, 消耗 ￥{cost:.0f}"
            )

        ctrs = [float(m.get("ctr") or 0) for m in sorted_mats if m.get("ctr")]
        if len(ctrs) >= 2:
            best = max(ctrs)
            worst = min(ctrs)
            if worst > 0:
                spread = (best - worst) / worst * 100
                lines.append(f"- 人群间 CTR 差异: {spread:.0f}%")

        comparisons.append("\n".join(lines))

    return "\n\n".join(comparisons) if comparisons else "（本批次无同名素材跨人群包投放）"


# ── Stage 5: RAG ─────────────────────────────────────────────────────

async def _rag_search_experience(
    campaign: dict,
    audiences: list,
    materials: list | None = None,
    groups: list | None = None,
    kb_ids: list[str] | None = None,
) -> str:
    materials = materials or []
    groups = groups or []
    product_name = campaign.get("product_name", "")
    audience_tags: list[str] = []
    audience_descs: list[str] = []
    for aud in audiences:
        tags = aud.get("tags")
        if isinstance(tags, list):
            audience_tags.extend(str(t) for t in tags)
        elif isinstance(tags, str):
            audience_tags.append(tags)
        desc = aud.get("description", "")
        if desc:
            audience_descs.append(desc)
        targeting = aud.get("targeting_method_text", "")
        if targeting:
            audience_descs.append(targeting[:100])

    group_map = {str(g["id"]): g for g in groups}
    purposes = set()
    for m in materials:
        gid = str(m.get("group_id") or "")
        grp = group_map.get(gid)
        if grp:
            purposes.add(grp.get("video_purpose", "seeding"))

    avg_ctr = 0.0
    avg_cvr = 0.0
    avg_cpm = 0.0
    n = len(materials) or 1
    for m in materials:
        avg_ctr += float(m.get("ctr") or 0)
        avg_cvr += float(m.get("conversion_rate") or 0)
        avg_cpm += float(m.get("cpm") or 0)
    avg_ctr /= n
    avg_cvr /= n
    avg_cpm /= n

    has_iteration = any(m.get("parent_material_id") for m in materials)
    change_tags_all = set()
    for m in materials:
        ct = m.get("change_tags")
        if isinstance(ct, list):
            change_tags_all.update(ct)
        elif isinstance(ct, str):
            try:
                import json as _json
                parsed = _json.loads(ct)
                if isinstance(parsed, list):
                    change_tags_all.update(parsed)
            except Exception:
                pass

    purpose_label = "/".join(PURPOSE_LABELS.get(p, p) for p in purposes) if purposes else "种草"

    query_parts = [
        f"产品：{product_name}",
        f"投放目的：{purpose_label}",
        f"人群标签：{', '.join(audience_tags)}" if audience_tags else "",
        f"人群描述：{'; '.join(audience_descs[:2])}" if audience_descs else "",
        f"当前数据：平均CTR={avg_ctr:.2%}, 平均转化率={avg_cvr:.2%}, 平均CPM=¥{avg_cpm:.1f}",
        f"素材数量：{len(materials)}条",
    ]
    if has_iteration:
        query_parts.append(f"已有迭代，改动类型：{', '.join(change_tags_all)}" if change_tags_all else "已有迭代")
    if avg_ctr < 0.03:
        query_parts.append("问题：CTR偏低，需要提升点击率的经验")
    if avg_cvr < 0.05:
        query_parts.append("问题：转化率偏低，需要提升转化的经验")
    if avg_cpm > 50:
        query_parts.append("问题：CPM偏高，需要降低流量成本的经验")

    query_parts.append("请提供：有效的钩子策略、素材迭代经验、人群匹配优化方法、历史复盘结论")
    query = "\n".join(p for p in query_parts if p)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if kb_ids:
                results = []
                for kb_id in kb_ids:
                    try:
                        rag_resp = await client.post(
                            f"{KE_BASE}/api/v1/knowledge/rag",
                            json={"kb_id": kb_id, "query": query, "top_k": 8, "stream": False},
                            timeout=60.0,
                        )
                        if rag_resp.status_code == 200:
                            answer = rag_resp.json().get("data", {}).get("answer", "")
                            if answer:
                                results.append(answer)
                    except Exception as e:
                        logger.warning("RAG search kb %s failed: %s", kb_id, e)
                return "\n\n".join(results) if results else "(所选知识库无相关经验)"

            kb_resp = await client.get(f"{KE_BASE}/api/v1/knowledge/bases")
            if kb_resp.status_code != 200:
                return "（投放复盘经验库尚无历史数据）"
            body = kb_resp.json()
            kbs = body.get("data") or []
            review_kb = next((kb for kb in kbs if "复盘" in (kb.get("name") or "")), None)
            if not review_kb:
                return "（投放复盘经验库尚无历史数据）"

            kb_id = review_kb["id"]
            rag_resp = await client.post(
                f"{KE_BASE}/api/v1/knowledge/rag",
                json={
                    "kb_id": kb_id,
                    "query": query,
                    "top_k": 8,
                    "stream": False,
                },
                timeout=60.0,
            )
            if rag_resp.status_code != 200:
                return "（无相关历史经验）"
            rag_body = rag_resp.json()
            data = rag_body.get("data") or {}
            return data.get("answer") or "（无相关历史经验）"
    except Exception as e:
        logger.warning("RAG search failed: %s", e)

    return "（RAG检索失败，跳过历史经验）"


# ── Stage 5.5: Suggestion Comparison ─────────────────────────────────

def _build_suggestion_comparison(prev_suggestions: list, materials: list) -> str:
    """Compare previous review suggestions with actual material changes."""
    if not prev_suggestions:
        return ""

    mat_by_name: dict[str, dict] = {}
    for m in materials:
        mat_by_name[m["name"]] = m

    lines = ["## 上轮建议执行情况"]
    for sug in prev_suggestions:
        name = sug.get("material_name", "")
        suggested = sug.get("suggestions", [])
        if not name or not suggested:
            continue

        mat = mat_by_name.get(name)
        if not mat:
            lines.append(f"- {name}: 建议{suggested}, 本轮未出现该素材")
            continue

        actual_tags = _safe_tags(mat.get("change_tags"))
        executed = [s for s in suggested if s in actual_tags]
        not_executed = [s for s in suggested if s not in actual_tags]

        parts = [f"- {name}: 建议{suggested}"]
        if executed:
            parts.append(f"实际执行{executed}")
        if not_executed:
            parts.append(f"未执行{not_executed}")
        if not executed:
            parts.append("均未执行")
        lines.append(", ".join(parts))

    return "\n".join(lines) if len(lines) > 1 else ""


# ── Stage 6A: Structured JSON Diagnosis Prompt ──────────────────────

EVIDENCE_FIELDS_WHITELIST = frozenset({
    "ctr", "cpm", "conversion_rate", "completion_rate", "play_3s_rate",
    "interaction_rate", "a3_ratio", "new_a3", "cost", "impressions",
    "plays", "video_score_overall",
    "video_score_hook_power", "video_score_content_value",
    "video_score_visual_quality", "video_score_editing_rhythm",
    "video_score_audio_bgm", "video_score_copy_script",
    "video_score_interaction_design", "video_score_algorithm_friendliness",
    "video_score_commercial_potential",
    "conv_cost_calculated",
})


def _build_stage_a_prompt(
    data_summary: str,
    video_insights: str,
    group_analysis: str,
    cross_pack: str,
    rag_context: str,
    audiences: list,
    campaign: dict,
    prev_suggestions_text: str = "",
) -> str:
    audience_profiles_parts = []
    for a in audiences:
        parts = [f"- **{a['name']}**"]
        desc = a.get('description', '')
        if desc:
            parts.append(f"  描述: {desc}")
        targeting = a.get('targeting_method_text') or ''
        if targeting:
            parts.append(f"  圈包手法: {targeting}")
        else:
            tf = a.get('targeting_method_file')
            parts.append(f"  圈包手法: {'（已上传文件但未填写文本摘要）' if tf else '未提供'}")
        profile = a.get('audience_profile_text') or ''
        if profile:
            parts.append(f"  人群画像: {profile}")
        else:
            pf = a.get('audience_profile_file')
            parts.append(f"  人群画像: {'（已上传文件但未填写文本摘要）' if pf else '未提供'}")
        tags = a.get('tags') or []
        if isinstance(tags, list) and tags:
            parts.append(f"  标签: {', '.join(str(t) for t in tags)}")
        audience_profiles_parts.append("\n".join(parts))
    audience_profiles = "\n".join(audience_profiles_parts)

    product_price = float(campaign.get("product_price") or 0)
    margin_rate = float(campaign.get("product_margin_rate") or 0)

    breakeven_section = ""
    if product_price and margin_rate:
        roi_per_unit = product_price * margin_rate
        breakeven_section = (
            f"\n## 保本计算\n"
            f"- 单件毛利 = ￥{product_price:.2f} × {margin_rate:.1%} = ￥{roi_per_unit:.2f}\n"
            f"- 单转化成本 = CPM ÷ (CTR × 1000) ÷ CVR\n"
        )

    prev_section = ""
    if prev_suggestions_text:
        prev_section = f"\n## 上轮建议\n{prev_suggestions_text}\n"

    return f"""你是一位资深的巨量千川投放优化师。

## 数据第一原则（必须遵守）
1. 所有结论必须直接依附于输入中的真实数据或视频分析结果，不得臆测。
2. 禁止编造不存在的指标、行业均值、人群画像、分段留存或成本数据。
3. 如果某项分析所需数据缺失，对应字段输出 null 并在 _reason 字段说明。
4. 每条关键结论都必须包含 evidence_fields（指向输入数据字段名）和 confidence（高/中/低）。
5. evidence_fields 只能从以下白名单选择：ctr, cpm, conversion_rate, completion_rate, play_3s_rate, interaction_rate, a3_ratio, new_a3, cost, impressions, plays, video_score_overall, video_score_hook_power, video_score_content_value, video_score_visual_quality, video_score_editing_rhythm, video_score_audio_bgm, video_score_copy_script, video_score_interaction_design, video_score_algorithm_friendliness, video_score_commercial_potential, conv_cost_calculated

## 归因三步法
1. 对齐：同一变量组内，只改变一个因素比较
2. 定位：数据变化定位到视频秒级变更
3. 判定：有效/无效/不确定 + 信心等级
{breakeven_section}
## 输入数据

### 投放数据总览
{data_summary}

### 视频分析结果
{video_insights}

### 各风格组分析
{group_analysis}

### 跨人群包对比
{cross_pack}

### 人群画像
{audience_profiles}

### 历史经验
{rag_context}
{prev_section}
---

请输出严格的 JSON 对象（不要额外文字、不要 markdown 包裹），结构如下：

{{
  "data_availability": {{
    "available_fields": ["本次可用的指标字段名"],
    "missing_fields": ["缺失的字段名"],
    "missing_impact": "缺失对结论的影响说明"
  }},
  "key_findings": [
    {{
      "conclusion": "一句话结论",
      "evidence": "素材A vs 素材B 的具体数据",
      "evidence_fields": ["ctr", "cpm"],
      "judgment": "有效/无效/不确定",
      "confidence": "高/中/低"
    }}
  ],
  "purpose_diagnosis": {{
    "organic": {{
      "ranking": [{{"material_name": "", "completion_rate": 0, "play_3s_rate": 0, "rank_label": "TOP1/BOTTOM1"}}],
      "hook_issues": ["素材名: 问题描述"],
      "retention_analysis": "数据或数据不足",
      "retention_analysis_reason": "若为数据不足则说明原因"
    }},
    "seeding": {{
      "cpm_ranking": [{{"material_name": "", "audience": "", "cpm": 0, "ctr": 0}}],
      "high_ctr_traits": "高CTR共性",
      "low_ctr_issues": "低CTR问题",
      "a3_efficiency": "A3效率分析"
    }},
    "conversion": {{
      "breakeven_matrix": [
        {{"material_name": "", "cpm": 0, "ctr": 0, "cvr": 0, "conv_cost": 0, "margin": 0, "profitable": true}}
      ],
      "loss_attribution": [{{"material_name": "", "bottleneck": "cpm/ctr/cvr", "detail": ""}}]
    }}
  }},
  "iteration_attribution": [
    {{
      "chain": "根素材名",
      "versions": ["v1→v2"],
      "change_tags": ["改钩子"],
      "kpi_delta": "CTR 2.1%→3.5%",
      "evidence_fields": ["ctr"],
      "judgment": "有效/无效/不确定",
      "confidence": "高/中/低",
      "repeated_validation": false
    }}
  ],
  "audience_content_matrix": [
    {{
      "material_name": "",
      "cross_pack_results": [{{"audience": "", "ctr": 0, "cpm": 0}}],
      "best_audience": "",
      "conclusion": ""
    }}
  ],
  "action_plan": {{
    "stop_immediately": [{{"material_name": "", "reason": "", "evidence_fields": ["ctr"]}}],
    "scale_up": [{{"material_name": "", "reason": "", "evidence_fields": ["ctr"]}}],
    "iteration_directions": [{{"group": "", "changes": "", "target_seconds": ""}}],
    "new_material_suggestions": [""],
    "audience_adjustments": [""],
    "budget_allocation": [""]
  }},
  "experience_tags": ["#标签1", "#标签2"],
  "next_suggestions": [
    {{
      "material_name": "",
      "suggestions": ["改钩子"],
      "evidence_fields": ["ctr", "play_3s_rate"],
      "detail": ""
    }}
  ]
}}

如果某个分类（organic/seeding/conversion）在本次投放中无对应素材，该分类输出空对象 {{}}。
所有数值必须来自输入数据，禁止编造。
"""


async def _call_llm_json(prompt: str, n_materials: int = 0) -> dict | None:
    """Non-streaming LLM call for structured JSON output with adaptive token budget."""
    url = f"{AI_HUB_BASE}/v1/chat/completions"
    timeout = httpx.Timeout(120.0, connect=10.0)
    max_tokens = 8192 + max(0, n_materials - 10) * 256

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            try:
                request_body: dict[str, Any] = {
                    "model": settings.review_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                }
                resp = await client.post(url, json=request_body)
                if resp.status_code >= 400:
                    logger.error("Stage A LLM error %s: %s", resp.status_code, resp.text[:500])
                    return None
                body = resp.json()
                choice = body["choices"][0]
                finish_reason = choice.get("finish_reason", "")
                if finish_reason == "length" and attempt == 0:
                    logger.warning("Stage A truncated (max_tokens=%d), retrying with +4096", max_tokens)
                    max_tokens += 4096
                    continue
                text = choice["message"]["content"]
                text = text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()
                return json.loads(text)
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.warning("Stage A JSON parse failed (attempt %d): %s", attempt, e)
                if attempt == 0:
                    continue
                return None
            except Exception as e:
                logger.warning("Stage A LLM call failed: %s", e)
                return None
    return None


def _validate_evidence_fields(diagnosis: dict) -> dict:
    """Strip invalid evidence_fields from the diagnosis JSON."""
    def _clean_list(items: list) -> list:
        for item in items:
            if isinstance(item, dict) and "evidence_fields" in item:
                item["evidence_fields"] = [
                    f for f in item["evidence_fields"] if f in EVIDENCE_FIELDS_WHITELIST
                ]
        return items

    for key in ("key_findings", "iteration_attribution", "next_suggestions"):
        if isinstance(diagnosis.get(key), list):
            _clean_list(diagnosis[key])

    ap = diagnosis.get("action_plan")
    if isinstance(ap, dict):
        for sub_key in ("stop_immediately", "scale_up"):
            if isinstance(ap.get(sub_key), list):
                _clean_list(ap[sub_key])

    return diagnosis


# ── Stage 6B: Render Markdown from Diagnosis ─────────────────────────

def _truncate_preserving_names(text: str, max_chars: int = 4000) -> str:
    """Truncate data_summary while preserving all material name lines."""
    if len(text) <= max_chars:
        return text
    lines = text.split("\n")
    kept: list[str] = []
    budget = max_chars
    for line in lines:
        is_important = line.startswith("- [") or line.startswith("- ") or line.startswith("## ")
        if is_important or budget > len(line) + 1:
            kept.append(line)
            budget -= len(line) + 1
        if budget <= 0 and not is_important:
            kept.append("...（数据摘要已截断，完整数据见诊断 JSON）")
            break
    return "\n".join(kept)


def _build_stage_b_prompt(diagnosis: dict, data_summary: str) -> str:
    diagnosis = _validate_evidence_fields(diagnosis)
    diagnosis_text = json.dumps(diagnosis, ensure_ascii=False, indent=2)
    summary_text = _truncate_preserving_names(data_summary, max_chars=4000)

    return f"""你是一位投放复盘报告的渲染专家。

下面是已经完成的结构化诊断 JSON（所有数据和结论已经过数据验证）。
你的任务是将其渲染为可读性强的 Markdown 复盘报告。

## 渲染规则
1. 严格按照诊断 JSON 中的内容输出，不得添加 JSON 中不存在的结论或数据。
2. 不要编造任何额外的数字、百分比、或分析。
3. 如果 JSON 中某字段为 null 并有 _reason 说明，在报告中明确写出"数据不足"及原因。
4. 每条关键发现必须标注【置信度】。
5. 对于 evidence_fields，在结论旁用括号标注依据字段。
6. 最后的"下一版素材改动建议"段落必须输出原始 JSON 代码块（```json ... ```），不要改动内容。

## 原始数据摘要（供引用素材名）
{summary_text}

## 诊断 JSON
{diagnosis_text}

---

请按以下结构输出 Markdown 报告：

### 一、数据可用性声明
（基于 data_availability）

### 二、关键发现
（基于 key_findings，每条标注置信度和证据字段）

### 三、按视频目的分类诊断
（基于 purpose_diagnosis，分 organic/seeding/conversion 三段）

### 四、迭代归因分析
（基于 iteration_attribution）

### 五、人群×内容匹配矩阵
（基于 audience_content_matrix）

### 六、下一轮行动清单
（基于 action_plan）

### 七、经验沉淀
（基于 experience_tags）

### 八、下一版素材改动建议（JSON）
（直接输出 next_suggestions 的 JSON 代码块）
"""


# ── Stage 6 (Legacy Fallback): Build Prompt ──────────────────────────

def _build_review_prompt(
    data_summary: str,
    video_insights: str,
    group_analysis: str,
    cross_pack: str,
    rag_context: str,
    audiences: list,
    campaign: dict,
    prev_suggestions_text: str = "",
) -> str:
    audience_profiles_parts = []
    for a in audiences:
        parts = [f"- **{a['name']}**"]
        desc = a.get('description', '')
        if desc:
            parts.append(f"  描述: {desc}")
        targeting = a.get('targeting_method_text') or ''
        if targeting:
            parts.append(f"  圈包手法: {targeting}")
        else:
            tf = a.get('targeting_method_file')
            parts.append(f"  圈包手法: {'（已上传文件但未填写文本摘要，请补充）' if tf else '未提供'}")
        profile = a.get('audience_profile_text') or ''
        if profile:
            parts.append(f"  人群画像: {profile}")
        else:
            pf = a.get('audience_profile_file')
            parts.append(f"  人群画像: {'（已上传文件但未填写文本摘要，请补充）' if pf else '未提供'}")
        tags = a.get('tags') or []
        if isinstance(tags, list) and tags:
            parts.append(f"  标签: {', '.join(str(t) for t in tags)}")
        audience_profiles_parts.append("\n".join(parts))
    audience_profiles = "\n".join(audience_profiles_parts)

    product_price = float(campaign.get("product_price") or 0)
    margin_rate = float(campaign.get("product_margin_rate") or 0)
    prev_section = ""
    if prev_suggestions_text:
        prev_section = (
            "\n## 七、上轮复盘改动建议（供参考）\n"
            + prev_suggestions_text
            + "\n"
        )

    breakeven_section = ""
    if product_price and margin_rate:
        roi_per_unit = product_price * margin_rate
        breakeven_section = f"""
## 保本计算公式（转化类素材适用）
- 单件毛利 = 产品单价(￥{product_price:.2f}) × 毛利率({margin_rate:.1%}) = ￥{roi_per_unit:.2f}
- 单次转化成本 = CPM ÷ (CTR × 1000) ÷ CVR
- 判定: 单转化成本 ≤ 单件毛利 → 可投放; 单转化成本 > 单件毛利 → 亏损
- 对于每条转化类素材，必须明确标注是否保本，亏多少或赚多少
"""

    return f"""你是一位资深的巨量千川投放优化师，同时精通短视频内容分析。
你需要按照不同视频目的（自然流量/种草/转化）使用不同的分析框架。

## 数据第一原则（必须遵守）
1. 所有结论必须直接依附于输入中的真实数据或视频分析结果，不得臆测。
2. 禁止编造不存在的指标、行业均值、人群画像、分段留存或成本数据。
3. 如果某项分析所需数据缺失，明确写“数据不足，无法判断”，并列出缺失字段。
4. 每条关键结论都必须包含：结论 + 证据数据 + 归因判定 + 置信度（高/中/低）。
5. 不允许使用“通常/一般/大概率”替代证据推理。

## 核心分析方法论：归因三步法
1. **对齐**：同一变量组内，只改变一个因素进行比较（如同一风格组内，改钩子的那组 vs 不改的那组）
2. **定位**：数据变化的原因定位到具体的视频秒级变更（如"第2秒换了产品特写→3秒率提升"）
3. **判定**：明确标注每个改动的效果——有效/无效/不确定，给出信心等级

## 不同视频目的的关键指标
- **自然流量**: 核心看完播率、3秒完播率、互动率、播放量。
- **种草**: 核心看CPM、点击率、A3转化率（即千川导出的"转化率"）、A3转化成本（即千川导出的"转化成本"）。注意：种草计划的转化率=A3转化率，转化成本=A3成本，可能>100%是正常的（归因窗口导致）。
- **转化**: 核心看CPM×CTR×CVR三者综合。必须计算单次转化成本并与保本线对比。
{breakeven_section}
## 一、投放数据总览
{data_summary}

## 二、视频分析结果
{video_insights}

## 三、各风格组按目的分类分析
{group_analysis}

## 四、同内容跨人群包对比
{cross_pack}

## 五、人群画像与圈包手法
{audience_profiles}

## 六、历史投放经验（来自知识库）
{rag_context}
{prev_section}
---

**重要输出要求：**
1. 不限字数，必须详细充分，把每个分析点讲透
2. 每个结论必须有具体数据支撑，引用素材名+数据
3. 改进建议必须具体到秒级、画面级、文案级，不要泛泛而谈
4. 对比分析必须列出前后版本的具体差异

请按照以下结构输出复盘日志（Markdown格式）：

### 一、数据可用性声明（先输出）
- 列出本次可用核心字段（如CTR/CPM/CVR/完播率/3秒率/A3等）
- 列出缺失字段（若缺失）
- 缺失字段对结论范围的影响

### 二、关键发现（3-5条，每条都要“结论+证据+判定+置信度”）
格式: "【结论】……｜【证据】素材A vs 素材B 的具体数据｜【判定】有效/无效/不确定｜【置信度】高/中/低"

### 三、按视频目的分类诊断（仅使用已提供数据）

#### 自然流量类素材
- 核心指标排名（按完播率排序），标注TOP3和BOTTOM3
- 3秒流失分析：哪些素材3秒率低？结合视频分析判断钩子问题
- 若存在分段留存数据，再输出25%/50%/75%节点衰减；否则明确“数据不足”

#### 种草类素材
- CPM效率排名（按CPM从低到高），找出最划算的人群包×素材组合
- 点击率分析：高CTR素材的共性特征，低CTR素材的问题
- A3转化率分析（种草的"转化率"就是A3转化率）：转化率高低的原因，结合视频内容分析
- A3转化成本分析（种草的"转化成本"就是A3成本）：每条素材的A3成本对比，哪条最划算
- 综合效率：CPM × CTR × A3转化率，找出综合ROI最高的素材

#### 转化类素材
- **保本矩阵**：每条素材的 CPM、CTR、CVR、单转化成本、vs保本线差距
- 哪些素材盈利？哪些亏损？差距多大？
- 拆解亏损原因：是CPM太高（流量贵）？CTR太低（不吸引人）？CVR太低（不转化）？

### 四、迭代归因分析（核心：结合视频内容差异解释数据变化）
- 对每个有迭代链的变种，逐版本对比：
  1. **数据变化**: 列出 CTR、转化率、完播率、CPM 等关键指标的前后变化
  2. **视频内容差异**: 对比前后版本的以下维度（从上方视频分析中提取）：
     - 钩子差异（前3秒用了什么钩子？类型变了吗？效果描述有何不同？）
     - 画面/场景差异（场景切换了吗？画面元素变了哪些？）
     - 表演差异（演员、肢体语言、表情有变化吗？）
     - 脚本结构差异（叙事顺序变了吗？新增/删除了哪些段落？）
     - BGM/音频差异（换BGM了吗？节奏变了吗？）
     - 文案差异（口播文案改了哪些？）
  3. **归因判定**: 基于以上对比，判断数据变化的原因：
     - 是因为钩子更吸引人→CTR提升？
     - 是因为节奏更紧凑→完播率提升？
     - 是因为卖点更清晰→转化率提升？
     - 还是因为画面质量下降→CPM变贵？
  4. **信心等级**: 给出归因的信心等级（高/中/低）
- 如果有上轮改动建议，评估哪些建议被执行了、效果如何、哪些没执行是否应该继续

### 五、人群×内容×圈包手法匹配分析
- 结合每个人群包的**圈包手法**和**人群画像**数据，分析：
  - 当前定向策略是否精准？人群和素材内容是否匹配？
  - 哪些人群包的CPM偏高？是定向太宽还是内容不匹配？
  - 哪些人群包转化率好？好在哪里？（人群精准 or 内容匹配 or 两者兼有）
- 如果有跨包素材，制作对比表
- 给出每个人群包最适合的素材类型/风格结论
- 圈包手法的具体调整建议（加什么兴趣标签、排除什么人群、怎么缩窄/扩大定向）

### 六、下一轮行动清单（必须详细具体，不限字数）

**不要给模糊建议。每条建议必须说清楚：改什么、怎么改、为什么改、预期效果。**

1. **立即停投**:
   - 哪些素材应该暂停？列出素材名
   - 暂停原因（具体数据支撑）
   - 暂停后预算如何重新分配

2. **加大投入**:
   - 哪些素材值得追加预算？追加多少？
   - 为什么这条素材值得追加（数据证据）

3. **素材迭代方向（逐条素材出详细改进方案，这是最重要的部分）**:
   对每条需要迭代的素材，必须输出完整的改进方案（不少于200字/条）：
   
   **a) 钩子改进（前3秒）：**
   - 当前钩子是什么？效果如何？（引用视频分析数据）
   - 建议改成什么类型的钩子？（反问式/痛点式/悬念式/利益式等）
   - 具体的开场文案建议（写出完整的口播词）
   - 画面怎么配合？（产品特写/场景/人物表情等）
   
   **b) 内容结构改进：**
   - 当前脚本结构的问题在哪？（哪里流失严重？）
   - 建议的新脚本结构（按秒级拆解：0-3秒做什么、3-8秒做什么、8-15秒做什么、15秒-结尾做什么）
   - 每段的画面建议和口播文案建议
   
   **c) 转化路径改进：**
   - 当前转化率的瓶颈在哪？是不够吸引人还是信任度不够？
   - CTA（行动号召）怎么改？放在第几秒？用什么话术？
   - 价格锚点、促销信息怎么植入？
   
   **d) 画面和制作改进：**
   - 画面质量哪里需要提升？
   - BGM是否合适？建议换什么风格？
   - 字幕、特效、贴纸等辅助元素建议

4. **新素材建议**:
   - 基于数据和视频分析，应该新拍什么类型的素材
   - 给出完整的脚本大纲（不少于100字）
   - 参考的成功案例特征

5. **人群调整**:
   - 哪些人群包要调整定向？怎么调？
   - 结合圈包手法和画像数据给出具体的定向修改建议
   - 建议新增哪些兴趣标签、排除哪些人群

6. **预算分配建议**:
   - 下一轮各风格组的预算占比建议及理由

### 七、经验沉淀
以 #标签 格式输出本次复盘的关键经验标签。
包含：产品类型、人群特征、有效策略、无效策略、风格组类型、视频目的等维度。

### 八、下一版素材改动建议（JSON，严格数据驱动）
针对每条需要继续迭代的素材，从以下标签中选择改动方向并输出严格JSON。
可选标签：改钩子、改BGM、改文案、改画面、缩短时长、换演员、换场景、改字幕
约束：只允许基于本次数据证据给建议；如证据不足，detail 必须写“数据不足，需补充X字段”。
每条建议必须包含 evidence_fields（数组），仅可从以下字段中选择并按证据强弱排序：
- ctr
- cpm
- conversion_rate
- completion_rate
- play_3s_rate
- interaction_rate
- a3_ratio
- new_a3
- cost
- impressions
- plays
- video_score_overall

请输出如下格式的JSON代码块（注意必须是合法JSON数组）：
```json
[{{"material_name":"素材名","suggestions":["改钩子","改画面"],"evidence_fields":["ctr","play_3s_rate","completion_rate"],"detail":"具体怎么改的一句话说明"}}]
```
"""


# ── Stage 7: LLM Streaming ───────────────────────────────────────────

async def _stream_llm(prompt: str, temperature: float = 0.2, max_tokens: int = 16384) -> AsyncIterator[str]:
    url = f"{AI_HUB_BASE}/v1/chat/completions"
    timeout = httpx.Timeout(300.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST",
                url,
                json={
                    "model": settings.review_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            ) as resp:
                if resp.status_code >= 400:
                    err = await resp.aread()
                    logger.error("LLM error %s: %s", resp.status_code, err[:500])
                    if resp.status_code in (401, 403):
                        yield "\n\n[错误：请先配置 AI 模型（在 AI Provider Hub 中填写有效的 API Key）。]\n"
                    else:
                        yield "\n\n[错误：AI 网关返回异常，请检查 API Key 与模型配置。]\n"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except (httpx.TimeoutException, httpx.ReadTimeout) as e:
            logger.warning("LLM stream timeout: %s", e)
            yield "\n\n[提示：生成超时（120s），上文已保留。可稍后重试或缩短数据量。]\n"
        except Exception as e:
            logger.exception("LLM stream failed: %s", e)
            yield f"\n\n[错误：{e!s}]\n"
