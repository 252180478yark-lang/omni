"""W2 T6/T8/T9 + W4-B 切片 14 系列：media tools。

- generate_brief：基于 sku metadata + 渠道特点 + KB context → LLM → markdown brief
- generate_image：多 prompt 一次出多张分镜（gpt-image-2，多类 refs）  ← T8
- generate_video：多 segment 并发跑 Seedance 各段（首尾帧 + refs）   ← T9
- generate_selling_points_matrix：sku-pipeline step 2 卖点矩阵       ← 切片 14.1
- generate_audience_match：sku-pipeline step 3 人群匹配 + 多 query   ← 切片 14.2

每个 LLM tool 返 result + trace + next_step_hint。
"""
from __future__ import annotations

import asyncio
import re

from app.database import get_pool
from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.services import rag_chain
from app.services.ai_hub_client import AIHubClient


def _channel_profile(channel: str) -> str:
    """从 config/prompts/channel_profiles/<channel>.md 加载渠道画像。

    未配 profile 文件时返回 fallback 文案（不报错，让 brief 仍能出）。
    """
    try:
        return prompts.load(f"channel_profiles/{channel}").strip()
    except FileNotFoundError:
        return f"渠道 {channel}（未配 profile，按通用电商写）"


@tool_with_audit(mcp, require_approval=False)
async def generate_brief(
    sku_id: str,
    channel: str,
    extra_context: str | None = None,
    kb_context: str | None = None,
) -> dict:
    """出渠道 brief（markdown）。基于 sku metadata + 渠道 profile + 可选 KB 上下文 + 可选 extra_context。

    Args:
        sku_id: SKU id
        channel: 渠道（douyin / tmall / jd / ...）
        extra_context: 额外提示（如"主推健康"/"对标 X 品牌"）
        kb_context: 已检索好的 KB 上下文（建议由 gather_brief_context tool 出）

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

    sys_msg = prompts.render("generate_brief.system")
    user_msg = prompts.render(
        "generate_brief.user",
        sku_md=sku_md,
        channel_profile=_channel_profile(channel),
        kb_context=kb_context.strip() if kb_context else "（未提供 KB 上下文）",
        extra_context=extra_context.strip() if extra_context else "（无）",
    )
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


# ============================================================
# W4-B 切片 14：sku-pipeline step 2 — 5 维卖点 + 3 心智矩阵
# ============================================================

@tool_with_audit(mcp, require_approval=False)
async def generate_selling_points_matrix(
    sku_id: str,
    user_initial_points: str = "",
    user_reviews: str = "",
    kb_context: str | None = None,
    extra_context: str | None = None,
) -> dict:
    """生成 SKU 三层卖点 + 5 心智矩阵（sku-pipeline step 2）。

    使用调味品行业专家 prompt（5 部分输出：产品档案速写/三层卖点地图/五心智维度
    /结构化标签汇总/信息补全建议）。每个卖点含 5 关键词 + 强度评分 + 匹配场景 +
    匹配理由 + 30 字提炼。USP 走排他性检验。

    Args:
        sku_id: SKU id
        user_initial_points: 用户/运营观察到的显性卖点清单
        user_reviews: 用户评价（好评/差评关键词 / 客服反馈 / 私域反馈）
        kb_context: KB 上下文（竞品/品牌故事/工艺细节等）
        extra_context: 额外要求

    Returns:
        {ok, result: {matrix_md}, trace, next_step_hint(audience_match)}
    """
    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT id, name, category, price_min, price_max, specifications, "
        "owner_selling_points, owner_notes, platform_status, growth_class "
        "FROM mvp_sku WHERE id = $1",
        sku_id,
    )
    if not sku:
        return {
            "ok": False,
            "error": f"sku_id 未找到: {sku_id}",
            "hint": "调 list_skus 看现有 sku_id",
        }

    # 售价
    if sku["price_min"] is not None and sku["price_max"] is not None:
        if sku["price_min"] == sku["price_max"]:
            price_str = str(sku["price_min"])
        else:
            price_str = f"{sku['price_min']} - {sku['price_max']}"
    else:
        price_str = "（未设置）"

    # owner_selling_points 是 JSONB（list[{text:...}]）→ 渲染成 bullet
    osp_raw = sku["owner_selling_points"]
    osp_lines = []
    if osp_raw:
        try:
            import json as _json
            items = osp_raw if isinstance(osp_raw, list) else _json.loads(osp_raw)
            for it in items:
                if isinstance(it, dict) and it.get("text"):
                    osp_lines.append(f"  - {it['text']}")
                elif isinstance(it, str):
                    osp_lines.append(f"  - {it}")
        except Exception:
            osp_lines = [f"  - {osp_raw}"]

    # 套装规格表达更清晰：避免 LLM 把 "500ml*2 + 200ml*2" 误读成"单瓶 1.4L"
    spec_raw = sku["specifications"]
    spec_explanation = ""
    if spec_raw:
        # 启发式：规格里含 "+" 或 "*N + ..." 形式 → 是套装组合
        if "+" in spec_raw or " + " in spec_raw:
            spec_explanation = f"\n- 规格说明：**这是套装组合**（不是单瓶），上述 `{spec_raw}` 表示装在一起的多瓶配置。算单瓶价时不要把售价直接除以总容量"
        elif "*" in spec_raw:
            spec_explanation = f"\n- 规格说明：`{spec_raw}` 含 `*` 通常表示一箱多瓶或套装。算单瓶价请按瓶数拆分"

    sku_md = (
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '（未分类，调味品/酱油醋类）'}\n"
        f"- 规格：{spec_raw or '（信息不足）'}{spec_explanation}\n"
        f"- 老板手填备注（产品参数 / 工艺 / 认证）：{sku['owner_notes'] or '（无）'}\n"
        f"- 抖店平台状态：{sku['platform_status'] or '（unknown）'}\n"
        f"- 抖店诊断：{sku['growth_class'] or '（无）'}\n"
        f"- 老板手填卖点（owner_selling_points）：\n"
        + ("\n".join(osp_lines) if osp_lines else "  - （无）")
    )

    # SKU 与价格带（当前只有这一款 SKU 的信息，跨品类对比由 user 补充）
    sku_price_band = (
        f"- 当前主推 SKU：{sku['id']} / 售价 ¥{price_str} / 规格 {spec_raw or '（无）'}\n"
        f"- 其他在售 SKU 与价格分布：（信息不足，需用户补充其他 SKU 的价格带数据）\n"
        f"- 渠道售价差异：（信息不足）"
    )

    # system 用 load 不 format（system.md 含字面 {需求表达} 等不希望被替换的花括号）
    sys_msg = prompts.load("selling_points_matrix.system")
    user_msg = prompts.render(
        "selling_points_matrix.user",
        sku_md=sku_md,
        sku_price_band=sku_price_band,
        user_reviews=user_reviews.strip() if user_reviews else "（信息不足，需补充用户评价/客服反馈/差评关键词）",
        user_initial_points=user_initial_points.strip() if user_initial_points else "（用户/运营未输入显性卖点观察清单）",
        kb_context=kb_context.strip() if kb_context else "（未提供 KB 上下文：建议先 search_kb 拿同品类爆款 / 品牌资产 / 竞品对比）",
        extra_context=extra_context.strip() if extra_context else "（无）",
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model_for_tool("generate_selling_points_matrix")
    # pro 模型推理慢（6000 max_tokens 可 ~120s），给充足 timeout
    client = AIHubClient(timeout=240.0)
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        temperature=model_cfg.get("temperature", 0.5),
        max_tokens=6000,  # 5 部分输出（产品档案 + 三层卖点地图 + 5 心智 + 标签 + 信息补全）较长
        enforce_human_voice=True,
    )
    matrix_md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()

    result = {
        "ok": True,
        "result": {
            "matrix_md": matrix_md,
            "sku_id": sku_id,
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.5),
                "max_tokens": 6000,
            },
            cost_estimate="1 quota call (~3-5k tokens)",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_audience_match",
        suggested_args={"sku_id": sku_id, "matrix_md": matrix_md},
        human_text="step 3 generate_audience_match（人群匹配 + 多 query 召回）",
    )


# ============================================================
# W4-B 切片 14.2：sku-pipeline step 3 — 人群匹配（多 query 召回）
# ============================================================

# 人群分析报告 KB（kb_role=private_doc，46 docs / 3291 chunks）
AUDIENCE_KB_ID = "b7a08c06-50a4-491e-9a1d-a6568dea5695"

# 品类中性锚（**不预设人群圈层**，只锚 SKU 品类）
# 多 query 用意 = 用多角度查同一件事避开「单 query 偏移」（KB 管线发现 #1），
# 不是「用我预设的圈层覆盖一遍」。所有人群圈层都靠 matrix 派生 query 自然召回。
# 反向推理硬约束（feedback_sku_pipeline_design memory 第 7 条）：
#   严格按"卖点+场景+心智"反向匹配人群，不预先匹配思路
_CATEGORY_ANCHORS: tuple[str, ...] = (
    # 用 {category} 占位，运行时替换为 SKU 实际品类（"调味品" / "酱油" / "醋" 等）
    "{category} 消费人群",
    "{category} 内容偏好",
    "{category} 决策路径",
)


def _extract_seed_phrases(matrix_md: str) -> list[str]:
    """从 matrix_md 解析多角度 query seeds。

    启发式（不依赖严格结构，对 prompt 输出格式变动鲁棒）：
    - 抓 ###/#### 标题（去掉编号 / # / 装饰符）
    - 抓 **加粗短语**（5-25 字）
    - 抓「」/【】里的短语
    - 去重、去停用词、限长

    返回 ≤ 12 个种子短语。
    """
    seeds: list[str] = []
    seen: set[str] = set()

    # 1) 标题（### / ####）
    for m in re.finditer(r"^#{2,4}\s+(.+?)$", matrix_md, flags=re.M):
        raw = m.group(1).strip()
        # 去编号前缀（"三、" / "1.1.2" / "2.6 节" 等）
        clean = re.sub(r"^[一二三四五六七八九十0-9.\s、节·】\[\]【\.]+", "", raw)
        clean = clean.strip("- ").strip()
        if 4 <= len(clean) <= 30 and clean not in seen:
            seen.add(clean)
            seeds.append(clean)

    # 2) **加粗短语**
    for m in re.finditer(r"\*\*([^\*\n]{4,30})\*\*", matrix_md):
        clean = m.group(1).strip()
        # 跳过明显不是名词短语的（含冒号 / 太多空格）
        if (
            ":" not in clean
            and "：" not in clean
            and clean not in seen
        ):
            seen.add(clean)
            seeds.append(clean)

    # 3) 「」/【】里的短语
    for m in re.finditer(r"[「【]([^」】\n]{3,20})[」】]", matrix_md):
        clean = m.group(1).strip()
        if clean not in seen:
            seen.add(clean)
            seeds.append(clean)

    # 过滤掉太通用的词 + matrix prompt 的结构性章节标题（避免被当人群 query）
    skip_words = {
        "卖点", "场景", "心智", "标签", "USP", "信息", "产品", "品牌",
        "强度评分", "匹配场景", "匹配理由", "证据", "合规风险",
        "显性卖点", "隐性卖点", "独特卖点", "结构化标签",
    }
    skip_phrases = {
        # selling_points_matrix.system.md 的结构性章节标题，不是真卖点/场景/心智名
        "产品档案", "产品档案速写",
        "三层卖点地图", "层卖点地图",
        "五心智维度", "心智维度",
        "使用场景", "场景心智", "内容心智", "产品心智", "品牌心智",
        "结构化标签汇总", "信息补全", "信息补全建议",
        "合规与红线", "输出前自检", "品类常识校准",
        "复合心智候选", "排他性检验",
    }
    seeds = [s for s in seeds if s not in skip_words and s not in skip_phrases]

    # 限 12 个（再多 query 量爆炸）
    return seeds[:12]


async def _list_audience_kb_docs(kb_id: str) -> list[str]:
    """拿 audience KB 全部 doc title（去重）。让每个 doc 都有机会被召回。

    用 doc title 做 query 不是"预设人群圈层"——doc title 反映 KB 实际存的圈层结构，
    给所有 doc 公平召回机会，匹配什么仍由 LLM 看 chunk 实打实判断。
    """
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT DISTINCT title FROM knowledge.knowledge_chunks "
        "WHERE kb_id = $1 AND title IS NOT NULL AND title != ''",
        kb_id,
    )
    return [r["title"] for r in rows]


def _doc_title_to_query_seed(title: str) -> str:
    """doc title → 适合做 query 的关键词。

    剥掉年份/版本号/装饰，保留圈层关键词。
    """
    s = title
    # 剥年份 / 版本
    s = re.sub(r"^\d{4}", "", s).strip()
    s = re.sub(r"\s*\(\d+\)\s*$", "", s).strip()
    s = re.sub(r"\s*-?\s*final\s*$", "", s, flags=re.I).strip()
    # 剥书名号 / 引号
    s = s.strip("《》「」【】\"' ")
    # 取括号外部分（"暮年当燃（银发圈层）" → "暮年当燃 银发圈层"）
    s = re.sub(r"[（(]", " ", s)
    s = re.sub(r"[）)]", "", s)
    return s.strip()


async def _build_audience_queries(
    matrix_md: str,
    sku_name: str,
    sku_category: str | None = None,
    kb_id: str | None = None,
) -> list[str]:
    """构造 query list — 品类锚 + matrix 派生 + 全 KB doc 扩散（不预设人群圈层）。

    规则：
    - 品类锚（3）：用 SKU 实际品类填 _CATEGORY_ANCHORS
    - SKU 名锚（1）：剥容量/编号后做独立 query
    - matrix 派生：从 matrix_md 提取卖点/场景/心智名
    - **全 KB doc 扩散**：拿 KB 所有 doc title 做 query，让每个 doc 都有公平召回机会。
      doc title 是 KB 实际存的圈层结构（不是我猜的人群圈层），给每个 doc 公平
      召回机会才能让 LLM 看到 46 个 doc 全貌后自由判断匹配。

    匹配什么人群圈层完全由 LLM 看 chunk 实打实决定，tool 不预判结果。
    """
    category = (sku_category or "").strip() or "调味品"
    out: list[str] = [a.format(category=category) for a in _CATEGORY_ANCHORS]

    # SKU 名锚（剥容量/规格/括号里的修饰）
    sku_short = re.sub(r"\d+ml|\d+g|\*\d+|\(.*?\)|（.*?）", "", sku_name).strip()
    if sku_short:
        out.append(f"{sku_short[:20]} 消费人群")

    # matrix 派生（卖点 / 场景 / 心智名 → query）
    for seed in _extract_seed_phrases(matrix_md):
        out.append(f"{category} {seed[:18]} 人群")

    # 全 KB doc 扩散（每个 doc 一个 query，让所有圈层公平进候选池）
    if kb_id:
        try:
            doc_titles = await _list_audience_kb_docs(kb_id)
            for title in doc_titles:
                seed = _doc_title_to_query_seed(title)
                if seed:
                    out.append(f"{category} {seed[:25]} 人群")
        except Exception:
            pass  # 失败回退到品类锚 + matrix 派生

    # 去重保留顺序
    seen: set[str] = set()
    dedup: list[str] = []
    for q in out:
        if q not in seen:
            seen.add(q)
            dedup.append(q)
    return dedup


async def _multi_query_recall(
    queries: list[str],
    kb_id: str,
    top_k_per_query: int = 5,
    max_chunks: int = 40,
) -> list[dict]:
    """对多个 query 跑 KB 召回，按 chunk id 去重，返回合并 list。

    Returns:
        list[{source, kb_id, id, score, content, title, query_origin}]
        其中 query_origin 标记是哪个 query 召回到的（首次命中的 query）
    """
    name_map: dict[str, str] = {}
    try:
        from app.services import ingestion as _ingestion
        kbs = await _ingestion.list_kbs()
        name_map = {k["id"]: k["name"] for k in kbs}
    except Exception:
        pass

    # 并发跑（asyncio.gather；失败不挂全跑）
    async def _one_query(q: str) -> tuple[str, list[dict]]:
        try:
            hits = await rag_chain.retrieve_multi_kb(
                q,
                [kb_id],
                top_k_per_kb=top_k_per_query,
                kb_name_map=name_map,
            )
            return q, hits
        except Exception:
            return q, []

    results = await asyncio.gather(*[_one_query(q) for q in queries])

    seen_chunk_ids: set[str] = set()
    merged: list[dict] = []
    for q, hits in results:
        for h in hits:
            cid = str(h.get("id") or "")
            if not cid or cid in seen_chunk_ids:
                continue
            seen_chunk_ids.add(cid)
            h2 = dict(h)
            h2["query_origin"] = q
            merged.append(h2)

    # 按 doc round-robin 重排（避免单 doc 占据 chunks 大头让 LLM 偏视一个 doc）：
    # 1) 按 title 分桶
    # 2) 桶内按 score 降序
    # 3) 轮询每个桶取一个，直到桶都空
    # 这样不同 doc 的 chunk 交替出现，LLM 在第 1 部分跨 doc 多样性匹配会更稳
    by_doc: dict[str, list[dict]] = {}
    for h in merged:
        title = (h.get("title") or "").strip() or "（无标题）"
        by_doc.setdefault(title, []).append(h)
    for d in by_doc:
        by_doc[d].sort(key=lambda h: float(h.get("score") or 0), reverse=True)

    diversified: list[dict] = []
    while len(diversified) < max_chunks and any(by_doc.values()):
        for d in list(by_doc.keys()):
            if by_doc[d]:
                diversified.append(by_doc[d].pop(0))
                if len(diversified) >= max_chunks:
                    break
    return diversified


def _format_kb_recall(chunks: list[dict]) -> str:
    """把多 query 召回的 chunks 渲染成 markdown，喂给 LLM。

    chunk 已被 _multi_query_recall 按 doc round-robin 重排（不再纯 score 降序）。
    顶部加 doc 来源清单让 LLM 看到"涉及哪些 doc"，提示要全部 chunks 过一遍 + 不预设映射。

    每个 chunk 一段：
    ```
    ### Chunk N — [来源: 文档名] (score: 0.78, query: "...")

    [chunk 原文]
    ```
    """
    if not chunks:
        return "（KB 召回为空：建议检查 audience KB id 是否正确，或 query seeds 是否有效）"

    # 顶部 doc 来源清单（按出现 chunk 数）
    doc_count: dict[str, int] = {}
    for h in chunks:
        t = (h.get("title") or "").strip() or "（无标题）"
        doc_count[t] = doc_count.get(t, 0) + 1
    doc_list_md = "\n".join(
        f"- **{t}**（{n} chunks）"
        for t, n in sorted(doc_count.items(), key=lambda kv: -kv[1])
    )
    header = (
        f'### 本次 KB 召回涉及 {len(doc_count)} 个不同 doc（按 chunk 数排序）：\n\n'
        f'{doc_list_md}\n\n'
        f'**全部 chunks 都过一遍**，按"假设卖点+场景+心智 vs chunk 描绘"实打实匹配；'
        f'跨 doc 是自然结果，不要预设"哪个假设该去哪个 doc 找"。\n\n'
        f'---\n\n'
    )

    parts: list[str] = []
    for i, h in enumerate(chunks, start=1):
        title = (h.get("title") or "").strip() or "（无标题）"
        score = float(h.get("score") or 0)
        q = h.get("query_origin") or ""
        content = (h.get("content") or "").strip()
        parts.append(
            f"### Chunk {i} — [来源: {title}] (score: {score:.3f}, query: \"{q}\")\n\n"
            f"{content}"
        )
    return header + "\n\n---\n\n".join(parts)


@tool_with_audit(mcp, require_approval=False)
async def generate_audience_match(
    sku_id: str,
    matrix_md: str,
    extra_context: str | None = None,
    kb_recall_override: str | None = None,
) -> dict:
    """生成 SKU 人群匹配（sku-pipeline step 3）。

    输入 step 2 的卖点矩阵 markdown，内部按多 query 策略召回人群分析报告 KB
    （绕开 KB 单 query 偏移），喂给 pro 模型，输出 4 部分人群匹配报告：

    - 第 0 部分：人群假设推断（5-10 个跨圈层假设，反向推理）
    - 第 1 部分：KB 匹配人群（KB 原文 1:1 + 匹配理由 ≥ 5 条含卖点+场景）
    - 第 3 部分：KB 召回未覆盖的假设（信息补全建议）
    - 第 4 部分：结构化标签汇总（≥ 30 条）

    严格不写：圈包标签 / 优先级 / 预算 / 投放渠道 / 脚本 / 钩子 / 拒绝候选

    Args:
        sku_id: SKU id
        matrix_md: step 2 输出的卖点矩阵 markdown（必填，没这个反向推理无依据）
        extra_context: 额外要求（如"重点挖跨圈层"/"对标 X 品牌"）
        kb_recall_override: 显式覆盖 KB 召回（老板手贴 chunks 时用）

    Returns:
        {ok, result: {audience_md, sku_id, recall_meta}, trace, next_step_hint(audience_sop_pack)}
    """
    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT id, name, category, price_min, price_max, specifications, "
        "owner_selling_points, owner_notes, platform_status, growth_class "
        "FROM mvp_sku WHERE id = $1",
        sku_id,
    )
    if not sku:
        return {
            "ok": False,
            "error": f"sku_id 未找到: {sku_id}",
            "hint": "调 list_skus 看现有 sku_id",
        }

    if not matrix_md or not matrix_md.strip():
        return {
            "ok": False,
            "error": "matrix_md 为空",
            "hint": "step 3 必须先跑 step 2（generate_selling_points_matrix）拿 matrix_md。"
                    "反向推理需要卖点+场景+心智作为推断起点",
        }

    # SKU 基本信息（精简版，audience_match 不需要 step 2 的所有套装规格细节）
    spec_raw = sku["specifications"] or ""
    sku_md = (
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '（未分类，调味品）'}\n"
        f"- 规格：{spec_raw or '（无）'}\n"
        f"- 抖店平台状态：{sku['platform_status'] or '（unknown）'}\n"
        f"- 抖店诊断：{sku['growth_class'] or '（无）'}\n"
    )

    # === 多 query 召回（kb_recall_override 显式覆盖时跳过）===
    if kb_recall_override and kb_recall_override.strip():
        kb_recall_md = kb_recall_override.strip()
        recall_meta = {
            "mode": "override",
            "queries": [],
            "chunk_count": 0,
        }
    else:
        queries = await _build_audience_queries(
            matrix_md,
            sku["name"] or "",
            sku_category=sku["category"],
            kb_id=AUDIENCE_KB_ID,
        )
        # 全 KB doc 扩散后 query 数 ~50-65，每 query top_k=3 节省 chunks 名额
        # max_chunks=80 让 LLM 看到更多 doc 代表 chunks（之前 40 太少）
        chunks = await _multi_query_recall(
            queries=queries,
            kb_id=AUDIENCE_KB_ID,
            top_k_per_query=3,
            max_chunks=80,
        )
        kb_recall_md = _format_kb_recall(chunks)
        recall_meta = {
            "mode": "multi_query",
            "queries": queries,
            "chunk_count": len(chunks),
        }

    # === LLM ===
    sys_msg = prompts.load("audience_match.system")
    user_msg = prompts.render(
        "audience_match.user",
        sku_md=sku_md,
        matrix_md=matrix_md.strip(),
        kb_recall=kb_recall_md,
        extra_context=extra_context.strip() if extra_context else "（无）",
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model_for_tool("generate_audience_match")
    # pro 推理慢 + 输出长（≥ 30 标签 + 多人群 KB 原文 + 假设推断），给 240s
    client = AIHubClient(timeout=240.0)
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3.1-pro-preview"),
        temperature=model_cfg.get("temperature", 0.3),
        max_tokens=model_cfg.get("max_tokens", 8000),
        enforce_human_voice=True,
    )
    audience_md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()

    result = {
        "ok": True,
        "result": {
            "audience_md": audience_md,
            "sku_id": sku_id,
            "recall_meta": recall_meta,
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3.1-pro-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.3),
                "max_tokens": model_cfg.get("max_tokens", 8000),
                "audience_kb_id": AUDIENCE_KB_ID,
                "queries_used": len(recall_meta["queries"]),
                "chunks_recalled": recall_meta["chunk_count"],
            },
            cost_estimate="1 quota call (~5-8k tokens) + 多 query KB 召回",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool=None,  # step 4 audience_sop_pack 切片 14.3 再加
        suggested_args={"sku_id": sku_id, "matrix_md": matrix_md, "audience_md": audience_md},
        human_text="step 4 圈包 SOP（把人群描绘翻译成抖店/巨量后台标签）—— 工具切片 14.3 加",
    )
