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


def _build_prompt(context: dict[str, Any] | None = None) -> str:
    prompt = (
        "你是短视频分析助手。请根据给定视频内容输出严格 JSON，不要额外文字。\n"
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
        '    "completion_rate_logic": "", "follow_like_ratio": ""\n'
        "  },\n"
        '  "business_strategy": {\n'
        '    "monetization_path": "", "trend_stage": "",\n'
        '    "cognitive_load": "", "audience_persona": ""\n'
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
                response = model.generate_content([video_file, _build_prompt(context)])
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

    md = [
        "# 短视频多维度分析报告",
        "",
        "## 概览",
        str(report.get("summary", "")),
        "",
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
        "",
        "## 商业与战略",
        line("变现路径", str(business_strategy.get("monetization_path", ""))),
        line("趋势定位", str(business_strategy.get("trend_stage", ""))),
        line("认知负荷", str(business_strategy.get("cognitive_load", ""))),
        line("受众画像", str(business_strategy.get("audience_persona", ""))),
        "",
        "## AI 深度洞察",
        line("语义标签", "、".join(semantic_tags)),
        line("复刻可行性评分", str(ai_insights.get("replicability_score", ""))),
        "",
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
    ]
    return "\n".join(md)


def render_text(report: dict[str, Any]) -> str:
    parts = [
        "短视频多维度分析报告",
        "",
        f"概览：{report.get('summary', '')}",
        "",
        f"画面视觉：{report.get('visual', {})}",
        f"BGM 与音效：{report.get('bgm_audio', {})}",
        f"剪辑节奏：{report.get('editing_rhythm', {})}",
        f"文案与逻辑：{report.get('copy_logic', {})}",
        f"互动与算法：{report.get('interaction_algo', {})}",
        f"商业与战略：{report.get('business_strategy', {})}",
        f"AI 洞察：{report.get('ai_insights', {})}",
    ]
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
