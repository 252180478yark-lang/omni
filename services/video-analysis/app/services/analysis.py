from __future__ import annotations

import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .emotion_curve import build_curve

DEFAULT_REPORT_OUTPUT_DIR = Path(os.getenv("VIDEO_ANALYSIS_PACK_DIR") or os.getenv("VIDEO_ANALYSIS_DATA_DIR") or "/app/data/video-analysis") / "reports"


def _build_placeholder_report(
    video_id: str, original_name: str, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    no_llm = "未启用多模态 LLM"
    summary = "未启用多模态 LLM，无法生成完整分析报告。"
    persona_detail = (context or {}).get("persona_detail") or {
        "appearance": no_llm,
        "outfit": no_llm,
        "micro_expression": no_llm,
        "body_language": no_llm,
    }
    return {
        "meta": {
            "video_id": video_id,
            "original_name": original_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "summary": summary,
        "visual": {
            "composition": no_llm,
            "shot_type": no_llm,
            "lighting_tone": no_llm,
            "persona": no_llm,
            "persona_detail": persona_detail,
            "scene_semantics": no_llm,
            "visual_elements": [],
        },
        "bgm_audio": {
            "beat_sync": no_llm,
            "emotion_fit": no_llm,
            "hotness_estimate": no_llm,
        },
        "editing_rhythm": {"first_3s_hook": no_llm, "cut_frequency": no_llm},
        "copy_logic": {
            "title_hook_type": no_llm,
            "seo_keywords": [],
            "golden_3s": no_llm,
            "narrative_model": no_llm,
            "info_density": no_llm,
            "catchphrase_frequency": no_llm,
            "on_screen_text": no_llm,
        },
        "interaction_algo": {
            "bait_points": no_llm,
            "controversy": no_llm,
            "cta": no_llm,
            "completion_rate_logic": no_llm,
            "follow_like_ratio": no_llm,
        },
        "business_strategy": {
            "monetization_path": no_llm,
            "trend_stage": no_llm,
            "cognitive_load": no_llm,
            "audience_persona": no_llm,
        },
        "douyin_specific": {
            "content_type": no_llm,
            "video_format": no_llm,
            "duration_strategy": {"actual_duration_assessment": no_llm, "optimal_duration_suggestion": no_llm},
            "hashtag_strategy": {"detected_topics": [], "recommended_topics": [], "topic_heat_assessment": no_llm},
            "douyin_native_elements": {
                "sticker_effects": no_llm, "duet_potential": no_llm,
                "challenge_relevance": no_llm, "poi_usage": no_llm, "shopping_cart": no_llm,
            },
            "traffic_pool_prediction": {"estimated_level": no_llm, "breakthrough_factors": [], "risk_factors": []},
        },
        "scores": {
            "overall": 0.0,
            "dimensions": {
                "hook_power": {"score": 0.0, "weight": 0.20, "brief": no_llm},
                "content_value": {"score": 0.0, "weight": 0.15, "brief": no_llm},
                "visual_quality": {"score": 0.0, "weight": 0.10, "brief": no_llm},
                "editing_rhythm": {"score": 0.0, "weight": 0.10, "brief": no_llm},
                "audio_bgm": {"score": 0.0, "weight": 0.10, "brief": no_llm},
                "copy_script": {"score": 0.0, "weight": 0.10, "brief": no_llm},
                "interaction_design": {"score": 0.0, "weight": 0.10, "brief": no_llm},
                "algorithm_friendliness": {"score": 0.0, "weight": 0.10, "brief": no_llm},
                "commercial_potential": {"score": 0.0, "weight": 0.05, "brief": no_llm},
            },
            "replicability": {"score": 0.0, "difficulty": no_llm, "key_barriers": []},
        },
        "improvement_suggestions": {
            "priority_actions": [],
            "copy_rewrite": {"original_title": "", "suggested_titles": [], "title_optimization_notes": ""},
            "editing_suggestions": [],
            "algorithm_optimization": [],
            "a_b_test_suggestions": [],
        },
        "ai_insights": {
            "semantic_tags": [],
            "replicability_score": 0.0,
            "emotion_curve": build_curve(video_id),
        },
    }


def build_placeholder_report(
    video_id: str, original_name: str, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    return _build_placeholder_report(video_id, original_name, context)


def _set_llm_notice(
    report: dict[str, Any], reason: str, summary: str, detail: str | None = None
) -> dict[str, Any]:
    report.setdefault("meta", {})
    report["meta"]["llm_disabled_reason"] = reason
    if detail:
        report["meta"]["llm_disabled_detail"] = detail
    report["summary"] = summary
    return report


def _build_prompt(context: dict[str, Any] | None = None, metrics: dict[str, Any] | None = None) -> str:
    prompt = (
        "你是专业的抖音短视频分析师，精通抖音推荐算法和内容生态。\n"
        "分析时请基于以下抖音算法核心逻辑：\n"
        "1. 流量池机制：200→3000→1万→10万→100万，逐级突破\n"
        "2. 核心指标权重：完播率 > 互动率 > 关注率 > 分享率\n"
        "3. 前3秒决定70%的完播率\n"
        "4. 评论区活跃度对流量池升级影响最大\n"
        "5. 内容与账号标签的一致性影响推荐精准度\n"
        "\n"
        "请根据给定视频内容输出严格 JSON，不要额外文字。\n"
        "字段结构如下（所有字段必填，字符串请用中文）：\n"
        "\n"
        "## 情绪曲线 emotion_curve 生成规则\n"
        "- 必须输出至少 30 个点（短视频）或 60 个点（长视频），t 为秒序号，v 为 0-1 之间的小数。\n"
        "- v 的判断维度：综合画面冲击力、BGM 节奏强度、文案情感张力、剪辑转场密度。\n"
        "- 开头 3 秒内应反映钩子强度（强钩子 v≥0.6，弱钩子 v≤0.3）。\n"
        "- 高潮/反转/金句时刻 v 应升至 0.7-1.0。\n"
        "- 过渡/铺垫段落 v 在 0.2-0.5 之间。\n"
        "- 结尾 CTA 段 v 略回升（0.4-0.6）。\n"
        "- 整体曲线应有波动，不要平坦，不要全部相同值。\n"
        "\n"
        "## 画面元素 visual_elements 生成规则\n"
        "- 列出视频画面中出现的所有主要视觉元素。\n"
        "- 包括但不限于：人物（数量/角色）、物体、场景背景、文字/花字、品牌/Logo、特效/滤镜、字幕。\n"
        "- 每个元素用简短中文描述，输出为字符串数组。\n"
        "\n"
        "## 多维评分 scores 生成规则\n"
        "- 9 个维度各独立给分（1-10），附带一句话说明 brief。\n"
        "- overall = 各维度 score × weight 求和（保留 1 位小数）。\n"
        "- 权重已在 schema 中给出默认值，请直接使用。\n"
        "- replicability 保留 0-1 分值，附带难度等级和关键壁垒。\n"
        "\n"
        "## 改进建议 improvement_suggestions 生成规则\n"
        "- priority_actions: 列出 3-5 个按紧急度排序的改进项。\n"
        "- 每个建议必须包含：当前问题 current_issue、具体改法 suggestion、预期效果 expected_impact。\n"
        "- copy_rewrite: 必须给出 3 个优化版标题 suggested_titles。\n"
        "- editing_suggestions: 按时间轴标注需要改进的具体秒数。\n"
        "- algorithm_optimization: 针对抖音算法给出 3-5 条具体操作建议。\n"
        "- a_b_test_suggestions: 给出 1-2 个 A/B 测试方案。\n"
        "\n"
        "{\n"
        '  "summary": "简要结论（2-3句话概括视频特征与传播潜力）",\n'
        '  "visual": {\n'
        '    "composition": "", "shot_type": "", "lighting_tone": "",\n'
        '    "persona": "",\n'
        '    "persona_detail": {\n'
        '      "appearance": "", "outfit": "", "micro_expression": "", "body_language": ""\n'
        "    },\n"
        '    "scene_semantics": "",\n'
        '    "visual_elements": ["元素1", "元素2", "..."]\n'
        "  },\n"
        '  "bgm_audio": {\n'
        '    "beat_sync": "", "emotion_fit": "",\n'
        '    "hotness_estimate": "疑似爆款/非爆款/无法判断（无热度数据）"\n'
        "  },\n"
        '  "editing_rhythm": { "first_3s_hook": "", "cut_frequency": "" },\n'
        '  "copy_logic": {\n'
        '    "title_hook_type": "", "seo_keywords": [],\n'
        '    "golden_3s": "", "info_density": "", "catchphrase_frequency": "",\n'
        '    "narrative_model": "", "on_screen_text": ""\n'
        "  },\n"
        '  "interaction_algo": {\n'
        '    "bait_points": "", "controversy": "", "cta": "",\n'
        '    "completion_rate_logic": "", "follow_like_ratio": "",\n'
        '    "completion_rate_design": {\n'
        '      "hook_strength": "前3秒拦截强度评分(1-10)",\n'
        '      "loop_design": "是否有循环播放设计（首尾衔接）",\n'
        '      "progress_bar_suspense": "是否利用进度条制造悬念",\n'
        '      "duration_content_match": "时长与信息密度匹配度"\n'
        "    },\n"
        '    "comment_inducement": {\n'
        '      "question_type": "提问型/纠错型/投票型/共鸣型/无",\n'
        '      "controversy_level": "争议度(0-10)",\n'
        '      "comment_template_prediction": "预测高频评论内容"\n'
        "    },\n"
        '    "share_motivation": {\n'
        '      "utility_value": "实用收藏价值(1-10)",\n'
        '      "social_currency": "社交货币价值(1-10)",\n'
        '      "emotional_contagion": "情绪感染力(1-10)"\n'
        "    },\n"
        '    "negative_signal_risk": {\n'
        '      "skip_risk_points": ["可能引发滑走的时间点(秒)"],\n'
        '      "dislike_risk": "不感兴趣风险因素",\n'
        '      "report_risk": "举报风险因素（低质/搬运/违规）"\n'
        "    }\n"
        "  },\n"
        '  "business_strategy": {\n'
        '    "monetization_path": "", "trend_stage": "",\n'
        '    "cognitive_load": "", "audience_persona": "",\n'
        '    "dou_plus_assessment": {\n'
        '      "worth_investing": true,\n'
        '      "recommended_budget_tier": "低(100-300)/中(500-1000)/高(2000+)",\n'
        '      "target_audience_suggestion": "投放人群建议",\n'
        '      "expected_roi_range": "预期 ROI 范围"\n'
        "    },\n"
        '    "content_lifecycle_prediction": "内容衰减预期（3天热度/7天长尾/持续常青）",\n'
        '    "audience_detail": {\n'
        '      "age_range": "18-24/25-30/31-40/40+",\n'
        '      "gender_skew": "偏女性/偏男性/均衡",\n'
        '      "city_tier": "一线/新一线/二三线/下沉市场",\n'
        '      "interest_tags": ["兴趣标签"],\n'
        '      "consumption_power": "高/中/低"\n'
        "    }\n"
        "  },\n"
        '  "douyin_specific": {\n'
        '    "content_type": "知识口播/剧情演绎/好物种草/颜值展示/搞笑段子/技术流/vlog/直播切片/图文轮播",\n'
        '    "video_format": "竖屏原生/横屏裁切/绿幕合成/分屏对比/图文滑动",\n'
        '    "duration_strategy": {\n'
        '      "actual_duration_assessment": "时长与内容量是否匹配",\n'
        '      "optimal_duration_suggestion": "建议最佳时长"\n'
        "    },\n"
        '    "hashtag_strategy": {\n'
        '      "detected_topics": ["#话题1"],\n'
        '      "recommended_topics": ["建议增加的话题"],\n'
        '      "topic_heat_assessment": "话题热度评估"\n'
        "    },\n"
        '    "douyin_native_elements": {\n'
        '      "sticker_effects": "是否使用抖音原生贴纸/特效",\n'
        '      "duet_potential": "合拍/二创潜力",\n'
        '      "challenge_relevance": "与热门挑战赛的相关性",\n'
        '      "poi_usage": "是否使用定位（本地生活相关）",\n'
        '      "shopping_cart": "是否挂小黄车/商品链接"\n'
        "    },\n"
        '    "traffic_pool_prediction": {\n'
        '      "estimated_level": "初级(200-500)/中级(3k-5k)/高级(1w-10w)/爆款(10w+)",\n'
        '      "breakthrough_factors": ["有利因素"],\n'
        '      "risk_factors": ["不利因素"]\n'
        "    }\n"
        "  },\n"
        '  "scores": {\n'
        '    "overall": 7.0,\n'
        '    "dimensions": {\n'
        '      "hook_power":            {"score": 7.0, "weight": 0.20, "brief": ""},\n'
        '      "content_value":         {"score": 7.0, "weight": 0.15, "brief": ""},\n'
        '      "visual_quality":        {"score": 7.0, "weight": 0.10, "brief": ""},\n'
        '      "editing_rhythm":        {"score": 7.0, "weight": 0.10, "brief": ""},\n'
        '      "audio_bgm":             {"score": 7.0, "weight": 0.10, "brief": ""},\n'
        '      "copy_script":           {"score": 7.0, "weight": 0.10, "brief": ""},\n'
        '      "interaction_design":    {"score": 7.0, "weight": 0.10, "brief": ""},\n'
        '      "algorithm_friendliness":{"score": 7.0, "weight": 0.10, "brief": ""},\n'
        '      "commercial_potential":  {"score": 7.0, "weight": 0.05, "brief": ""}\n'
        "    },\n"
        '    "replicability": {\n'
        '      "score": 0.5,\n'
        '      "difficulty": "中等",\n'
        '      "key_barriers": ["壁垒1"]\n'
        "    }\n"
        "  },\n"
        '  "improvement_suggestions": {\n'
        '    "priority_actions": [\n'
        "      {\n"
        '        "category": "hook_optimization/interaction_boost/bgm_upgrade/copy_improvement/editing_fix/other",\n'
        '        "urgency": "high/medium/low",\n'
        '        "current_issue": "当前问题描述",\n'
        '        "suggestion": "具体改进方法",\n'
        '        "expected_impact": "预期效果"\n'
        "      }\n"
        "    ],\n"
        '    "copy_rewrite": {\n'
        '      "original_title": "原标题或推测标题",\n'
        '      "suggested_titles": ["优化标题1", "优化标题2", "优化标题3"],\n'
        '      "title_optimization_notes": "标题优化思路"\n'
        "    },\n"
        '    "editing_suggestions": [\n'
        '      {"timestamp_sec": 0, "suggestion": "具体秒数的剪辑改进建议"}\n'
        "    ],\n"
        '    "algorithm_optimization": ["针对抖音算法的具体操作建议"],\n'
        '    "a_b_test_suggestions": [\n'
        '      {"variable": "测试变量", "version_a": "当前方案", "version_b": "建议测试方案"}\n'
        "    ]\n"
        "  },\n"
        '  "ai_insights": {\n'
        '    "semantic_tags": [], "replicability_score": 0.0,\n'
        '    "emotion_curve": [{"t": 0, "v": 0.3}, {"t": 1, "v": 0.5}, "..."]\n'
        "  }\n"
        "}\n"
    )
    if context:
        prompt += "\n以下是从视频中提取的辅助信息（可作为参考）：\n"
        prompt += json.dumps(context, ensure_ascii=False, indent=2)
    if metrics:
        prompt += (
            "\n\n以下是该视频在抖音的实际表现数据：\n"
            + json.dumps(metrics, ensure_ascii=False, indent=2)
            + "\n\n请基于内容分析结果和实际数据进行归因分析：\n"
            "1. 数据表现与内容质量是否匹配？\n"
            "2. 如果数据好，归因到具体哪些内容因素\n"
            "3. 如果数据差，找出内容层面的具体瓶颈\n"
            "4. 对比同类型视频的典型数据，给出相对评价\n"
            "\n请将归因分析结果放入 performance_attribution 字段：\n"
            '{\n'
            '  "performance_attribution": {\n'
            '    "data_vs_content_alignment": "高度匹配/内容优于数据/数据优于内容",\n'
            '    "positive_factors": [{"factor": "", "estimated_contribution": ""}],\n'
            '    "negative_factors": [{"factor": "", "estimated_contribution": ""}],\n'
            '    "benchmark": {"category_avg_completion_rate": 0.35, "actual_vs_benchmark": ""}\n'
            "  }\n"
            "}\n"
        )
    return prompt


def _extract_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def _merge_missing(target: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    for key, value in fallback.items():
        if key not in target or target[key] is None:
            target[key] = value
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_missing(target[key], value)
    return target


def _ensure_dict(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    return value if isinstance(value, dict) else dict(fallback)


def _ensure_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[,\s、]+", value) if p.strip()]
        return parts or list(fallback)
    return list(fallback)


def _ensure_str(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    return str(value)


def _ensure_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


def _normalize_curve(value: Any, fallback_curve: list[dict[str, float]] | None = None) -> list[dict[str, float]]:
    if not isinstance(value, list):
        return fallback_curve or []
    points: list[dict[str, float]] = []
    for idx, item in enumerate(value):
        if isinstance(item, dict):
            t = item.get("t", idx)
            v = item.get("v", 0.0)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            t, v = item[0], item[1]
        elif isinstance(item, (int, float)):
            t, v = idx, item
        else:
            continue
        t_val = _ensure_float(t, float(idx))
        v_val = max(0.0, min(1.0, _ensure_float(v, 0.0)))
        points.append({"t": t_val, "v": v_val})
    return points or (fallback_curve or [])


def _coerce_report(report: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    report = _merge_missing(report, fallback)

    report["summary"] = _ensure_str(report.get("summary"), fallback.get("summary", ""))

    report["visual"] = _ensure_dict(report.get("visual"), fallback["visual"])
    visual = report["visual"]
    visual["composition"] = _ensure_str(visual.get("composition"), fallback["visual"]["composition"])
    visual["shot_type"] = _ensure_str(visual.get("shot_type"), fallback["visual"]["shot_type"])
    visual["lighting_tone"] = _ensure_str(visual.get("lighting_tone"), fallback["visual"]["lighting_tone"])
    visual["persona"] = _ensure_str(visual.get("persona"), fallback["visual"]["persona"])
    visual["scene_semantics"] = _ensure_str(visual.get("scene_semantics"), fallback["visual"]["scene_semantics"])
    visual["visual_elements"] = _ensure_list(visual.get("visual_elements"), fallback["visual"].get("visual_elements", []))
    visual["persona_detail"] = _ensure_dict(visual.get("persona_detail"), fallback["visual"]["persona_detail"])
    pd = visual["persona_detail"]
    pd["appearance"] = _ensure_str(pd.get("appearance"), fallback["visual"]["persona_detail"]["appearance"])
    pd["outfit"] = _ensure_str(pd.get("outfit"), fallback["visual"]["persona_detail"]["outfit"])
    pd["micro_expression"] = _ensure_str(pd.get("micro_expression"), fallback["visual"]["persona_detail"]["micro_expression"])
    pd["body_language"] = _ensure_str(pd.get("body_language"), fallback["visual"]["persona_detail"]["body_language"])

    report["bgm_audio"] = _ensure_dict(report.get("bgm_audio"), fallback["bgm_audio"])
    bgm = report["bgm_audio"]
    bgm["beat_sync"] = _ensure_str(bgm.get("beat_sync"), fallback["bgm_audio"]["beat_sync"])
    bgm["emotion_fit"] = _ensure_str(bgm.get("emotion_fit"), fallback["bgm_audio"]["emotion_fit"])
    bgm["hotness_estimate"] = _ensure_str(bgm.get("hotness_estimate"), fallback["bgm_audio"]["hotness_estimate"])

    report["editing_rhythm"] = _ensure_dict(report.get("editing_rhythm"), fallback["editing_rhythm"])
    er = report["editing_rhythm"]
    er["first_3s_hook"] = _ensure_str(er.get("first_3s_hook"), fallback["editing_rhythm"]["first_3s_hook"])
    er["cut_frequency"] = _ensure_str(er.get("cut_frequency"), fallback["editing_rhythm"]["cut_frequency"])

    report["copy_logic"] = _ensure_dict(report.get("copy_logic"), fallback["copy_logic"])
    cl = report["copy_logic"]
    cl["title_hook_type"] = _ensure_str(cl.get("title_hook_type"), fallback["copy_logic"]["title_hook_type"])
    cl["seo_keywords"] = _ensure_list(cl.get("seo_keywords"), fallback["copy_logic"]["seo_keywords"])
    cl["golden_3s"] = _ensure_str(cl.get("golden_3s"), fallback["copy_logic"]["golden_3s"])
    cl["info_density"] = _ensure_str(cl.get("info_density"), fallback["copy_logic"]["info_density"])
    cl["catchphrase_frequency"] = _ensure_str(cl.get("catchphrase_frequency"), fallback["copy_logic"]["catchphrase_frequency"])
    cl["narrative_model"] = _ensure_str(cl.get("narrative_model"), fallback["copy_logic"]["narrative_model"])
    cl["on_screen_text"] = _ensure_str(cl.get("on_screen_text"), fallback["copy_logic"]["on_screen_text"])

    report["interaction_algo"] = _ensure_dict(report.get("interaction_algo"), fallback["interaction_algo"])
    ia = report["interaction_algo"]
    ia["bait_points"] = _ensure_str(ia.get("bait_points"), fallback["interaction_algo"]["bait_points"])
    ia["controversy"] = _ensure_str(ia.get("controversy"), fallback["interaction_algo"]["controversy"])
    ia["cta"] = _ensure_str(ia.get("cta"), fallback["interaction_algo"]["cta"])
    ia["completion_rate_logic"] = _ensure_str(ia.get("completion_rate_logic"), fallback["interaction_algo"]["completion_rate_logic"])
    ia["follow_like_ratio"] = _ensure_str(ia.get("follow_like_ratio"), fallback["interaction_algo"]["follow_like_ratio"])

    report["business_strategy"] = _ensure_dict(report.get("business_strategy"), fallback["business_strategy"])
    bs = report["business_strategy"]
    bs["monetization_path"] = _ensure_str(bs.get("monetization_path"), fallback["business_strategy"]["monetization_path"])
    bs["trend_stage"] = _ensure_str(bs.get("trend_stage"), fallback["business_strategy"]["trend_stage"])
    bs["cognitive_load"] = _ensure_str(bs.get("cognitive_load"), fallback["business_strategy"]["cognitive_load"])
    bs["audience_persona"] = _ensure_str(bs.get("audience_persona"), fallback["business_strategy"]["audience_persona"])

    # --- douyin_specific ---
    report["douyin_specific"] = _ensure_dict(report.get("douyin_specific"), fallback.get("douyin_specific", {}))
    dy = report["douyin_specific"]
    dy["content_type"] = _ensure_str(dy.get("content_type"), fallback.get("douyin_specific", {}).get("content_type", ""))
    dy["video_format"] = _ensure_str(dy.get("video_format"), fallback.get("douyin_specific", {}).get("video_format", ""))
    dy["duration_strategy"] = _ensure_dict(dy.get("duration_strategy"), fallback.get("douyin_specific", {}).get("duration_strategy", {}))
    dy["hashtag_strategy"] = _ensure_dict(dy.get("hashtag_strategy"), fallback.get("douyin_specific", {}).get("hashtag_strategy", {}))
    hs = dy["hashtag_strategy"]
    hs["detected_topics"] = _ensure_list(hs.get("detected_topics"), [])
    hs["recommended_topics"] = _ensure_list(hs.get("recommended_topics"), [])
    dy["douyin_native_elements"] = _ensure_dict(dy.get("douyin_native_elements"), fallback.get("douyin_specific", {}).get("douyin_native_elements", {}))
    dy["traffic_pool_prediction"] = _ensure_dict(dy.get("traffic_pool_prediction"), fallback.get("douyin_specific", {}).get("traffic_pool_prediction", {}))
    tp = dy["traffic_pool_prediction"]
    tp["breakthrough_factors"] = _ensure_list(tp.get("breakthrough_factors"), [])
    tp["risk_factors"] = _ensure_list(tp.get("risk_factors"), [])

    # --- scores ---
    report["scores"] = _ensure_dict(report.get("scores"), fallback.get("scores", {}))
    sc = report["scores"]
    sc["overall"] = _ensure_float(sc.get("overall"), 0.0)
    sc["dimensions"] = _ensure_dict(sc.get("dimensions"), fallback.get("scores", {}).get("dimensions", {}))
    for dim_key in ("hook_power", "content_value", "visual_quality", "editing_rhythm",
                     "audio_bgm", "copy_script", "interaction_design", "algorithm_friendliness", "commercial_potential"):
        dim = sc["dimensions"].get(dim_key)
        if not isinstance(dim, dict):
            dim = fallback.get("scores", {}).get("dimensions", {}).get(dim_key, {"score": 0.0, "weight": 0.1, "brief": ""})
        dim["score"] = _ensure_float(dim.get("score"), 0.0)
        dim["weight"] = _ensure_float(dim.get("weight"), 0.1)
        dim["brief"] = _ensure_str(dim.get("brief"), "")
        sc["dimensions"][dim_key] = dim
    sc["replicability"] = _ensure_dict(sc.get("replicability"), fallback.get("scores", {}).get("replicability", {}))
    rep = sc["replicability"]
    rep["score"] = _ensure_float(rep.get("score"), 0.0)
    rep["difficulty"] = _ensure_str(rep.get("difficulty"), "")
    rep["key_barriers"] = _ensure_list(rep.get("key_barriers"), [])

    # --- improvement_suggestions ---
    report["improvement_suggestions"] = _ensure_dict(report.get("improvement_suggestions"), fallback.get("improvement_suggestions", {}))
    imp = report["improvement_suggestions"]
    if not isinstance(imp.get("priority_actions"), list):
        imp["priority_actions"] = []
    for action in imp["priority_actions"]:
        if isinstance(action, dict):
            action["category"] = _ensure_str(action.get("category"), "other")
            action["urgency"] = _ensure_str(action.get("urgency"), "medium")
            action["current_issue"] = _ensure_str(action.get("current_issue"), "")
            action["suggestion"] = _ensure_str(action.get("suggestion"), "")
            action["expected_impact"] = _ensure_str(action.get("expected_impact"), "")
    imp["copy_rewrite"] = _ensure_dict(imp.get("copy_rewrite"), {"original_title": "", "suggested_titles": [], "title_optimization_notes": ""})
    cr = imp["copy_rewrite"]
    cr["original_title"] = _ensure_str(cr.get("original_title"), "")
    cr["suggested_titles"] = _ensure_list(cr.get("suggested_titles"), [])
    cr["title_optimization_notes"] = _ensure_str(cr.get("title_optimization_notes"), "")
    if not isinstance(imp.get("editing_suggestions"), list):
        imp["editing_suggestions"] = []
    imp["algorithm_optimization"] = _ensure_list(imp.get("algorithm_optimization"), [])
    if not isinstance(imp.get("a_b_test_suggestions"), list):
        imp["a_b_test_suggestions"] = []

    # --- performance_attribution (optional, only when metrics provided) ---
    if "performance_attribution" in report:
        pa = report["performance_attribution"]
        if isinstance(pa, dict):
            pa["data_vs_content_alignment"] = _ensure_str(pa.get("data_vs_content_alignment"), "")
            if not isinstance(pa.get("positive_factors"), list):
                pa["positive_factors"] = []
            if not isinstance(pa.get("negative_factors"), list):
                pa["negative_factors"] = []
            pa["benchmark"] = _ensure_dict(pa.get("benchmark"), {})

    # --- ai_insights ---
    report["ai_insights"] = _ensure_dict(report.get("ai_insights"), fallback["ai_insights"])
    ai = report["ai_insights"]
    ai["semantic_tags"] = _ensure_list(ai.get("semantic_tags"), fallback["ai_insights"]["semantic_tags"])
    ai["replicability_score"] = _ensure_float(ai.get("replicability_score"), fallback["ai_insights"]["replicability_score"])
    ai["emotion_curve"] = _normalize_curve(ai.get("emotion_curve"))

    return report


def _normalize_report(
    report: dict[str, Any], video_id: str, original_name: str, fallback: dict[str, Any]
) -> dict[str, Any]:
    report = _coerce_report(report, fallback)
    report.setdefault("meta", {})
    report["meta"]["video_id"] = video_id
    report["meta"]["original_name"] = original_name
    report["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat()
    return report


def _extract_usage(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None
    prompt_tokens = getattr(usage, "prompt_token_count", None)
    response_tokens = getattr(usage, "candidates_token_count", None)
    total_tokens = getattr(usage, "total_token_count", None)
    cost_per_1k = float(os.getenv("GEMINI_COST_PER_1K", "0") or 0)
    cost_usd = round((float(total_tokens) / 1000.0) * cost_per_1k, 6) if total_tokens else None
    return {
        "prompt_tokens": prompt_tokens,
        "response_tokens": response_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
    }


def analyze_video(
    video_id: str,
    original_name: str,
    video_path: Path,
    context: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    fallback = _build_placeholder_report(video_id, original_name, context)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return (
            _set_llm_notice(fallback, "missing_api_key", "未配置 Gemini API Key，无法启用多模态 LLM。"),
            None,
            False,
        )
    if not video_path.exists():
        return (
            _set_llm_notice(fallback, "video_missing", "视频文件不存在，无法调用多模态 LLM。"),
            None,
            False,
        )

    try:
        import google.generativeai as genai
    except Exception as exc:
        return (
            _set_llm_notice(
                fallback,
                "missing_dependency",
                "未安装 google-generativeai，无法启用多模态 LLM。",
                str(exc),
            ),
            None,
            False,
        )

    def _is_retryable(err: Exception) -> bool:
        msg = str(err).lower()
        return "ssl" in msg or "eof" in msg or "connection" in msg or "retries exceeded" in msg

    try:
        genai.configure(api_key=api_key, transport="rest")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        model = genai.GenerativeModel(model_name)

        last_err = None
        for attempt in range(3):
            try:
                video_file = genai.upload_file(str(video_path))
                break
            except Exception as e:
                last_err = e
                if not _is_retryable(e) or attempt == 2:
                    raise
                time.sleep(2)
        else:
            raise last_err

        max_wait = 120
        poll_interval = 3
        waited = 0
        while waited < max_wait:
            try:
                file_status = genai.get_file(video_file.name)
            except Exception as e:
                if _is_retryable(e) and waited < max_wait - 6:
                    time.sleep(2)
                    waited += 2
                    continue
                raise
            state = getattr(file_status, "state", None)
            state_name = getattr(state, "name", str(state)) if state else ""
            if state_name == "ACTIVE":
                break
            if state_name == "FAILED":
                return (
                    _set_llm_notice(
                        fallback,
                        "file_processing_failed",
                        "Gemini 视频文件处理失败，请重试。",
                    ),
                    None,
                    False,
                )
            time.sleep(poll_interval)
            waited += poll_interval
        else:
            return (
                _set_llm_notice(
                    fallback,
                    "file_processing_timeout",
                    f"Gemini 视频文件处理超时（{max_wait}s），请重试或使用更短的视频。",
                ),
                None,
                False,
            )

        last_err = None
        for attempt in range(3):
            try:
                response = model.generate_content([video_file, _build_prompt(context, metrics)])
                break
            except Exception as e:
                last_err = e
                if not _is_retryable(e) or attempt == 2:
                    raise
                time.sleep(2)
        else:
            raise last_err
        report = _extract_json(getattr(response, "text", "") or "")
        if not report:
            return (
                _set_llm_notice(
                    fallback,
                    "invalid_llm_response",
                    "大模型已调用，但返回结果无法解析为 JSON。",
                ),
                _extract_usage(response),
                True,
            )

        normalized = _normalize_report(report, video_id, original_name, fallback)
        return normalized, _extract_usage(response), True
    except Exception as exc:
        detail = str(exc)
        hint = ""
        if "ssl" in detail.lower() or "eof" in detail.lower() or "connection" in detail.lower():
            hint = "（若在国内，请确保代理已开启并重启应用）"
        return (
            _set_llm_notice(
                fallback,
                "llm_request_failed",
                "大模型调用失败，请检查网络/配额/模型权限。" + hint,
                detail,
            ),
            None,
            False,
        )


def render_markdown(report: dict[str, Any], emotion_curve: list[dict[str, float]]) -> str:
    def line(key: str, value: str) -> str:
        return f"- **{key}**：{value}"

    visual = report.get("visual", {}) if isinstance(report.get("visual"), dict) else {}
    persona_detail = visual.get("persona_detail", {}) if isinstance(visual.get("persona_detail"), dict) else {}
    bgm_audio = report.get("bgm_audio", {}) if isinstance(report.get("bgm_audio"), dict) else {}
    editing_rhythm = report.get("editing_rhythm", {}) if isinstance(report.get("editing_rhythm"), dict) else {}
    copy_logic = report.get("copy_logic", {}) if isinstance(report.get("copy_logic"), dict) else {}
    interaction_algo = report.get("interaction_algo", {}) if isinstance(report.get("interaction_algo"), dict) else {}
    business_strategy = report.get("business_strategy", {}) if isinstance(report.get("business_strategy"), dict) else {}
    ai_insights = report.get("ai_insights", {}) if isinstance(report.get("ai_insights"), dict) else {}
    douyin_specific = report.get("douyin_specific", {}) if isinstance(report.get("douyin_specific"), dict) else {}
    scores = report.get("scores", {}) if isinstance(report.get("scores"), dict) else {}
    improvement = report.get("improvement_suggestions", {}) if isinstance(report.get("improvement_suggestions"), dict) else {}

    seo_keywords = copy_logic.get("seo_keywords", [])
    if not isinstance(seo_keywords, list):
        seo_keywords = [str(seo_keywords)] if seo_keywords else []
    semantic_tags = ai_insights.get("semantic_tags", [])
    if not isinstance(semantic_tags, list):
        semantic_tags = [str(semantic_tags)] if semantic_tags else []
    visual_elements = visual.get("visual_elements", [])
    if not isinstance(visual_elements, list):
        visual_elements = [str(visual_elements)] if visual_elements else []

    curve_tip = "已生成情绪曲线图与结构化数据。" if emotion_curve else "未生成情绪曲线（需启用多模态 LLM）。"
    curve_preview = emotion_curve[:10] if emotion_curve else []

    # scores rendering
    dims = scores.get("dimensions", {})
    score_lines: list[str] = []
    if dims and isinstance(dims, dict):
        score_lines.append(f"- **综合评分**：{scores.get('overall', 0)}/10")
        dim_labels = {
            "hook_power": "钩子力", "content_value": "内容价值", "visual_quality": "画面质量",
            "editing_rhythm": "剪辑节奏", "audio_bgm": "音频/BGM", "copy_script": "文案脚本",
            "interaction_design": "互动设计", "algorithm_friendliness": "算法友好度", "commercial_potential": "商业潜力",
        }
        for key, label in dim_labels.items():
            d = dims.get(key, {})
            if isinstance(d, dict):
                score_lines.append(f"- **{label}**：{d.get('score', 0)}/10（权重 {d.get('weight', 0)}）— {d.get('brief', '')}")
        rep = scores.get("replicability", {})
        if isinstance(rep, dict):
            barriers = rep.get("key_barriers", [])
            barrier_text = "、".join(barriers) if isinstance(barriers, list) else str(barriers)
            score_lines.append(f"- **复刻可行性**：{rep.get('score', 0)}，难度 {rep.get('difficulty', '')}，壁垒：{barrier_text}")

    # improvement rendering
    imp_lines: list[str] = []
    actions = improvement.get("priority_actions", [])
    if isinstance(actions, list):
        for i, act in enumerate(actions, 1):
            if isinstance(act, dict):
                urgency = act.get("urgency", "")
                imp_lines.append(f"### 优先改进 {i}（{urgency}）")
                imp_lines.append(f"- **问题**：{act.get('current_issue', '')}")
                imp_lines.append(f"- **建议**：{act.get('suggestion', '')}")
                imp_lines.append(f"- **预期效果**：{act.get('expected_impact', '')}")
                imp_lines.append("")
    cr = improvement.get("copy_rewrite", {})
    if isinstance(cr, dict) and cr.get("suggested_titles"):
        imp_lines.append("### 标题优化建议")
        imp_lines.append(f"- **原标题**：{cr.get('original_title', '')}")
        for j, title in enumerate(cr.get("suggested_titles", []), 1):
            imp_lines.append(f"- **方案 {j}**：{title}")
        imp_lines.append(f"- **优化思路**：{cr.get('title_optimization_notes', '')}")
        imp_lines.append("")
    algo_opt = improvement.get("algorithm_optimization", [])
    if isinstance(algo_opt, list) and algo_opt:
        imp_lines.append("### 算法优化建议")
        for tip in algo_opt:
            imp_lines.append(f"- {tip}")
        imp_lines.append("")
    edit_sug = improvement.get("editing_suggestions", [])
    if isinstance(edit_sug, list) and edit_sug:
        imp_lines.append("### 剪辑改进建议")
        for es in edit_sug:
            if isinstance(es, dict):
                imp_lines.append(f"- **{es.get('timestamp_sec', '?')}s**：{es.get('suggestion', '')}")
        imp_lines.append("")
    ab = improvement.get("a_b_test_suggestions", [])
    if isinstance(ab, list) and ab:
        imp_lines.append("### A/B 测试方案")
        for t in ab:
            if isinstance(t, dict):
                imp_lines.append(f"- **{t.get('variable', '')}**：A={t.get('version_a', '')} vs B={t.get('version_b', '')}")
        imp_lines.append("")

    # douyin specific rendering
    dy_lines: list[str] = []
    if douyin_specific:
        dy_lines.append(line("内容类型", str(douyin_specific.get("content_type", ""))))
        dy_lines.append(line("视频格式", str(douyin_specific.get("video_format", ""))))
        ds = douyin_specific.get("duration_strategy", {})
        if isinstance(ds, dict):
            dy_lines.append(line("时长评估", str(ds.get("actual_duration_assessment", ""))))
            dy_lines.append(line("建议时长", str(ds.get("optimal_duration_suggestion", ""))))
        hs = douyin_specific.get("hashtag_strategy", {})
        if isinstance(hs, dict):
            detected = hs.get("detected_topics", [])
            recommended = hs.get("recommended_topics", [])
            dy_lines.append(line("检测到的话题", "、".join(detected) if isinstance(detected, list) else str(detected)))
            dy_lines.append(line("推荐话题", "、".join(recommended) if isinstance(recommended, list) else str(recommended)))
            dy_lines.append(line("话题热度", str(hs.get("topic_heat_assessment", ""))))
        dne = douyin_specific.get("douyin_native_elements", {})
        if isinstance(dne, dict):
            dy_lines.append(line("贴纸/特效", str(dne.get("sticker_effects", ""))))
            dy_lines.append(line("合拍潜力", str(dne.get("duet_potential", ""))))
            dy_lines.append(line("挑战赛关联", str(dne.get("challenge_relevance", ""))))
            dy_lines.append(line("定位/POI", str(dne.get("poi_usage", ""))))
            dy_lines.append(line("小黄车/商品", str(dne.get("shopping_cart", ""))))
        tp = douyin_specific.get("traffic_pool_prediction", {})
        if isinstance(tp, dict):
            dy_lines.append(line("流量池预测", str(tp.get("estimated_level", ""))))
            bf = tp.get("breakthrough_factors", [])
            rf = tp.get("risk_factors", [])
            dy_lines.append(line("有利因素", "、".join(bf) if isinstance(bf, list) else str(bf)))
            dy_lines.append(line("风险因素", "、".join(rf) if isinstance(rf, list) else str(rf)))

    # interaction_algo enhanced sub-fields
    ia_extra_lines: list[str] = []
    crd = interaction_algo.get("completion_rate_design", {})
    if isinstance(crd, dict) and any(crd.values()):
        ia_extra_lines.append(line("前3秒拦截强度", str(crd.get("hook_strength", ""))))
        ia_extra_lines.append(line("循环播放设计", str(crd.get("loop_design", ""))))
        ia_extra_lines.append(line("进度条悬念", str(crd.get("progress_bar_suspense", ""))))
        ia_extra_lines.append(line("时长-密度匹配", str(crd.get("duration_content_match", ""))))
    ci = interaction_algo.get("comment_inducement", {})
    if isinstance(ci, dict) and any(ci.values()):
        ia_extra_lines.append(line("评论引导类型", str(ci.get("question_type", ""))))
        ia_extra_lines.append(line("争议度", str(ci.get("controversy_level", ""))))
        ia_extra_lines.append(line("预测高频评论", str(ci.get("comment_template_prediction", ""))))
    sm = interaction_algo.get("share_motivation", {})
    if isinstance(sm, dict) and any(sm.values()):
        ia_extra_lines.append(line("实用价值", str(sm.get("utility_value", ""))))
        ia_extra_lines.append(line("社交货币", str(sm.get("social_currency", ""))))
        ia_extra_lines.append(line("情绪感染力", str(sm.get("emotional_contagion", ""))))
    nsr = interaction_algo.get("negative_signal_risk", {})
    if isinstance(nsr, dict) and any(nsr.values()):
        skip_pts = nsr.get("skip_risk_points", [])
        ia_extra_lines.append(line("滑走风险点", "、".join(str(p) for p in skip_pts) if isinstance(skip_pts, list) else str(skip_pts)))
        ia_extra_lines.append(line("不感兴趣风险", str(nsr.get("dislike_risk", ""))))
        ia_extra_lines.append(line("举报风险", str(nsr.get("report_risk", ""))))

    # business_strategy enhanced sub-fields
    bs_extra_lines: list[str] = []
    dp = business_strategy.get("dou_plus_assessment", {})
    if isinstance(dp, dict) and any(dp.values()):
        bs_extra_lines.append(line("DOU+投放建议", f"{'值得投放' if dp.get('worth_investing') else '不建议投放'}"))
        bs_extra_lines.append(line("建议预算", str(dp.get("recommended_budget_tier", ""))))
        bs_extra_lines.append(line("投放人群", str(dp.get("target_audience_suggestion", ""))))
        bs_extra_lines.append(line("预期ROI", str(dp.get("expected_roi_range", ""))))
    if business_strategy.get("content_lifecycle_prediction"):
        bs_extra_lines.append(line("内容生命周期", str(business_strategy["content_lifecycle_prediction"])))
    ad = business_strategy.get("audience_detail", {})
    if isinstance(ad, dict) and any(ad.values()):
        bs_extra_lines.append(line("年龄段", str(ad.get("age_range", ""))))
        bs_extra_lines.append(line("性别偏向", str(ad.get("gender_skew", ""))))
        bs_extra_lines.append(line("城市线级", str(ad.get("city_tier", ""))))
        tags = ad.get("interest_tags", [])
        bs_extra_lines.append(line("兴趣标签", "、".join(tags) if isinstance(tags, list) else str(tags)))
        bs_extra_lines.append(line("消费力", str(ad.get("consumption_power", ""))))

    # performance_attribution (when metrics were provided)
    pa_lines: list[str] = []
    pa = report.get("performance_attribution")
    if isinstance(pa, dict):
        pa_lines.append(line("数据与内容匹配度", str(pa.get("data_vs_content_alignment", ""))))
        for pf in pa.get("positive_factors", []):
            if isinstance(pf, dict):
                pa_lines.append(f"  - ✅ {pf.get('factor', '')}（{pf.get('estimated_contribution', '')}）")
        for nf in pa.get("negative_factors", []):
            if isinstance(nf, dict):
                pa_lines.append(f"  - ❌ {nf.get('factor', '')}（{nf.get('estimated_contribution', '')}）")
        bm = pa.get("benchmark", {})
        if isinstance(bm, dict):
            pa_lines.append(line("同类均值完播率", str(bm.get("category_avg_completion_rate", ""))))
            pa_lines.append(line("对比基准", str(bm.get("actual_vs_benchmark", ""))))

    md = [
        "# 短视频多维度分析报告（抖音特化）",
        "",
        "## 概览",
        str(report.get("summary", "")),
        "",
    ]

    # Scores section
    if score_lines:
        md.append("## 多维评分")
        md.extend(score_lines)
        md.append("")

    md.extend([
        "## 画面视觉",
        line("构图与景别", f"{visual.get('composition', '')} / {visual.get('shot_type', '')}"),
        line("光影色调", str(visual.get("lighting_tone", ""))),
        line("人设表现", str(visual.get("persona", ""))),
        line("颜值/气质", str(persona_detail.get("appearance", ""))),
        line("穿搭细节", str(persona_detail.get("outfit", ""))),
        line("微表情", str(persona_detail.get("micro_expression", ""))),
        line("肢体语言", str(persona_detail.get("body_language", ""))),
        line("场景语义", str(visual.get("scene_semantics", ""))),
        line("画面元素", "、".join(visual_elements) if visual_elements else "未提取"),
        "",
        "## BGM 与音效",
        line("节奏卡点", str(bgm_audio.get("beat_sync", ""))),
        line("情绪适配", str(bgm_audio.get("emotion_fit", ""))),
        line("热度属性", str(bgm_audio.get("hotness_estimate", ""))),
        "",
        "## 剪辑节奏",
        line("前 3 秒钩子", str(editing_rhythm.get("first_3s_hook", ""))),
        line("剪辑频率", str(editing_rhythm.get("cut_frequency", ""))),
        "",
        "## 文案与逻辑",
        line("标题钩子类型", str(copy_logic.get("title_hook_type", ""))),
        line("SEO 关键词", "、".join(seo_keywords)),
        line("黄金 3 秒", str(copy_logic.get("golden_3s", ""))),
        line("信息密度", str(copy_logic.get("info_density", ""))),
        line("金句频率", str(copy_logic.get("catchphrase_frequency", ""))),
        line("叙事模型", str(copy_logic.get("narrative_model", ""))),
        line("画面花字", str(copy_logic.get("on_screen_text", ""))),
        "",
        "## 互动与算法",
        line("互动埋点", str(interaction_algo.get("bait_points", ""))),
        line("争议话题", str(interaction_algo.get("controversy", ""))),
        line("CTA", str(interaction_algo.get("cta", ""))),
        line("完播率逻辑", str(interaction_algo.get("completion_rate_logic", ""))),
        line("粉赞比预测", str(interaction_algo.get("follow_like_ratio", ""))),
    ])
    if ia_extra_lines:
        md.extend(ia_extra_lines)
    md.append("")

    md.extend([
        "## 商业与战略",
        line("变现路径", str(business_strategy.get("monetization_path", ""))),
        line("趋势定位", str(business_strategy.get("trend_stage", ""))),
        line("认知负荷", str(business_strategy.get("cognitive_load", ""))),
        line("受众画像", str(business_strategy.get("audience_persona", ""))),
    ])
    if bs_extra_lines:
        md.extend(bs_extra_lines)
    md.append("")

    # Douyin specific
    if dy_lines:
        md.append("## 抖音特化分析")
        md.extend(dy_lines)
        md.append("")

    # Performance attribution
    if pa_lines:
        md.append("## 数据归因分析")
        md.extend(pa_lines)
        md.append("")

    md.extend([
        "## AI 深度洞察",
        line("语义标签", "、".join(semantic_tags)),
        line("复刻可行性评分", str(ai_insights.get("replicability_score", ""))),
        "",
    ])

    # Improvement suggestions
    if imp_lines:
        md.append("## 改进建议")
        md.extend(imp_lines)

    md.extend([
        "## 情绪曲线（示意）",
        curve_tip,
        "",
        "## 情绪曲线数据（前 10 点示例）",
        "```json",
        json.dumps(curve_preview, ensure_ascii=False),
        "```",
        "",
        "## 解析输入（节选）",
        "```json",
        json.dumps(report.get("analysis_inputs", {}), ensure_ascii=False, indent=2, default=str)[:2000],
        "```",
    ])
    return "\n".join(md)


def render_text(report: dict[str, Any]) -> str:
    scores = report.get("scores", {})
    dims = scores.get("dimensions", {}) if isinstance(scores, dict) else {}
    dim_labels = {
        "hook_power": "钩子力", "content_value": "内容价值", "visual_quality": "画面质量",
        "editing_rhythm": "剪辑节奏", "audio_bgm": "音频/BGM", "copy_script": "文案脚本",
        "interaction_design": "互动设计", "algorithm_friendliness": "算法友好度", "commercial_potential": "商业潜力",
    }
    score_text = ""
    if isinstance(dims, dict) and dims:
        score_text = f"综合评分：{scores.get('overall', 0)}/10\n"
        for key, label in dim_labels.items():
            d = dims.get(key, {})
            if isinstance(d, dict):
                score_text += f"  {label}：{d.get('score', 0)}/10 — {d.get('brief', '')}\n"

    imp = report.get("improvement_suggestions", {})
    imp_text = ""
    if isinstance(imp, dict):
        actions = imp.get("priority_actions", [])
        if isinstance(actions, list) and actions:
            imp_text = "改进建议：\n"
            for i, act in enumerate(actions, 1):
                if isinstance(act, dict):
                    imp_text += f"  {i}. [{act.get('urgency', '')}] {act.get('current_issue', '')} → {act.get('suggestion', '')}（{act.get('expected_impact', '')}）\n"

    parts = [
        "短视频多维度分析报告（抖音特化）",
        "",
        f"概览：{report.get('summary', '')}",
        "",
    ]
    if score_text:
        parts.append(score_text)
    parts.extend([
        f"画面视觉：{json.dumps(report.get('visual', {}), ensure_ascii=False, default=str)}",
        f"BGM 与音效：{json.dumps(report.get('bgm_audio', {}), ensure_ascii=False, default=str)}",
        f"剪辑节奏：{json.dumps(report.get('editing_rhythm', {}), ensure_ascii=False, default=str)}",
        f"文案与逻辑：{json.dumps(report.get('copy_logic', {}), ensure_ascii=False, default=str)}",
        f"互动与算法：{json.dumps(report.get('interaction_algo', {}), ensure_ascii=False, default=str)}",
        f"商业与战略：{json.dumps(report.get('business_strategy', {}), ensure_ascii=False, default=str)}",
        f"抖音特化：{json.dumps(report.get('douyin_specific', {}), ensure_ascii=False, default=str)}",
        f"AI 洞察：{json.dumps(report.get('ai_insights', {}), ensure_ascii=False, default=str)}",
        "",
    ])
    if imp_text:
        parts.append(imp_text)
    return "\n".join(parts)


def _sanitize_filename(name: str) -> str:
    name = Path(name).stem
    invalid_chars = r'<>:"/\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    name = name.strip(" .")
    return name or "video"


def _get_unique_path(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent
    counter = 1
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def pack_report_bundle(
    original_name: str,
    json_path: Path | str | None = None,
    md_path: Path | str | None = None,
    txt_path: Path | str | None = None,
    curve_path: Path | str | None = None,
    output_dir: Path | None = None,
    analysis_time: datetime | None = None,
) -> Path | None:
    if output_dir is None:
        output_dir = DEFAULT_REPORT_OUTPUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if analysis_time is None:
        analysis_time = datetime.now()

    video_name = _sanitize_filename(original_name)
    date_str = analysis_time.strftime("%Y%m%d")
    zip_filename = f"{video_name}-{date_str}.zip"
    zip_path = _get_unique_path(output_dir / zip_filename)

    files_to_pack: list[tuple[Path, str]] = []
    if json_path and Path(json_path).exists():
        files_to_pack.append((Path(json_path), "report.json"))
    if md_path and Path(md_path).exists():
        files_to_pack.append((Path(md_path), "report.md"))
    if txt_path and Path(txt_path).exists():
        files_to_pack.append((Path(txt_path), "report.txt"))
    if curve_path and Path(curve_path).exists():
        files_to_pack.append((Path(curve_path), "emotion_curve.png"))
    if not files_to_pack:
        return None

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path, arcname in files_to_pack:
                zf.write(file_path, arcname=arcname)
        return zip_path
    except Exception:
        if zip_path.exists():
            try:
                zip_path.unlink()
            except Exception:
                pass
        return None
