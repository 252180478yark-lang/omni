"""竞品人群逆向分析（2026-06-12）：reverse_audience_analysis。

段一（必跑）：竞品视频（本地路径 / 抖音分享链接）→ Gemini Files API 视频理解 →
8 项人群信号提取（演员人设/场景档次/话术诉求/BGM/字幕/钩子/价格信号/CTA）→
竞品人群假设（V4.1 Part A 裁剪：核心服务人群假设 1-3 个 + 核心沟通主张 + 它没在打谁）。

段二（条件跑）：有 portrait_id（或 sku_id 能拉到 step 3.5 画像，adopted 优先）时，
竞品假设 vs 自家画像文本对照 → 对照表 / 人群空白四区映射（红海/抢夺/蓝海/必争）/
可借鉴打法 3-5 条。段二任何失败 fail-open：只返段一 + warning。

跟 reverse_storyboard_video 分工：那边反推「怎么拍」（喂回 AI 生成模型的故事板
prompt 包），这边反推「打什么人」（竞品人群假设 + 自家画像对照）。

v1 不落库（照 competitor_search 先例只出 md 报告）。
"""
from __future__ import annotations

import logging
import os
import re
import time

logger = logging.getLogger(__name__)

from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.services import pipeline_lineage
from app.services.ai_hub_client import AIHubClient


# ============ 确定性校验（防臆想三道闸·竞品侧） ============

_FAKE_KB_RE = re.compile(r"\[KB[:：][^\]]*\]")
# "看起来精确的数字"：带量纲/比例的才算（列表序号"1." / "假设 2"不触发）
_NUM_UNIT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|万|亿|元|块|岁|线城市)")


def _validate_reverse_persona(persona_md: str) -> list[str]:
    """竞品人群假设确定性校验。返回警告列表（空 = 过）。

    - 全文无 🧠/⚠️ 标记 → 警告（违反防臆想铁律）
    - 出现 [KB:] → 警告"伪 KB 锚"（竞品反推只看视频，没有 KB 依据）
    - 含量纲数字的行没标 ⚠️ → 警告（数字必须当推测处理）
    """
    if not (persona_md or "").strip():
        return ["⚠ persona_md 为空——LLM 没产出竞品人群假设，建议重跑"]
    warnings: list[str] = []
    if "🧠" not in persona_md and "⚠" not in persona_md:
        warnings.append("⚠ 竞品人群假设没有任何可信度标记（🧠/⚠️）——违反防臆想铁律，建议重跑")
    if _FAKE_KB_RE.search(persona_md):
        warnings.append(
            "⚠ 出现 [KB:] 伪锚——竞品反推只看了视频、没有任何 KB 依据，"
            "[KB:] 标记不可信，建议重跑"
        )
    unmarked = [
        line.strip()[:40]
        for line in persona_md.splitlines()
        if _NUM_UNIT_RE.search(line) and "⚠" not in line
    ]
    if unmarked:
        warnings.append(
            f"⚠ {len(unmarked)} 行含数字但没标 ⚠️（视频里推不出精确数，数字一律当推测）："
            f"{unmarked[:3]}"
        )
    return warnings


# ============ 信号摘要渲染 ============

_SIGNAL_LABELS = [
    ("actor_persona", "演员人设"),
    ("scene_class", "场景档次→消费力"),
    ("claims", "话术诉求"),
    ("bgm", "BGM"),
    ("subtitles", "字幕"),
    ("hook", "钩子"),
    ("price_signals", "价格信号"),
    ("cta", "CTA→漏斗位"),
]


def _format_signals_md(signals: dict) -> str:
    """8 项信号 dict → markdown 表（缺项标（无），不硬编）。"""
    lines = ["| 信号 | 观察 |", "|---|---|"]
    known = {k for k, _ in _SIGNAL_LABELS}
    for key, label in _SIGNAL_LABELS:
        v = signals.get(key)
        if isinstance(v, (list, tuple)):
            v = "；".join(str(x) for x in v if x)
        v = (str(v).strip() if v else "") or "（无）"
        lines.append(f"| {label} | {v.replace(chr(10), ' ')} |")
    for key in signals:
        if key in known:
            continue
        v = signals.get(key)
        if isinstance(v, (list, tuple)):
            v = "；".join(str(x) for x in v if x)
        if v:
            lines.append(f"| {key} | {str(v).replace(chr(10), ' ')} |")
    return "\n".join(lines)


# ============ 段二：自家画像对照（fail-open） ============

async def _compare_with_portrait(
    cfg: dict,
    *,
    persona_md: str,
    signals_md: str,
    funnel_guess: str,
    portrait_md: str,
    competitor_hint: str | None,
    extra_context: str | None,
) -> tuple[str, str]:
    """竞品假设 vs 自家画像文本对照。返回 (comparison_md, final_prompt)。异常上抛由调用方 fail-open。"""
    sys_msg = prompts.load("reverse_audience_compare.system")
    user_msg = prompts.render(
        "reverse_audience_compare.user",
        competitor_persona_md=persona_md.strip(),
        signals_md=signals_md.strip(),
        funnel_guess=(funnel_guess or "（段一未给出）").strip(),
        portrait_md=portrait_md.strip(),
        competitor_hint_block=(competitor_hint or "").strip() or "（无）",
        extra_context_block=(extra_context or "").strip() or "（无）",
    )
    client = AIHubClient(timeout=360.0)
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=cfg.get("provider", "gemini"),
        model=cfg.get("model", "gemini-2.5-flash"),
        temperature=float(cfg.get("temperature", 0.3)),
        max_tokens=int(cfg.get("max_tokens", 16000)),
        enforce_human_voice=True,
    )
    md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()
    if not md:
        raise RuntimeError("compare LLM 返回空内容")
    return md, sys_msg + "\n\n" + user_msg


async def _resolve_portrait(
    portrait_id: str | None, sku_id: str | None,
) -> tuple[dict | None, list[str]]:
    """段二画像路由：portrait_id 直取；sku_id 拉最新 adopted（无则最新 draft）。
    拿不到不报错——返回 (None, warnings) 让段一照常出（fail-open）。"""
    warnings: list[str] = []
    if portrait_id:
        portrait = await pipeline_lineage.get_audience_portrait(portrait_id)
        if portrait:
            return portrait, warnings
        warnings.append(f"⚠ portrait_id={portrait_id} 未找到——跳过对照，只返竞品假设")
        return None, warnings
    if sku_id:
        rows = await pipeline_lineage.list_audience_portraits(sku_id=sku_id, limit=30)
        pick = next((r for r in rows if r.get("status") == "adopted"), None) \
            or (rows[0] if rows else None)
        if pick:
            portrait = await pipeline_lineage.get_audience_portrait(pick["id"])
            if portrait:
                return portrait, warnings
        warnings.append(
            f"⚠ sku_id={sku_id} 没有任何画像（pipeline.audience_portraits 空）——"
            "先跑 step 3.5 generate_audience_portrait 再来对照"
        )
        return None, warnings
    warnings.append(
        "⚠ 未传 portrait_id / sku_id——本次只出竞品人群假设；"
        "要对照自家画像，补 portrait_id（或 sku_id 自动拉最新 adopted 画像）重跑"
    )
    return None, warnings


# ============ markdown 报告 ============

_FOOTER = "竞品人群假设全部为视频推演，真实人群以投放数据为准。"


def _render_markdown(
    *,
    signals_md: str,
    persona_md: str,
    funnel_guess: str,
    confidence_notes: list,
    comparison_md: str | None,
    compared_portrait_id: str | None,
    validation_warnings: list[str],
    meta: dict,
) -> str:
    parts = ["# 竞品人群逆向分析报告", ""]
    src = meta.get("source") or {}
    info = [
        f"- 视频：{meta.get('video_path')}（{meta.get('file_size_mb')}MB"
        f"，{meta.get('video_duration_sec') or '?'}s）",
        f"- 模型：{meta.get('model_used')}，耗时 {meta.get('elapsed_sec')}s",
    ]
    if src.get("desc") or src.get("author_nickname"):
        info.append(f"- 来源：{src.get('author_nickname') or ''} · {src.get('desc') or ''}")
    parts += info + ["", "## 一、视频人群信号（8 项）", "", signals_md, ""]
    parts += ["## 二、竞品人群假设（🧠 视频推演）", "", persona_md.strip(), ""]
    parts += ["## 三、漏斗位判断", "", (funnel_guess or "（段一未给出）").strip(), ""]
    if comparison_md:
        parts += [f"## 四、自家画像对照（portrait_id={compared_portrait_id}）", "",
                  comparison_md.strip(), ""]
    else:
        parts += ["## 四、自家画像对照", "", "（本次未跑——原因见下方警告）", ""]
    if confidence_notes:
        parts += ["## 可信度备注（LLM 自报）", ""]
        parts += [f"- {n}" for n in confidence_notes] + [""]
    if validation_warnings:
        parts += ["## ⚠ 警告", ""]
        parts += [f"- {w}" for w in validation_warnings] + [""]
    parts += ["---", f"> {_FOOTER}"]
    return "\n".join(parts)


# ============ tool ============

@tool_with_audit(mcp, require_approval=False)
async def reverse_audience_analysis(
    video_path: str | None = None,
    share_url: str | None = None,
    portrait_id: str | None = None,
    sku_id: str | None = None,
    competitor_hint: str | None = None,
    extra_context: str | None = None,
    model: str | None = None,
) -> dict:
    """竞品人群逆向分析：看一条竞品视频在打什么人，可选对照自家画像找空白区。

    段一（必跑）：视频 → 8 项人群信号（演员人设/场景档次→消费力/话术诉求/BGM/
    字幕/钩子/价格信号/CTA→漏斗位）→ 竞品人群假设（核心服务人群假设 1-3 个 +
    核心沟通主张 + 它没在打谁，每句标 🧠/⚠️，数字必带 ⚠️）。
    段二（条件跑）：有自家画像（portrait_id 直给，或 sku_id 拉最新 adopted/draft）
    时出对照：对照表（竞品🧠 vs 自家[KB:]）/ 人群空白四区映射（红海/抢夺/蓝海/
    必争→该不该跟）/ 可借鉴打法 3-5 条。段二失败 fail-open 只返段一 + warning。

    跟 reverse_storyboard_video 的分工：那边反推「怎么拍」（故事板 prompt 包），
    这边反推「打什么人」（人群假设 + 画像对照）。v1 不落库，只出 md 报告。

    Args:
        video_path: 视频文件路径（KE 容器内可访问；host Desktop 已 mount /host/Desktop）；
            跟 share_url 二选一
        share_url: 抖音分享链接（v.douyin.com 短链 / iesdouyin.com 长链）；自动解析下载
            （带缓存，同视频不重复下载）；跟 video_path 二选一
        portrait_id: 自家画像 id（step 3.5 落库的 pipeline.audience_portraits）；给了走段二对照
        sku_id: 不给 portrait_id 时按 sku 拉该 SKU 最新 adopted 画像（无 adopted 则最新 draft）
        competitor_hint: 竞品提示（"这是海天的短视频"/"千禾零添加系列"），帮 LLM 定锚
        extra_context: 老板临时方向（"重点看它的价格信号"）
        model: 显式覆盖 tool_models.yaml 配的视频理解模型；None=用 yaml

    Returns:
        {ok, result: {competitor_persona_md, comparison_md|None, signals, funnel_guess,
                      confidence_notes, markdown, compared_portrait_id, sku_id,
                      validation_warnings, meta},
         trace, next_step_hint}
    """
    source_url: str | None = None
    resolver_meta: dict | None = None

    # ── 1a. share_url 模式：先解析下载（同 reverse_storyboard_video） ──
    if share_url and not video_path:
        from app.services.douyin_resolver import resolve_douyin_share_url

        resolved = await resolve_douyin_share_url(share_url.strip())
        if not resolved.get("ok"):
            return {
                "ok": False,
                "error": f"douyin_resolve_failed:{resolved.get('error')}",
                "hint": resolved.get("hint", "抖音链接解析失败"),
                "share_url": share_url,
            }
        video_path = resolved["video_path"]
        source_url = resolved.get("source_url")
        resolver_meta = {
            "aweme_id": resolved.get("aweme_id"),
            "watermark": resolved.get("watermark"),
            "from_cache": resolved.get("from_cache"),
            "desc": resolved.get("desc"),
            "author_nickname": resolved.get("author_nickname"),
        }
        logger.info(
            "[reverse-aud] share_url=%s → video_path=%s (cache=%s)",
            share_url, video_path, resolver_meta["from_cache"],
        )

    # ── 1b. 校验文件 ──
    if not video_path or not isinstance(video_path, str):
        return {
            "ok": False,
            "error": "missing_input",
            "hint": "video_path 或 share_url 至少传一个（抖音链接 share_url='https://v.douyin.com/xxx/'）",
        }
    if not os.path.exists(video_path):
        return {
            "ok": False,
            "error": "file_not_found",
            "hint": (
                f"video_path={video_path} 不存在（容器内视角）。"
                f"host 路径需在 docker-compose.yml 给 KE service 加 volume bind-mount；"
                f"C:/Users/Administrator/Desktop/* 已 mount 到 /host/Desktop/*"
            ),
        }
    if os.path.isdir(video_path):
        return {"ok": False, "error": "is_directory", "hint": f"{video_path} 是目录，要文件"}

    file_size_mb = os.path.getsize(video_path) / 1024 / 1024
    logger.info(f"[reverse-aud] video_path={video_path} size={file_size_mb:.1f}MB")

    # ── 2. 模型配置 + prompt ──
    cfg = get_model_for_tool("reverse_audience_analysis")
    used_model = (model or cfg.get("model") or "gemini-2.5-flash").strip()
    temperature = float(cfg.get("temperature", 0.3))
    max_tokens = int(cfg.get("max_tokens", 16000))

    try:
        system_prompt = prompts.load(cfg.get("prompts", {}).get("system", "reverse_audience.system"))
        user_prompt = prompts.render(
            cfg.get("prompts", {}).get("user", "reverse_audience.user"),
            competitor_hint_block=(competitor_hint or "").strip() or "（无，LLM 按视频内容自判竞品定位）",
            extra_context_block=(extra_context or "").strip() or "（无）",
        )
    except (FileNotFoundError, KeyError) as exc:
        return {"ok": False, "error": "prompt_missing", "hint": str(exc)}

    final_prompt_preview = (system_prompt + "\n\n---\n\n" + user_prompt)[:8000]

    # ── 3. 段一：Gemini Files API 视频理解（错误分类同 reverse_storyboard_video） ──
    try:
        from app.services.gemini_video_client import GeminiVideoClient
    except ImportError as exc:
        return {"ok": False, "error": "gemini_sdk_missing",
                "hint": f"google-generativeai 未装（KE rebuild?）: {exc}"}
    try:
        client = GeminiVideoClient(model=used_model)
    except RuntimeError as exc:
        return {"ok": False, "error": "gemini_not_configured", "hint": str(exc)}

    start = time.time()
    try:
        llm_result, usage = await client.analyze_video(
            video_path=video_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except (FileNotFoundError, TimeoutError) as exc:
        return {"ok": False, "error": "upload_or_timeout", "hint": str(exc)}
    except Exception as exc:
        logger.exception("reverse_audience_analysis LLM call failed")
        msg = str(exc).lower()
        if "vision" in msg or "video" in msg or "modality" in msg or "400" in msg:
            return {
                "ok": False,
                "error": "model_no_vision",
                "hint": (
                    f"模型 {used_model} 可能不支持视频输入。建议换 "
                    f"gemini-2.5-flash / gemini-3-flash-preview / gemini-3.1-pro-preview。原始错误: {exc}"
                ),
            }
        return {"ok": False, "error": "llm_call_failed", "hint": f"{type(exc).__name__}: {exc}"}
    elapsed = time.time() - start

    persona_md = (llm_result.get("persona_md") or "").strip()
    signals = llm_result.get("signals") or {}
    funnel_guess = (llm_result.get("funnel_guess") or "").strip()
    confidence_notes = llm_result.get("confidence_notes") or []
    llm_meta = llm_result.get("meta") or {}
    if not persona_md:
        return {
            "ok": False,
            "error": "schema_validation_failed",
            "hint": "LLM 没返回 persona_md（竞品人群假设主体），查 raw_result 看具体内容后重跑",
            "raw_result": llm_result,
            "trace": build_trace(
                provider="gemini", model=used_model, prompt=final_prompt_preview,
                params={"temperature": temperature, "max_tokens": max_tokens},
                cost_estimate=f"input={usage.get('input_tokens', 0)} output={usage.get('output_tokens', 0)} tokens",
            ),
        }

    # ── 4. 确定性校验 ──
    validation_warnings = _validate_reverse_persona(persona_md)
    signals_md = _format_signals_md(signals if isinstance(signals, dict) else {})

    # ── 5. 段二：自家画像对照（fail-open） ──
    comparison_md: str | None = None
    compare_prompt: str | None = None
    portrait, route_warnings = await _resolve_portrait(portrait_id, sku_id)
    validation_warnings += route_warnings
    compared_portrait_id = (portrait or {}).get("id")
    out_sku_id = sku_id or (portrait or {}).get("sku_id")
    if portrait:
        try:
            comparison_md, compare_prompt = await _compare_with_portrait(
                cfg,
                persona_md=persona_md,
                signals_md=signals_md,
                funnel_guess=funnel_guess,
                portrait_md=portrait.get("portrait_md") or "",
                competitor_hint=competitor_hint,
                extra_context=extra_context,
            )
            if _FOOTER[:14] not in comparison_md:  # "竞品人群假设全部为视频推演"
                validation_warnings.append(
                    "⚠ 对照段缺固定结尾「竞品人群假设全部为视频推演，真实人群以投放数据为准」——人工复核"
                )
        except Exception as exc:
            logger.exception("reverse_audience compare stage failed (fail-open)")
            validation_warnings.append(
                f"⚠ 段二对照失败（fail-open，只返段一）：{type(exc).__name__}: {exc}——"
                "可单独重跑（同参数）或先看竞品假设"
            )

    # ── 6. meta + markdown ──
    full_meta = {
        "video_path": video_path,
        "video_duration_sec": llm_meta.get("video_duration_sec"),
        "model_used": used_model,
        "file_size_mb": round(file_size_mb, 1),
        "elapsed_sec": round(elapsed, 1),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "llm_warnings": llm_meta.get("warnings") or [],
        "usage": usage,
        "compared": bool(comparison_md),
    }
    if source_url:
        full_meta["source_url"] = source_url
    if resolver_meta:
        full_meta["source"] = resolver_meta

    markdown = _render_markdown(
        signals_md=signals_md,
        persona_md=persona_md,
        funnel_guess=funnel_guess,
        confidence_notes=confidence_notes,
        comparison_md=comparison_md,
        compared_portrait_id=compared_portrait_id,
        validation_warnings=validation_warnings + [f"（LLM 自报）{w}" for w in full_meta["llm_warnings"]],
        meta=full_meta,
    )

    # ── 7. 返回 ──
    result = {
        "ok": True,
        "result": {
            "competitor_persona_md": persona_md,
            "comparison_md": comparison_md,
            "signals": signals,
            "funnel_guess": funnel_guess,
            "confidence_notes": confidence_notes,
            "markdown": markdown,
            "compared_portrait_id": compared_portrait_id,
            "sku_id": out_sku_id,
            "validation_warnings": validation_warnings,
            "meta": full_meta,
        },
        "trace": build_trace(
            provider="gemini",
            model=used_model,
            prompt=(final_prompt_preview + (
                "\n\n=== 段二对照 prompt（截断） ===\n" + compare_prompt[:4000]
                if compare_prompt else ""
            ))[:12000],
            params={
                "temperature": temperature,
                "max_tokens": max_tokens,
                "portrait_id": portrait_id,
                "sku_id": sku_id,
                "compared_portrait_id": compared_portrait_id,
                "competitor_hint": competitor_hint,
                "source_url": source_url,
            },
            cost_estimate=(
                f"段一 input={usage.get('input_tokens', 0)} output={usage.get('output_tokens', 0)} tokens "
                f"+ {file_size_mb:.1f}MB video upload"
                + ("；段二 1 quota chat call" if comparison_md else "")
            ),
        ),
    }

    if comparison_md:
        return attach_next_step(
            result,
            suggested_tool=None,
            suggested_args={},
            human_text=(
                "对照已出——「可借鉴打法」可作为 extra_context 喂 generate_creative_pack / "
                "generate_director_brief 落到自家内容；记住竞品假设全是视频推演，投放数据说了算。"
            ),
        )
    return attach_next_step(
        result,
        suggested_tool="generate_audience_portrait",
        suggested_args={"audience_record_id": "<step 3 选中的人群 record id>"},
        human_text=(
            "本次只出了竞品假设（没拿到自家画像）。要对照：先跑 step 3.5 出画像，"
            "再带 portrait_id 重跑本工具补段二。"
        ),
    )
