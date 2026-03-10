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
        '{ "summary":"", "visual":{"composition":"","shot_type":"","lighting_tone":"","persona":"","persona_detail":{"appearance":"","outfit":"","micro_expression":"","body_language":""},"scene_semantics":"","visual_elements":[]}, "bgm_audio":{"beat_sync":"","emotion_fit":"","hotness_estimate":""}, "editing_rhythm":{"first_3s_hook":"","cut_frequency":""}, "copy_logic":{"title_hook_type":"","seo_keywords":[],"golden_3s":"","info_density":"","catchphrase_frequency":"","narrative_model":"","on_screen_text":""}, "interaction_algo":{"bait_points":"","controversy":"","cta":"","completion_rate_logic":"","follow_like_ratio":""}, "business_strategy":{"monetization_path":"","trend_stage":"","cognitive_load":"","audience_persona":""}, "ai_insights":{"semantic_tags":[],"replicability_score":0.0,"emotion_curve":[{"t":0,"v":0.3}]}}'
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


def _normalize_curve(value: Any, fallback_curve: list[dict[str, float]]) -> list[dict[str, float]]:
    if not isinstance(value, list):
        return fallback_curve
    points: list[dict[str, float]] = []
    for idx, item in enumerate(value):
        if isinstance(item, dict):
            t = item.get("t", idx)
            v = item.get("v", 0.0)
        else:
            continue
        try:
            t_val = float(t)
            v_val = max(0.0, min(1.0, float(v)))
            points.append({"t": t_val, "v": v_val})
        except Exception:
            continue
    return points or fallback_curve


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

        response = model.generate_content([video_file, _build_prompt(context)])
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

        report.setdefault("meta", {})
        report["meta"]["video_id"] = video_id
        report["meta"]["original_name"] = original_name
        report["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat()
        report.setdefault("ai_insights", {})
        report["ai_insights"]["emotion_curve"] = _normalize_curve(
            report["ai_insights"].get("emotion_curve"), fallback["ai_insights"]["emotion_curve"]
        )
        return report, _extract_usage(response), True
    except Exception as exc:
        return (
            _set_llm_notice(
                fallback,
                "llm_request_failed",
                "大模型调用失败，请检查网络/配额/模型权限。",
                str(exc),
            ),
            None,
            False,
        )


def render_markdown(report: dict[str, Any], emotion_curve: list[dict[str, float]]) -> str:
    tags = report.get("ai_insights", {}).get("semantic_tags", [])
    if not isinstance(tags, list):
        tags = []
    return "\n".join(
        [
            "# 短视频多维度分析报告",
            "",
            "## 概览",
            str(report.get("summary", "")),
            "",
            "## AI 深度洞察",
            f"- 语义标签：{'、'.join([str(t) for t in tags]) if tags else '无'}",
            f"- 复刻可行性评分：{report.get('ai_insights', {}).get('replicability_score', '')}",
            "",
            "## 情绪曲线数据（前 10 点示例）",
            "```json",
            json.dumps(emotion_curve[:10], ensure_ascii=False),
            "```",
            "",
            "## 解析输入（节选）",
            "```json",
            json.dumps(report.get("analysis_inputs", {}), ensure_ascii=False, indent=2, default=str)[:2000],
            "```",
        ]
    )


def render_text(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "短视频多维度分析报告",
            "",
            f"概览：{report.get('summary', '')}",
            f"AI 洞察：{report.get('ai_insights', {})}",
        ]
    )


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
