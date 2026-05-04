"""W2 T6/T8/T9：media tools。

- generate_brief：基于 sku metadata + 渠道特点 + KB context → Claude → markdown brief
- generate_image：多 prompt 一次出多张分镜（gpt-image-2，多类 refs）  ← T8
- generate_video：多 segment 并发跑 Seedance 各段（首尾帧 + refs）   ← T9

每个 LLM tool 返 result + trace + next_step_hint。
"""
from __future__ import annotations

import asyncio

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.services.ai_hub_client import AIHubClient


_CHANNEL_PROFILES = {
    "douyin": "抖音电商：竖版 9:16，前 3 秒强钩子，价格锚点 + 痛点切入；忌过长 brief（≤300 字）",
    "tmall": "天猫店铺：详情页长图文，强调品质 + 资质 + 用户证言；2-4 段，每段含一个购买理由",
    "jd": "京东自营：物流 + 售后承诺为主；强调正品 / 配送 / 服务",
}


def _channel_profile(channel: str) -> str:
    return _CHANNEL_PROFILES.get(channel, f"渠道 {channel}（未配 profile，按通用电商写）")


@tool_with_audit(mcp, require_approval=False)
async def generate_brief(
    sku_id: str,
    channel: str,
    extra_context: str | None = None,
) -> dict:
    """出渠道 brief（markdown）。基于 sku metadata + 渠道 profile + 可选 extra context。

    Args:
        sku_id: SKU id
        channel: 渠道（douyin / tmall / jd / ...）
        extra_context: 额外提示（如"主推健康"/"对标 X 品牌"）

    Returns:
        {ok, result: {brief_md}, trace, next_step_hint(generate_image)}
    """
    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT id, name, category, price_min, price_max, specifications "
        "FROM mvp_sku WHERE id = $1",
        sku_id,
    )
    if not sku:
        return {
            "ok": False,
            "error": f"sku_id 未找到: {sku_id}",
            "hint": "调 list_skus 看现有 sku_id",
        }

    # 售价区间显示：min == max 显示单值，否则区间
    if sku["price_min"] is not None and sku["price_max"] is not None:
        if sku["price_min"] == sku["price_max"]:
            price_str = str(sku["price_min"])
        else:
            price_str = f"{sku['price_min']} - {sku['price_max']}"
    else:
        price_str = "（未设置）"

    sku_md = (
        f"- 名称：{sku['name']}\n"
        f"- 品类：{sku['category'] or '（未分类）'}\n"
        f"- 售价：{price_str}\n"
        f"- 规格：{sku['specifications'] or '（无）'}\n"
    )

    sys_msg = (
        "你是调味品工厂老板的渠道运营。给一只 SKU 写一份渠道 brief。"
        "brief 用 markdown 格式，含：核心卖点（3 条）/ 目标人群 / "
        "主场景 / 文案钩子（1 句）/ 拍摄分镜建议（3 个分镜的 1 句话描述）。"
        "说人话，不要废话，不要“亲”“家人们”等套话。"
    )
    user_msg = (
        f"## SKU\n{sku_md}\n"
        f"## 渠道\n{_channel_profile(channel)}\n"
    )
    if extra_context:
        user_msg += f"\n## 额外要求\n{extra_context}\n"

    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model_for_tool("generate_brief")
    client = AIHubClient()
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        temperature=model_cfg.get("temperature", 0.5),
        max_tokens=1200,
        enforce_human_voice=True,
    )
    brief_md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()

    # 从 brief 文本里抠 3 个分镜建议作为 generate_image 的初始 prompts
    # 简单粗暴：按行扫"分镜"或"shot"或"场景 N"；找不到就给 placeholder
    suggested_prompts: list[str] = []
    for line in brief_md.split("\n"):
        s = line.strip()
        if not s:
            continue
        if any(k in s for k in ("分镜", "shot", "场景")) and len(s) > 6:
            suggested_prompts.append(s.lstrip("-*0123456789. ").strip())
            if len(suggested_prompts) >= 3:
                break
    if len(suggested_prompts) < 3:
        suggested_prompts = [
            f"{sku['name']} 主图：产品居中，{channel} 风格",
            f"{sku['name']} 使用场景：日常厨房，自然光",
            f"{sku['name']} 细节特写：质感 + 包装",
        ]

    result = {
        "ok": True,
        "result": {"brief_md": brief_md},
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.5),
                "max_tokens": 1200,
            },
            cost_estimate="1 quota call (~1k tokens)",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_image",
        suggested_args={
            "prompts": suggested_prompts,
            "face_refs": [],
            "product_refs": [],   # 老板补 sku 主图 url
            "aspect_ratio": "9:16" if channel == "douyin" else "1:1",
        },
        human_text=(
            "出 3 张分镜图（gpt-image-2，~¥1.5 / 3 张）；"
            "如要保产品一致，product_refs 填 sku 主图 url"
        ),
    )


@tool_with_audit(mcp, require_approval=False)
async def generate_image(
    prompts: list[str],
    face_refs: list[str] | None = None,
    product_refs: list[str] | None = None,
    style_refs: list[str] | None = None,
    aspect_ratio: str = "9:16",
    n_per_prompt: int = 1,
) -> dict:
    """多 prompt 并发出多张图（gpt-image-2）。

    Args:
        prompts: prompt 列表（典型 3 张分镜）
        face_refs / product_refs / style_refs: 三类参考图 url 列表
        aspect_ratio: 画幅（默认 9:16 抖音竖版）
        n_per_prompt: 每个 prompt 出几张（默认 1）

    Returns:
        {ok, result: {images: [{prompt, url} | {prompt, error}, ...]},
         trace, next_step_hint(generate_video)}
    """
    model_cfg = get_model_for_tool("generate_image")
    client = AIHubClient()

    async def _one(prompt: str):
        try:
            resp = await client.generate_image_v2(
                prompt=prompt,
                face_refs=face_refs,
                product_refs=product_refs,
                style_refs=style_refs,
                aspect=aspect_ratio,
                n=n_per_prompt,
                model=model_cfg.get("model", "gpt-image-2"),
                provider=model_cfg.get("provider", "openai"),
            )
            urls = []
            for img in resp.get("images") or resp.get("data") or []:
                urls.append(img.get("url") or img.get("image_url") or "")
            return {"prompt": prompt, "urls": [u for u in urls if u]}
        except Exception as exc:
            return {"prompt": prompt, "error": f"{type(exc).__name__}: {exc}"}

    results = await asyncio.gather(*(_one(p) for p in prompts))

    # flatten 用 url（前端展示）；保留 prompt 关联
    images = []
    for r in results:
        if r.get("error"):
            images.append({"prompt": r["prompt"], "error": r["error"]})
        else:
            for u in r["urls"]:
                images.append({"prompt": r["prompt"], "url": u})
            if not r["urls"]:
                images.append({"prompt": r["prompt"], "error": "hub 无返回 url"})

    cost_per = "¥0.5" if model_cfg.get("provider") == "openai" else "未知"
    cost_estimate = f"~{len(prompts) * n_per_prompt} × {cost_per}"

    result = {
        "ok": True,
        "result": {"images": images, "count": len(images)},
        "trace": build_trace(
            provider=model_cfg.get("provider", "openai"),
            model=model_cfg.get("model", "gpt-image-2"),
            prompt="\n---\n".join(prompts),
            params={
                "aspect_ratio": aspect_ratio,
                "n_per_prompt": n_per_prompt,
                "face_refs": face_refs or [],
                "product_refs": product_refs or [],
                "style_refs": style_refs or [],
            },
            cost_estimate=cost_estimate,
        ),
    }

    # next_step_hint：用刚出的图作为下一段视频的 first_frame
    valid_urls = [i["url"] for i in images if "url" in i]
    segments_hint = []
    for i, url in enumerate(valid_urls[:3]):
        nxt = valid_urls[i + 1] if i + 1 < len(valid_urls[:3]) else None
        segments_hint.append({
            "prompt": f"段 {i+1}：从这张图运镜 8 秒",
            "first_frame": url,
            "last_frame": nxt,
            "duration_s": 8,
        })

    return attach_next_step(
        result,
        suggested_tool="generate_video",
        suggested_args={
            "segments": segments_hint,
            "face_refs": face_refs or [],
            "product_refs": product_refs or [],
            "aspect_ratio": aspect_ratio,
        },
        human_text=(
            f"用这 {len(valid_urls)} 张图做底跑分镜视频（Seedance 2.0，"
            f"~¥15/段 × {len(segments_hint)} 段）"
        ),
    )


@tool_with_audit(mcp, require_approval=False)
async def generate_video(
    segments: list[dict],
    face_refs: list[str] | None = None,
    product_refs: list[str] | None = None,
    aspect_ratio: str = "9:16",
) -> dict:
    """多段分镜视频，并发跑 Seedance；不自动拼接（老板下载多段交剪辑）。

    Args:
        segments: [{prompt, first_frame?, last_frame?, duration_s?}, ...]
        face_refs / product_refs: 全段共用的人脸 / 产品参考
        aspect_ratio: 画幅

    Returns:
        {ok, result: {segments: [{prompt, video_url, duration} | {prompt, error}, ...]},
         trace, next_step_hint(None — 链路终点)}
    """
    model_cfg = get_model_for_tool("generate_video")
    provider = model_cfg.get("provider", "seedance")
    model = model_cfg.get("model", "seedance-2-0")
    client = AIHubClient()

    async def _one(seg: dict):
        try:
            start_resp = await client.generate_video_v2(
                prompt=seg["prompt"],
                first_frame=seg.get("first_frame"),
                last_frame=seg.get("last_frame"),
                duration_sec=int(seg.get("duration_s", 8)),
                face_refs=face_refs,
                product_refs=product_refs,
                aspect=aspect_ratio,
                model=model,
                provider=provider,
            )
            task_id = (
                start_resp.get("task_id")
                or (start_resp.get("data") or {}).get("task_id")
            )
            if not task_id:
                # 同步返结果（少见）
                url = start_resp.get("video_url") or (start_resp.get("data") or {}).get("video_url")
                return {"prompt": seg["prompt"], "video_url": url,
                        "duration": seg.get("duration_s", 8)}
            done = await client.wait_for_video(task_id, max_seconds=600, poll=5.0)
            data = done.get("data") or done
            url = data.get("video_url") or data.get("url")
            if data.get("status") in ("failed", "error"):
                return {"prompt": seg["prompt"],
                        "error": f"seedance {data.get('status')}: "
                                  f"{data.get('error') or data.get('message') or ''}"}
            return {"prompt": seg["prompt"], "video_url": url,
                    "duration": seg.get("duration_s", 8), "task_id": task_id}
        except Exception as exc:
            return {"prompt": seg["prompt"], "error": f"{type(exc).__name__}: {exc}"}

    out = await asyncio.gather(*(_one(s) for s in segments))

    cost_per = "¥15" if provider == "seedance" else "未知"
    cost_estimate = f"~{len(segments)} × {cost_per}"

    result = {
        "ok": True,
        "result": {"segments": out, "count": len(out)},
        "trace": build_trace(
            provider=provider,
            model=model,
            prompt="\n---\n".join(s["prompt"] for s in segments),
            params={
                "aspect_ratio": aspect_ratio,
                "segment_count": len(segments),
                "face_refs": face_refs or [],
                "product_refs": product_refs or [],
                "first_last_frames": [
                    {"first": s.get("first_frame"), "last": s.get("last_frame")}
                    for s in segments
                ],
            },
            cost_estimate=cost_estimate,
        ),
    }
    return attach_next_step(
        result,
        suggested_tool=None,
        suggested_args={},
        human_text="全链路完成。下载各段视频自己交剪辑（不自动拼接）。",
    )
