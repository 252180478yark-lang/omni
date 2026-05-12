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
import json
import re

from app.database import get_pool
from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.model_config import get_model_for_tool
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace
from app.services import pipeline_lineage, rag_chain
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
                quality=model_cfg.get("quality"),
                size=model_cfg.get("size"),
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
async def generate_character_sheets(
    script_id: str,
    role_ids: list[str] | None = None,
    aspect_ratio: str = "1:1",
) -> dict:
    """W4-B 切片 14.4 phase D · step 6.5：从 script.character_sheets 拉每个角色 → 自动 build 白底正面像 prompt → chatgpt-image-2 出图 → 落 pipeline.assets（asset_type='character_sheet', character_role=role_id）。

    后续 step 6 跑分镜图按 scene.characters_in_scene 自动找同 script 的对应 character_sheet url 当 face_refs，实现锁脸。

    Args:
        script_id: pipeline.scripts.id（必须有 character_sheets 字段，即 v11+ 新格式脚本）
        role_ids: 只跑某几个 role_id（如重跑 mother）；None = 全跑
        aspect_ratio: 默认 1:1（角色定妆白底像最合适）

    Returns:
        {ok, result: {script_id, kind, sku_id, roles_total, success_count, error_count,
                      results: [{role_id, name, asset_id, file_url, prompt} | {role_id, error, prompt}]},
         trace, next_step_hint(generate_storyboard_images)}
    """
    from app.services.pipeline_lineage import get_creative_pack, save_storyboard_asset

    script = await get_creative_pack(script_id)
    if not script:
        return {"ok": False, "error": "script_not_found", "script_id": script_id,
                "hint": "script_id 不存在或已 archived"}

    sheets = script.get("character_sheets") or []
    if not sheets:
        return {"ok": False, "error": "no_character_sheets", "script_id": script_id,
                "hint": "脚本 character_sheets 为空。可能是 v10 老格式（无第 3.5 部分），或 backfill 没解析到。先重跑 step 5 出 v11+ 新格式。"}

    if role_ids:
        sheets = [s for s in sheets if s.get("role_id") in role_ids]
    if not sheets:
        return {"ok": False, "error": "no_matching_roles", "role_ids": role_ids,
                "hint": f"指定 role_ids={role_ids} 在脚本里没匹配；脚本含 role_ids={[s.get('role_id') for s in (script.get('character_sheets') or [])]}"}

    # step 6.5 优先用 generate_character_sheets keyed override（老板可单独指定生脸模型）
    # 没配则回退 generate_image（跟 step 6 分镜图同款）
    # 检测方式：model 名包含 'image' / 'seedream' 才算 image-gen model；
    # 否则说明 yaml 没配 generate_character_sheets 落到 __default__（chat 模型），回退
    cs_cfg_raw = get_model_for_tool("generate_character_sheets")
    cs_model = (cs_cfg_raw.get("model") or "").lower()
    if "image" in cs_model or "seedream" in cs_model:
        model_cfg = cs_cfg_raw
    else:
        model_cfg = get_model_for_tool("generate_image")
    client = AIHubClient(timeout=180.0)

    def _build_character_prompt(sheet: dict) -> str:
        """白底正面像统一 prompt 模板（character reference sheet 风格）。"""
        age = (sheet.get("age") or "").strip()
        gender_zh = (sheet.get("gender") or "").strip()
        gender_en = "woman" if gender_zh == "女" else "man" if gender_zh == "男" else "person"
        keywords = (sheet.get("appearance_keywords") or "").strip()
        aura = (sheet.get("aura") or "").strip()
        return (
            f"A clean studio character reference portrait of a {age} {gender_en}. "
            f"{keywords}. "
            f"{aura} "
            f"Front-facing pose, neutral expression, looking slightly past the camera, "
            f"shoulders-up framing. "
            f"Pure pristine white seamless background, even softbox lighting from the front, "
            f"no harsh shadows, no environmental elements. "
            f"Photo-realistic, sharp focus on face, natural skin tones, "
            f"professional headshot quality. "
            f"This is a character reference sheet for film production — strictly clean isolated subject on white. "
            f"{aspect_ratio} aspect ratio."
        )

    async def _one(sheet: dict) -> dict:
        role_id = sheet.get("role_id")
        prompt = _build_character_prompt(sheet)
        try:
            resp = await client.generate_image_v2(
                prompt=prompt,
                aspect=aspect_ratio,
                n=1,
                model=model_cfg.get("model", "gpt-image-2"),
                provider=model_cfg.get("provider", "openai"),
                quality=model_cfg.get("quality"),
                size=model_cfg.get("size"),
            )
            urls: list[str] = []
            for img in resp.get("images") or resp.get("data") or []:
                u = img.get("url") or img.get("image_url") or img.get("b64_json", "")
                # b64_json 字段不带 data: 前缀，自己加
                if u and not u.startswith(("http", "data:")):
                    u = f"data:image/png;base64,{u}"
                if u:
                    urls.append(u)
            if not urls:
                return {"role_id": role_id, "name": sheet.get("name"),
                        "error": "no_image_returned", "prompt": prompt}
            url = urls[0]
            asset_id = await save_storyboard_asset(
                sku_id=script["sku_id"],
                asset_type="character_sheet",
                script_id=script_id,
                audience_pack_id=script.get("audience_pack_id"),
                audience_record_id=script.get("audience_record_id"),
                matrix_run_id=script.get("matrix_run_id"),
                character_role=role_id,
                file_url=url,
                prompt=prompt,
            )
            return {
                "role_id": role_id,
                "name": sheet.get("name"),
                "asset_id": asset_id,
                "file_url": url,
                "prompt": prompt,
            }
        except Exception as exc:
            return {"role_id": role_id, "name": sheet.get("name"),
                    "error": f"{type(exc).__name__}: {exc}", "prompt": prompt}

    results = await asyncio.gather(*(_one(s) for s in sheets))
    success_count = sum(1 for r in results if r.get("asset_id"))
    error_count = sum(1 for r in results if r.get("error"))

    cost_per = "¥0.5" if model_cfg.get("provider") == "openai" else "未知"
    cost_estimate = f"~{len(sheets)} × {cost_per}"

    out = {
        "ok": True,
        "result": {
            "script_id": script_id,
            "kind": script.get("kind"),
            "sku_id": script["sku_id"],
            "roles_total": len(sheets),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "openai"),
            model=model_cfg.get("model", "gpt-image-1"),
            prompt=f"script_id={script_id} → {len(sheets)} 个角色定妆并发出图",
            params={
                "role_ids": role_ids,
                "aspect_ratio": aspect_ratio,
            },
            cost_estimate=cost_estimate,
        ),
    }

    return attach_next_step(
        out,
        suggested_tool="generate_storyboard_images",
        suggested_args={"script_id": script_id},
        human_text=(
            f"已落 {success_count}/{len(sheets)} 张角色定妆照（asset_type='character_sheet'）。"
            f"接下来跑 step 6 分镜图，会自动按每段 scene.characters_in_scene 找对应 character_sheet 当 face_refs 锁脸。"
        ),
    )


@tool_with_audit(mcp, require_approval=False)
async def generate_storyboard_images(
    script_id: str,
    scene_nums: list[int] | None = None,
    face_refs: list[str] | None = None,
    product_refs: list[str] | None = None,
    style_refs: list[str] | None = None,
    aspect_ratio: str = "9:16",
    extra_prompt_suffix: str | None = None,
) -> dict:
    """W4-B 切片 14.4 phase D：从 script.scenes 拉分镜，并发调 generate_image_v2 出图，落 pipeline.assets。

    Args:
        script_id: pipeline.scripts.id（已 adopted 的最佳；scenes 字段需非空）
        scene_nums: 只跑这几段 scene_no（None = 全跑）；用于单段重跑
        face_refs / product_refs / style_refs: 三类参考图 url（同 generate_image）
        aspect_ratio: 画幅（默认 9:16）
        extra_prompt_suffix: 每段 prompt 末尾追加（如风格 hint "photo-realistic, warm tone"）

    Returns:
        {ok, result: {script_id, kind, sku_id, scenes_total, success_count, error_count,
                      results: [{scene_no, asset_id, file_url, prompt, face_refs_used, product_refs_used}
                               | {scene_no, error, prompt}]},
         trace, next_step_hint(generate_video — 把 image url 当 first_frame)}

    phase D 升级（v2）：
    - 优先用 scene.image_prompt（v11+ 新格式）；缺失才回退 scene.visual + shot
    - 自动按 scene.characters_in_scene 找同 script 的 character_sheet asset url 当 face_refs
      （老板传的 face_refs 跟自动找的合并，不重复）
    - scene.product_appearance=False 时强制不传 product_refs（哪怕老板传了，也不传）
    """
    from app.services.pipeline_lineage import (
        get_creative_pack, save_storyboard_asset, list_character_sheets_for_script,
    )

    script = await get_creative_pack(script_id)
    if not script:
        return {"ok": False, "error": "script_not_found", "script_id": script_id,
                "hint": "script_id 不存在或已 archived；先在血缘图里确认 script 有效"}

    scenes = script.get("scenes") or []
    if not scenes:
        return {"ok": False, "error": "no_scenes", "script_id": script_id,
                "hint": "脚本 scenes 为空。改 script_md 加「第 4 部分：分镜脚本」段，或调 backfill_scenes_for_existing_scripts 重解析"}

    if scene_nums:
        scenes = [s for s in scenes if s.get("scene_no") in scene_nums]
    if not scenes:
        return {"ok": False, "error": "no_matching_scenes", "scene_nums": scene_nums,
                "hint": f"指定 scene_nums={scene_nums} 在脚本里没匹配；脚本含 scene_no={[s.get('scene_no') for s in (script.get('scenes') or [])]}"}

    model_cfg = get_model_for_tool("generate_image")
    client = AIHubClient(timeout=180.0)

    # 拉同 script 的 character_sheet asset → role_id → file_url 索引
    character_sheets_assets = await list_character_sheets_for_script(script_id)
    role_to_url: dict[str, str] = {}
    for a in character_sheets_assets:
        role = a.get("character_role")
        url = a.get("file_url")
        if role and url and role not in role_to_url:
            role_to_url[role] = url

    # 拉 script.character_sheets 里的 gender 信息（给占位符翻译用 woman/man/person）
    char_sheets_meta = script.get("character_sheets") or []
    role_to_gender: dict[str, str] = {}
    for s in char_sheets_meta:
        rid = s.get("role_id")
        gender_zh = (s.get("gender") or "").strip()
        gender_en = "woman" if gender_zh == "女" else "man" if gender_zh == "男" else "person"
        if rid:
            role_to_gender[rid] = gender_en

    # 占位符翻译正则：character_sheet[role_id]（含可选空格）
    _CHAR_SHEET_REF_RE = re.compile(r"character_sheet\s*\[\s*([a-z_][a-z0-9_]*)\s*\]", re.I)

    def _replace_char_sheet_refs(prompt: str, scene: dict, manual_face_refs_count: int) -> str:
        """把 prompt 里的 character_sheet[role_id] 占位符替换为
        "the woman/man/person shown in reference image N"。

        N = manual_face_refs_count + scene.characters_in_scene 里 role_id 索引 + 1（1-based）。
        老板手填的 face_refs 占在前面（image[0]...），character_sheet 接其后。
        """
        chars = scene.get("characters_in_scene") or []
        if not chars or "character_sheet[" not in prompt.lower():
            return prompt
        # 建 role_id → reference_image_index 映射
        role_to_idx: dict[str, int] = {}
        for i, role_id in enumerate(chars):
            role_to_idx[role_id] = manual_face_refs_count + i + 1  # 1-based

        def _sub(m: re.Match) -> str:
            role_id = m.group(1)
            idx = role_to_idx.get(role_id)
            gender = role_to_gender.get(role_id, "person")
            if idx is None:
                # role 没在 characters_in_scene 里 → 不动占位符（数据不一致，保留原样让老板看到 bug）
                return m.group(0)
            return f"the {gender} shown in reference image {idx}"

        return _CHAR_SHEET_REF_RE.sub(_sub, prompt)

    def _build_prompt(scene: dict) -> str:
        """优先用 v11+ image_prompt 字段；缺失才回退 v10 老格式拼装。
        喂 hub 前做占位符翻译（character_sheet[role] → the woman/man in reference image N）。
        """
        ip = (scene.get("image_prompt") or "").strip()
        if ip:
            # 占位符翻译（OpenAI 不识别 character_sheet[xxx] 模板字符串，给它 reference image N 才能锁脸）
            manual_count = len(face_refs or [])
            ip = _replace_char_sheet_refs(ip, scene, manual_count)
            if extra_prompt_suffix:
                return f"{ip}\n\n{extra_prompt_suffix}".strip()
            return ip
        # 旧格式（v10）回退：visual + shot 拼接
        parts: list[str] = []
        if scene.get("name"):
            parts.append(f"【{scene['name']}】")
        if scene.get("visual"):
            parts.append(scene["visual"])
        if scene.get("shot"):
            parts.append(f"镜头：{scene['shot']}")
        if extra_prompt_suffix:
            parts.append(extra_prompt_suffix)
        return "\n".join(parts).strip()

    def _append_strict_product_hint(prompt: str, face_count: int, product_count: int) -> str:
        """如果该段真的传了产品参考图，prompt 末尾追加技术性指代说明，让 OpenAI 严格画产品外观。

        face_refs 在前 → product_refs 紧接着，所以产品的 reference image 索引从
        face_count+1 开始。多张产品时用 "images N to M" 区间。
        """
        if product_count <= 0:
            return prompt
        start_idx = face_count + 1
        end_idx = face_count + product_count
        ref_clause = (
            f"reference image {start_idx}" if start_idx == end_idx
            else f"reference images {start_idx} to {end_idx}"
        )
        hint = (
            f"\n\nProduct fidelity constraint: Strictly reproduce the product shown in {ref_clause} "
            f"(exact label, packaging design, color, proportions and any visible text — "
            f"do not invent, restyle or modify any visual element of the product itself; "
            f"only the surrounding scene, lighting and composition follow the main prompt)."
        )
        return prompt + hint

    def _resolve_face_refs(scene: dict) -> list[str]:
        """按 scene.characters_in_scene 找对应 character_sheet url。
        + 老板手传 face_refs 合并去重（手传优先放前面）。
        """
        urls: list[str] = list(face_refs or [])
        chars = scene.get("characters_in_scene") or []
        for role in chars:
            url = role_to_url.get(role)
            if url and url not in urls:
                urls.append(url)
        return urls

    def _resolve_product_refs(scene: dict) -> list[str] | None:
        """scene.product_appearance=False 强制不传 product_refs（哪怕老板传了）。
        =True 或缺失（v10）就用老板传的。
        """
        appears = scene.get("product_appearance")
        if appears is False:
            return None  # 强制不传
        return list(product_refs) if product_refs else None

    async def _one(scene: dict) -> dict:
        scene_no = scene.get("scene_no")
        prompt = _build_prompt(scene)
        if not prompt:
            return {"scene_no": scene_no, "error": "scene_visual_or_image_prompt_empty"}
        scene_face_refs = _resolve_face_refs(scene)
        scene_product_refs = _resolve_product_refs(scene)
        # 如果该段真的传产品参考图，追加严格参考说明（让 OpenAI 知道 image[N] 是产品要照画）
        if scene_product_refs:
            prompt = _append_strict_product_hint(
                prompt,
                face_count=len(scene_face_refs or []),
                product_count=len(scene_product_refs),
            )
        try:
            resp = await client.generate_image_v2(
                prompt=prompt,
                face_refs=scene_face_refs or None,
                product_refs=scene_product_refs,
                style_refs=style_refs,
                aspect=aspect_ratio,
                n=1,
                model=model_cfg.get("model", "gpt-image-2"),
                provider=model_cfg.get("provider", "openai"),
                quality=model_cfg.get("quality"),
                size=model_cfg.get("size"),
            )
            urls: list[str] = []
            for img in resp.get("images") or resp.get("data") or []:
                u = img.get("url") or img.get("image_url") or img.get("b64_json", "")
                if u and not u.startswith(("http", "data:")):
                    u = f"data:image/png;base64,{u}"
                if u:
                    urls.append(u)
            if not urls:
                return {"scene_no": scene_no, "error": "no_image_returned", "prompt": prompt}
            url = urls[0]
            asset_id = await save_storyboard_asset(
                sku_id=script["sku_id"],
                asset_type="image",
                script_id=script_id,
                audience_pack_id=script.get("audience_pack_id"),
                audience_record_id=script.get("audience_record_id"),
                matrix_run_id=script.get("matrix_run_id"),
                scene_no=scene_no,
                file_url=url,
                prompt=prompt,
            )
            return {
                "scene_no": scene_no,
                "asset_id": asset_id,
                "file_url": url,
                "prompt": prompt,
                "face_refs_used": scene_face_refs,
                "product_refs_used": scene_product_refs or [],
                "characters_in_scene": scene.get("characters_in_scene") or [],
                "product_appearance": scene.get("product_appearance"),
            }
        except Exception as exc:
            return {"scene_no": scene_no, "error": f"{type(exc).__name__}: {exc}", "prompt": prompt}

    results = await asyncio.gather(*(_one(s) for s in scenes))
    success_count = sum(1 for r in results if r.get("asset_id"))
    error_count = sum(1 for r in results if r.get("error"))

    cost_per = "¥0.5" if model_cfg.get("provider") == "openai" else "未知"
    cost_estimate = f"~{len(scenes)} × {cost_per}"

    out = {
        "ok": True,
        "result": {
            "script_id": script_id,
            "kind": script.get("kind"),
            "sku_id": script.get("sku_id"),
            "scenes_total": len(scenes),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "openai"),
            model=model_cfg.get("model", "gpt-image-2"),
            prompt=f"script_id={script_id} kind={script.get('kind')} → {len(scenes)} 段分镜并发出图",
            params={
                "scene_nums": scene_nums,
                "face_refs": face_refs or [],
                "product_refs": product_refs or [],
                "style_refs": style_refs or [],
                "aspect_ratio": aspect_ratio,
                "extra_prompt_suffix": extra_prompt_suffix,
            },
            cost_estimate=cost_estimate,
        ),
    }

    # next_step_hint：拿成功的图当 generate_video 的 first_frame
    valid = [r for r in results if r.get("file_url")]
    segments_hint = []
    for i, r in enumerate(valid):
        nxt = valid[i + 1].get("file_url") if i + 1 < len(valid) else None
        segments_hint.append({
            "prompt": f"第 {r['scene_no']} 段：从分镜图运镜",
            "first_frame": r["file_url"],
            "last_frame": nxt,
            "duration_s": 8,
            "scene_no": r["scene_no"],
        })

    return attach_next_step(
        out,
        suggested_tool="generate_video",
        suggested_args={
            "segments": segments_hint,
            "face_refs": face_refs or [],
            "product_refs": product_refs or [],
            "aspect_ratio": aspect_ratio,
        },
        human_text=(
            f"已落 {success_count}/{len(scenes)} 张分镜图到血缘（pipeline.assets, status=draft）；"
            f"老板审完逐张采纳，再用这些图当 first_frame 跑 {len(segments_hint)} 段视频"
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


@tool_with_audit(mcp, require_approval=False)
async def generate_video_segments(
    script_id: str,
    scene_nums: list[int] | None = None,
    face_refs: list[str] | None = None,
    product_refs: list[str] | None = None,
    aspect_ratio: str = "9:16",
    duration_s: int = 8,
    use_last_frame: bool = True,
    extra_prompt_suffix: str | None = None,
    dry_run: bool = False,
) -> dict:
    """W4-B 切片 14.4 phase D step 7：拉 script.scenes，用 step 6 出的分镜图当
    first_frame + character_sheet 锁脸 face_refs，并发调 seedance-2-0 出每段视频。

    跟 step 6 generate_storyboard_images 对照（同结构、同占位翻译规则、同严格参考
    产品 hint）；区别只是把 client.generate_image_v2 换成 generate_video_v2 + 加
    first_frame 注入 + 输出 落 pipeline.assets(asset_type='video', duration_seconds)。

    Args:
        script_id: pipeline.scripts.id（kind 须 startswith 'video_'）
        scene_nums: 只跑这几段（None = 全跑）；用于单段重跑
        face_refs / product_refs: 全段共用人工补充参考（自动 character_sheet 之外）
        aspect_ratio: 画幅（默认 9:16）
        duration_s: 每段时长秒（seedance 接受 4-15，默认 8）
        use_last_frame: True 则把下段 first_frame 当本段 last_frame 串场（默认不串）
        extra_prompt_suffix: 每段 prompt 末尾追加（如"slow handheld motion, breathy ambient sound"）
        dry_run: True 时只拼 prompt 不调 seedance 不落库（用于调试 prompt，零费用）

    Returns:
        {ok, result: {script_id, kind, sku_id, scenes_total, success_count, error_count,
                      results: [{scene_no, asset_id, video_url, prompt, first_frame_used,
                                 last_frame_used, face_refs_used, product_refs_used,
                                 characters_in_scene, product_appearance, duration_s, task_id}
                              | {scene_no, error, prompt}]},
         trace, next_step_hint(None — 链路终点，下载交剪辑)}

    前置：
    - script.scenes 非空（v11+ 含 image_prompt / characters_in_scene / product_appearance）
    - script_id 的 image asset 非空（先跑 step 6 generate_storyboard_images）；
      不够会返 missing_storyboard_images + 缺哪几段
    """
    from app.services.pipeline_lineage import (
        get_creative_pack, save_storyboard_asset, list_character_sheets_for_script,
        list_assets,
    )

    script = await get_creative_pack(script_id)
    if not script:
        return {"ok": False, "error": "script_not_found", "script_id": script_id,
                "hint": "script_id 不存在或已 archived"}

    kind = script.get("kind") or ""
    if not kind.startswith("video_"):
        return {"ok": False, "error": "non_video_kind", "kind": kind,
                "hint": f"step 7 只能跑 video_* kind 脚本；当前 kind={kind}（图文/主图/详情页等没有视频段）"}

    scenes = script.get("scenes") or []
    if not scenes:
        return {"ok": False, "error": "no_scenes", "script_id": script_id,
                "hint": "脚本 scenes 为空。先 backfill 或重跑 step 5"}

    if scene_nums:
        scenes = [s for s in scenes if s.get("scene_no") in scene_nums]
    if not scenes:
        return {"ok": False, "error": "no_matching_scenes", "scene_nums": scene_nums,
                "hint": f"指定 scene_nums={scene_nums} 在脚本里没匹配；脚本含 scene_no={[s.get('scene_no') for s in (script.get('scenes') or [])]}"}

    # 拉同 script 的 image asset（step 6 出的分镜图）→ scene_no → first_frame url
    # 同一 scene 可能跑多次累积多张图 → 优先用 adopted 那张，fallback 最新 draft
    image_assets = await list_assets(script_id=script_id, asset_type="image", limit=200)
    # list_assets 已按 scene_no + created_at DESC 排序，相同 scene_no 第一张是最新
    from collections import defaultdict
    by_scene: dict[int, list[dict]] = defaultdict(list)
    for a in image_assets:
        sn = a.get("scene_no")
        if sn is not None and a.get("file_url"):
            by_scene[int(sn)].append(a)
    scene_to_first_frame: dict[int, str] = {}
    for sn, assets in by_scene.items():
        # 优先 adopted（采纳那张），fallback 最新 draft
        adopted = [x for x in assets if x.get("status") == "adopted"]
        chosen = adopted[0] if adopted else assets[0]
        scene_to_first_frame[sn] = chosen["file_url"]

    # 校验：要跑的 scene_no 必须都有 image asset；缺哪几段先提示
    # dry_run 跳过（调 prompt 不依赖图）
    missing_images = [s.get("scene_no") for s in scenes
                      if int(s.get("scene_no") or -1) not in scene_to_first_frame]
    if missing_images and not dry_run:
        return {"ok": False, "error": "missing_storyboard_images",
                "scene_nums_missing_image": missing_images,
                "hint": (
                    f"以下分镜还没出图（image asset）：{missing_images}。"
                    f"先跑 generate_storyboard_images(script_id='{script_id}', "
                    f"scene_nums={missing_images}) 再回来跑 step 7 视频"
                )}

    model_cfg = get_model_for_tool("generate_video")
    provider = model_cfg.get("provider", "seedance")
    model = model_cfg.get("model", "seedance-2-0")
    # 视频生成 timeout 长（单段 60-180s + 排队 + 轮询，给 5min 余量）
    client = AIHubClient(timeout=300.0)

    # 拉同 script 的 character_sheet asset → role → face_ref url
    character_sheets_assets = await list_character_sheets_for_script(script_id)
    role_to_url: dict[str, str] = {}
    for a in character_sheets_assets:
        role = a.get("character_role")
        url = a.get("file_url")
        if role and url and role not in role_to_url:
            role_to_url[role] = url

    # 角色元信息：role_id → {zh_name, gender_en, gender_zh}
    # 来源 pipeline.scripts.character_sheets（step 5 LLM 写的，含中文名）
    char_sheets_meta = script.get("character_sheets") or []
    role_to_gender: dict[str, str] = {}
    role_to_zh_name: dict[str, str] = {}
    for s in char_sheets_meta:
        rid = s.get("role_id")
        gender_zh = (s.get("gender") or "").strip()
        gender_en = "woman" if gender_zh == "女" else "man" if gender_zh == "男" else "person"
        if rid:
            role_to_gender[rid] = gender_en
            zh = (s.get("name") or "").strip()
            if zh:
                role_to_zh_name[rid] = zh

    def _zh_role_label(role_id: str) -> str:
        """role_id → 中文标签，优先 character_sheets.name，回退按 gender 给"那位女士/那位男士"。"""
        zh = role_to_zh_name.get(role_id)
        if zh:
            return zh
        g = role_to_gender.get(role_id, "person")
        return "那位女士" if g == "woman" else "那位男士" if g == "man" else f"角色 {role_id}"

    _CHAR_SHEET_REF_RE = re.compile(r"character_sheet\s*\[\s*([a-z_][a-z0-9_]*)\s*\]", re.I)

    def _replace_char_sheet_refs(prompt: str, scene: dict, manual_face_refs_count: int) -> str:
        chars = scene.get("characters_in_scene") or []
        if not chars or "character_sheet[" not in prompt.lower():
            return prompt
        role_to_idx: dict[str, int] = {}
        for i, role_id in enumerate(chars):
            role_to_idx[role_id] = manual_face_refs_count + i + 1

        def _sub(m: re.Match) -> str:
            role_id = m.group(1)
            idx = role_to_idx.get(role_id)
            gender = role_to_gender.get(role_id, "person")
            if idx is None:
                return m.group(0)
            return f"the {gender} shown in reference image {idx}"

        return _CHAR_SHEET_REF_RE.sub(_sub, prompt)

    # ── dialog 字段三类标注解析（step 5 prompt 约定：对白 / 画外音独白 / 屏幕字幕）──
    _SUBTITLE_TOKENS = ("屏幕字幕", "字幕居中", "字幕浮现", "字幕弹出", "字幕显示",
                        "屏幕文字", "字幕标题", "字幕")
    _VOICEOVER_TOKENS = ("画外音独白", "画外音", "v.o.", "voice-over", "voiceover",
                         "独白", "旁白", "narration")
    _DIALOG_ANNOTATION_RE = re.compile(
        r"[（(]\s*([^）)]*?(?:屏幕字幕|字幕[^）)]*|画外音[^）)]*|独白|旁白|v\.?o\.?|voice[-\s]?over|voiceover|narration)[^）)]*)\s*[）)]",
        re.I,
    )

    def _classify_dialog(raw: str) -> tuple[str, str]:
        """返 (kind, cleaned_text)。
        kind ∈ {'speech' 对白嘴要动 / 'voiceover' 画外音嘴不动 / 'subtitle' 字幕嘴不动 / 'none'}。
        step 5 prompt 明确要求 dialog 字段"区分对白、画外音独白、屏幕字幕"，本函数按这个约定 parse。
        """
        d = (raw or "").strip()
        if not d:
            return ("none", "")
        # 提取标注（去括号留纯台词）
        lower = d.lower()
        is_subtitle = any(tok.lower() in lower for tok in _SUBTITLE_TOKENS)
        is_voiceover = any(tok.lower() in lower for tok in _VOICEOVER_TOKENS)
        cleaned = _DIALOG_ANNOTATION_RE.sub("", d).strip()
        # 末尾省略号/句末标点保留
        if is_subtitle:
            return ("subtitle", cleaned)
        if is_voiceover:
            return ("voiceover", cleaned)
        return ("speech", cleaned)

    def _build_prompt(scene: dict, *, has_last_frame: bool) -> str:
        """seedance i2v 模式中文 prompt（火山方舟官方推荐结构 · 严格参考 step 5）。

        参考资料：
        - 火山方舟《Seedance-1.0-pro 提示词指南》(docs/82379/1631633)
        - 社区《1940 个 Seedance 2.0 prompt 总结》8 种实战写法
        - apiyi.com Seedance 2.0 Ultimate Prompt Guide

        i2v 模式核心认知（跟 t2v 完全不同）：
        - 首帧图本身已包含构图/光线/色调/角色外观全部视觉信息 → prompt 不重复
        - 重点：motion（动作）+ camera（镜头）+ 一致性强调 + 转场过渡 + negative prompt

        严格参考 step 5 创意素材（10 字段全用 / 不丢任何标注）：
          time_range / characters_in_scene / visual / change_point / shot /
          dialog (区分对白/画外音/字幕 3 类) / product_appearance
          + image_prompt（v10 老脚本兜底）

        dialog 字段处理（老板硬规则："如果有台词，可以没声音，但要有口型变化"）：
          - kind='speech' 对白 → 画面中说话角色嘴部自然张合（无音轨，纯视觉）
          - kind='voiceover' 画外音/独白 → 角色嘴部静止（后期配画外音）
          - kind='subtitle' 屏幕字幕 → 角色嘴部静止 + 视频本身不渲染字幕文字（后期合成）

        sound 字段不喂（seedance 无 TTS + omni 无配音管线 feedback_no_recording_pipeline）。

        v10 老脚本无中文字段时回退 image_prompt + 占位翻译（兼容性兜底）。
        """
        tr = (scene.get("time_range") or f"0-{duration_s}s").strip()
        visual = (scene.get("visual") or "").strip()
        change = (scene.get("change_point") or "").strip()
        shot = (scene.get("shot") or "").strip()
        chars = scene.get("characters_in_scene") or []
        product_in = scene.get("product_appearance")
        dialog_kind, dialog_text = _classify_dialog(scene.get("dialog") or "")

        # 老格式兜底：中文字段全空才走 image_prompt 兼容路径
        if not visual and not change and not shot:
            ip = (scene.get("image_prompt") or "").strip()
            if ip:
                manual_count = len(face_refs or [])
                ip = _replace_char_sheet_refs(ip, scene, manual_count)
                prompt = f"[{tr}] {ip}"
            else:
                prompt = f"[{tr}]"
            if extra_prompt_suffix:
                prompt = f"{prompt}\n{extra_prompt_suffix}".strip()
            return prompt

        parts: list[str] = [f"[时长 {tr}]"]

        # ── 画面延续（i2v 模式核心标识 · 对应官方 "Animate the provided image,
        #     preserve composition and colors, keep consistent lighting"）──
        if chars:
            char_labels = "、".join(_zh_role_label(c) for c in chars)
            parts.append(
                f"画面延续：基于参考首帧生成动画，画面中的{char_labels}保持五官、发型、服装、神态完全不变；"
                f"沿用首帧的构图、空间环境、光线方向、色温、整体色调"
            )
        else:
            parts.append(
                "画面延续：基于参考首帧生成动画，沿用首帧的构图、空间环境、光线方向、色温、整体色调"
            )

        # ── 动作（核心 · camera/subject 分离原则 · 把 visual 当完整动作流喂）──
        action_pieces: list[str] = []
        if visual:
            action_pieces.append(visual)
        if change and change not in visual:
            action_pieces.append(f"动作衔接点：{change}")
        if action_pieces:
            parts.append("动作：" + "；".join(action_pieces))

        # ── 镜头（参考官方运镜术语 · 显式注入"平稳缓慢"避免 seedance 自加快镜头/抖动）──
        if shot:
            parts.append(f"镜头：{shot}（运镜平稳缓慢，无抖动无快速切换）")

        # ── 台词与口型（老板硬规则：有台词可以没声音，但要有口型变化）──
        if dialog_kind == "speech":
            speaker = "、".join(_zh_role_label(c) for c in chars) if chars else "画面中的说话角色"
            parts.append(
                f"台词与口型：本段为对白，{speaker} 的嘴部按以下台词节奏自然张合"
                f"（口型变化柔和不夸张，配合短语节拍；视频本身静音无音轨）："
                f"「{dialog_text}」"
            )
        elif dialog_kind == "voiceover":
            speaker = "、".join(_zh_role_label(c) for c in chars) if chars else "画面中的角色"
            parts.append(
                f"台词与口型：本段台词以画外音/独白形式呈现（后期外部配音），"
                f"{speaker} 的嘴部保持自然状态、不张合不说话。"
                f"画外音原文（仅供画面节奏参考，不出现在视频里）：「{dialog_text}」"
            )
        elif dialog_kind == "subtitle":
            speaker = "、".join(_zh_role_label(c) for c in chars) if chars else "画面中的角色"
            parts.append(
                f"台词与口型：本段台词以后期屏幕字幕形式呈现，"
                f"{speaker} 的嘴部保持自然状态、不张合；"
                f"视频本身不渲染任何字幕文字（字幕后期合成）。"
                f"屏幕字幕原文（仅供画面节奏参考，不出现在视频里）：「{dialog_text}」"
            )

        # ── 产品（product_appearance=true 锁产品；false 这段禁止出现）──
        if product_in is True:
            parts.append("产品：标签、包装、颜色、形状与参考图完全一致，不变形不重画")
        elif product_in is False:
            parts.append("产品：本段不出现产品，画面中不要任何瓶身/包装/品牌字样")

        # ── 转场（仅当下一段有图作 last_frame 时启用）──
        if has_last_frame:
            parts.append("结尾过渡：本段镜头自然收束到下一段画面的构图，过渡平滑无生硬切换")

        # ── 标准 negative prompt（seedance 官方推荐避免词 + 项目特定）──
        # 注意：speech 类有"嘴自然张合"指令，negative 里只禁"不自然抽搐/规则乱"
        parts.append(
            "避免：脸型/身份漂移、肢体扭曲（多手指、断肢、关节错位）、画面抖动、时序闪烁、"
            "光线色温突变、文字水印、品牌 logo 文字、屏幕字幕（字幕后期加）、"
            "嘴型抽搐/咬字过猛/与台词节奏脱节"
        )

        prompt = "\n".join(parts)

        if extra_prompt_suffix:
            prompt = f"{prompt}\n{extra_prompt_suffix}".strip()
        return prompt

    def _append_strict_product_hint(prompt: str, face_count: int, product_count: int) -> str:
        if product_count <= 0:
            return prompt
        start_idx = face_count + 1
        end_idx = face_count + product_count
        ref_clause = (
            f"reference image {start_idx}" if start_idx == end_idx
            else f"reference images {start_idx} to {end_idx}"
        )
        hint = (
            f"\n\nProduct fidelity constraint: Strictly reproduce the product shown in {ref_clause} "
            f"(exact label, packaging design, color, proportions and any visible text — "
            f"do not invent, restyle or modify any visual element of the product itself; "
            f"only the surrounding scene, lighting and composition follow the main prompt)."
        )
        return prompt + hint

    def _resolve_face_refs(scene: dict) -> list[str]:
        urls: list[str] = list(face_refs or [])
        chars = scene.get("characters_in_scene") or []
        for role in chars:
            url = role_to_url.get(role)
            if url and url not in urls:
                urls.append(url)
        return urls

    def _resolve_product_refs(scene: dict) -> list[str] | None:
        appears = scene.get("product_appearance")
        if appears is False:
            return None
        return list(product_refs) if product_refs else None

    # 按 scene_no 升序排（last_frame 串场需要顺序）
    sorted_scenes = sorted(scenes, key=lambda s: int(s.get("scene_no") or 0))

    # 从 scene.time_range 解析每段实际时长（"0-4s" → 4，"23-30s" → 7）
    # 失败 fallback 到 duration_s 参数。seedance 限制 [4, 15]：< 4 拉到 4，> 15 截到 15
    _TIME_RANGE_RE_LOCAL = re.compile(r'^\s*(\d+)\s*-\s*(\d+)\s*s?\s*$', re.I)

    def _compute_scene_duration(scene: dict, fallback: int) -> int:
        tr = (scene.get("time_range") or "").strip()
        m = _TIME_RANGE_RE_LOCAL.match(tr)
        if m:
            try:
                start, end = int(m.group(1)), int(m.group(2))
                if end > start:
                    return max(4, min(15, end - start))
            except (TypeError, ValueError):
                pass
        return max(4, min(15, fallback))

    # 全局 next_scene_map：按脚本所有 scene_no 升序排，scene N → scene N+1 的 image_url
    # 即使老板只选 1 段单跑，也能拿全局下一段图作 last_frame 串场（之前 bug：只看本次跑列表
    # 的下一段，单跑时 last_frame=None 失去串场）
    all_scenes_sorted = sorted(
        [int(s.get("scene_no") or 0) for s in (script.get("scenes") or []) if s.get("scene_no") is not None]
    )
    next_scene_map: dict[int, int | None] = {}
    for i, sn in enumerate(all_scenes_sorted):
        next_scene_map[sn] = all_scenes_sorted[i + 1] if i + 1 < len(all_scenes_sorted) else None

    async def _one(idx: int, scene: dict) -> dict:
        scene_no = int(scene.get("scene_no") or 0)

        first_frame = scene_to_first_frame.get(scene_no)
        # dry_run 跳过 first_frame 必须存在的检查（调 prompt 不依赖图）
        if not first_frame and not dry_run:
            return {"scene_no": scene_no, "error": "no_first_frame_image_asset",
                    "hint": f"scene {scene_no} 缺 step 6 分镜图 — 先跑 generate_storyboard_images"}

        # 全局下一段图作 last_frame（用 next_scene_map，不再用本次跑列表的下一段）
        last_frame: str | None = None
        if use_last_frame:
            nxt_sn = next_scene_map.get(scene_no)
            if nxt_sn is not None:
                last_frame = scene_to_first_frame.get(nxt_sn)

        # prompt 拼装需要知道 has_last_frame（决定加不加转场段）
        prompt = _build_prompt(scene, has_last_frame=last_frame is not None)
        if not prompt:
            return {"scene_no": scene_no, "error": "scene_prompt_empty"}

        # 每段从 scene.time_range 解析实际时长（无则 fallback duration_s 参数）
        # seedance clamp [4, 15]
        scene_duration = _compute_scene_duration(scene, duration_s)

        # dry_run 短路：只返 prompt + 时长 + 引用，零费用 / 不落库（调 prompt 用）
        if dry_run:
            return {
                "scene_no": scene_no,
                "prompt": prompt,
                "first_frame_used": first_frame,
                "last_frame_used": last_frame,
                "duration_s": scene_duration,
                "scene_time_range": (scene.get("time_range") or "").strip() or None,
                "characters_in_scene": scene.get("characters_in_scene") or [],
                "product_appearance": scene.get("product_appearance"),
                "dry_run": True,
            }

        scene_face_refs = _resolve_face_refs(scene)
        scene_product_refs = _resolve_product_refs(scene)

        # 火山方舟硬约束（2026-05-11 实测）：first_frame 跟 reference_images 任何 model 互斥；
        # 1.x 系列（含 1.5-pro-251215）只支持 t2v + i2v，不支持 r2v（reference_images）。
        # → step 7 走 i2v 模式：first_frame 优先，reference_images 全清掉（face/product 锁脸
        #   靠 step 6 分镜图本身已按 character_sheet 锁过脸间接传递）
        # → 等 2.0 激活后看是否开放 r2v + i2v 混合（火山方舟可能仍互斥），届时再调
        _model_supports_r2v = "seedance-2-" in (model or "")
        _refs_blocked_reason: str | None = None
        if first_frame and (scene_face_refs or scene_product_refs):
            _refs_blocked_reason = "first_frame_i2v_excludes_refs"
            scene_face_refs = []
            scene_product_refs = None
        elif not _model_supports_r2v and (scene_face_refs or scene_product_refs):
            _refs_blocked_reason = "model_does_not_support_r2v"
            scene_face_refs = []
            scene_product_refs = None

        if scene_product_refs:
            prompt = _append_strict_product_hint(
                prompt,
                face_count=len(scene_face_refs or []),
                product_count=len(scene_product_refs),
            )

        try:
            start_resp = await client.generate_video_v2(
                prompt=prompt,
                first_frame=first_frame,
                last_frame=last_frame,
                duration_sec=scene_duration,
                face_refs=scene_face_refs or None,
                product_refs=scene_product_refs,
                aspect=aspect_ratio,
                model=model,
                provider=provider,
            )
            task_id = (
                start_resp.get("task_id")
                or (start_resp.get("data") or {}).get("task_id")
            )
            if not task_id:
                url = start_resp.get("video_url") or (start_resp.get("data") or {}).get("video_url")
                if not url:
                    return {"scene_no": scene_no, "error": "no_task_id_no_url", "prompt": prompt}
                video_url, task_id_out = url, None
            else:
                done = await client.wait_for_video(task_id, max_seconds=600, poll=5.0)
                data = done.get("data") or done
                if data.get("status") in ("failed", "error"):
                    return {"scene_no": scene_no,
                            "error": f"seedance {data.get('status')}: "
                                     f"{data.get('error') or data.get('message') or ''}",
                            "prompt": prompt, "task_id": task_id}
                video_url = data.get("video_url") or data.get("url")
                task_id_out = task_id

            if not video_url:
                return {"scene_no": scene_no, "error": "no_video_url_returned",
                        "prompt": prompt, "task_id": task_id_out}

            asset_id = await save_storyboard_asset(
                sku_id=script["sku_id"],
                asset_type="video",
                script_id=script_id,
                audience_pack_id=script.get("audience_pack_id"),
                audience_record_id=script.get("audience_record_id"),
                matrix_run_id=script.get("matrix_run_id"),
                scene_no=scene_no,
                file_url=video_url,
                duration_seconds=float(scene_duration),
                external_video_id=task_id_out,
                prompt=prompt,
            )
            return {
                "scene_no": scene_no,
                "asset_id": asset_id,
                "video_url": video_url,
                "prompt": prompt,
                "first_frame_used": first_frame,
                "last_frame_used": last_frame,
                "face_refs_used": scene_face_refs,
                "product_refs_used": scene_product_refs or [],
                "refs_blocked_reason": _refs_blocked_reason,  # i2v 互斥或 model 不支持 r2v 时填
                "characters_in_scene": scene.get("characters_in_scene") or [],
                "product_appearance": scene.get("product_appearance"),
                "duration_s": scene_duration,
                "scene_time_range": (scene.get("time_range") or "").strip() or None,
                "task_id": task_id_out,
            }
        except Exception as exc:
            return {"scene_no": scene_no, "error": f"{type(exc).__name__}: {exc}",
                    "prompt": prompt}

    results = await asyncio.gather(*(_one(i, s) for i, s in enumerate(sorted_scenes)))
    success_count = sum(1 for r in results if r.get("asset_id"))
    error_count = sum(1 for r in results if r.get("error"))

    cost_per = "¥15" if provider == "seedance" else "未知"
    cost_estimate = f"~{len(sorted_scenes)} × {cost_per}"

    out = {
        "ok": True,
        "result": {
            "script_id": script_id,
            "kind": kind,
            "sku_id": script.get("sku_id"),
            "scenes_total": len(sorted_scenes),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        },
        "trace": build_trace(
            provider=provider,
            model=model,
            prompt=f"script_id={script_id} kind={kind} → {len(sorted_scenes)} 段视频并发出（first_frame from step 6 images）",
            params={
                "scene_nums": scene_nums,
                "face_refs": face_refs or [],
                "product_refs": product_refs or [],
                "aspect_ratio": aspect_ratio,
                "duration_s": duration_s,
                "use_last_frame": use_last_frame,
                "extra_prompt_suffix": extra_prompt_suffix,
            },
            cost_estimate=cost_estimate,
        ),
    }

    return attach_next_step(
        out,
        suggested_tool=None,
        suggested_args={},
        human_text=(
            f"已落 {success_count}/{len(sorted_scenes)} 段视频到血缘（pipeline.assets, status=draft）；"
            f"老板逐段下载交剪辑（不自动拼接）。"
        ),
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

    # 落库 pipeline.matrix_runs（status=draft；老板审完手点采纳）
    matrix_run_id = await pipeline_lineage.save_matrix_run(
        sku_id=sku_id,
        matrix_md=matrix_md,
        user_initial_points=user_initial_points,
        user_reviews=user_reviews,
        kb_context=kb_context,
        extra_context=extra_context,
        model_provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        final_prompt=final_prompt,
        cost_estimate="1 quota call (~3-5k tokens)",
    )

    result = {
        "ok": True,
        "result": {
            "matrix_md": matrix_md,
            "sku_id": sku_id,
            "matrix_run_id": matrix_run_id,
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.5),
                "max_tokens": 6000,
                "matrix_run_id": matrix_run_id,
            },
            cost_estimate="1 quota call (~3-5k tokens)",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_audience_match",
        suggested_args={"sku_id": sku_id, "matrix_md": matrix_md, "matrix_run_id": matrix_run_id},
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
    matrix_run_id: str | None = None,
) -> dict:
    """生成 SKU 人群匹配（sku-pipeline step 3）。

    输入 step 2 的卖点矩阵 markdown，内部按多 query 策略召回人群分析报告 KB
    （绕开 KB 单 query 偏移），喂给 pro 模型，输出 2 部分人群匹配报告：

    - 第 1 部分：KB 匹配人群（≥ 15 个，跨 ≥ 10 doc，KB 原文 1:1 + 匹配理由 ≥ 5 条）
    - 第 2 部分：结构化标签汇总（≥ 30 条）

    严格不写：圈包标签 / 优先级 / 预算 / 投放渠道 / 脚本 / 钩子 / 拒绝候选

    返回后**自动落库**：1 条 pipeline.audience_runs + N 条 pipeline.audience_records
    （regex 拆 #### 1.X [人群名] 段），老板可从 N 条里选 1 个挂下游 step 4 圈包。

    Args:
        sku_id: SKU id
        matrix_md: step 2 输出的卖点矩阵 markdown（必填，没这个反向推理无依据）
        extra_context: 额外要求（如"重点挖跨圈层"/"对标 X 品牌"）
        kb_recall_override: 显式覆盖 KB 召回（老板手贴 chunks 时用）
        matrix_run_id: 上游 step 2 落库的 matrix_run_id；不传则自动用 sku 最新 matrix_run，没有则用本次 matrix_md 自动建一条 stub

    Returns:
        {ok, result: {audience_md, sku_id, recall_meta, audience_run_id, records:[...]},
         trace, next_step_hint(audience_sop_pack)}
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

    # 解析 / 落库 matrix_run（如果调用方没传 id，自动 fallback 或建 stub）
    effective_matrix_run_id = matrix_run_id
    if not effective_matrix_run_id:
        # 用 sku 最新的 matrix_run 兜底；都没有就拿本次 matrix_md 自动建 stub
        pool = get_pool()
        latest = await pool.fetchrow(
            "SELECT id::text AS id FROM pipeline.matrix_runs "
            "WHERE sku_id = $1 ORDER BY created_at DESC LIMIT 1",
            sku_id,
        )
        if latest and latest["id"]:
            effective_matrix_run_id = latest["id"]
        else:
            effective_matrix_run_id = await pipeline_lineage.save_matrix_run(
                sku_id=sku_id,
                matrix_md=matrix_md,
                extra_context="(stub — auto-created from generate_audience_match 调用，没有真实 step 2 跑过)",
                model_provider="(stub)",
                model="(stub)",
            )

    # 落库 pipeline.audience_runs + 拆 N 条 pipeline.audience_records
    audience_run_id = None
    records: list[dict] = []
    if effective_matrix_run_id:
        audience_run_id, records = await pipeline_lineage.save_audience_run(
            matrix_run_id=effective_matrix_run_id,
            sku_id=sku_id,
            audience_md=audience_md,
            recall_meta=recall_meta,
            extra_context=extra_context,
            kb_recall_override=kb_recall_override,
            model_provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3.1-pro-preview"),
            final_prompt=final_prompt,
            cost_estimate="1 quota call (~5-8k tokens) + 多 query KB 召回",
        )

    result = {
        "ok": True,
        "result": {
            "audience_md": audience_md,
            "sku_id": sku_id,
            "recall_meta": recall_meta,
            "matrix_run_id": effective_matrix_run_id,
            "audience_run_id": audience_run_id,
            "records": [
                {
                    "id": r.get("id"),
                    "ordinal": r.get("ordinal"),
                    "name": r.get("name"),
                    "kb_doc": r.get("kb_doc"),
                    "kb_section": r.get("kb_section"),
                    "layer_tags": r.get("layer_tags") or [],
                    "match_reason_count": len(r.get("match_reasons") or []),
                }
                for r in records
            ],
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
                "audience_run_id": audience_run_id,
                "records_parsed": len(records),
            },
            cost_estimate="1 quota call (~5-8k tokens) + 多 query KB 召回",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_audience_pack",
        suggested_args={
            "sku_id": sku_id,
            "audience_run_id": audience_run_id,
            "audience_record_ids_to_choose_from": [r.get("id") for r in records if r.get("id")],
        },
        human_text="step 4 圈包 SOP — 老板从 records 选 1 个 audience_record_id → 调 generate_audience_pack 出 8 大维度 DMP 标签 + 预算 + A/B 矩阵",
    )


# ============================================================
# W4-B 切片 14.3 phase B：sku-pipeline step 4 — 圈包 SOP
# ============================================================

# 巨量云图 + 巨量千川 authoritative KB（圈包标签必须从这两个 KB 找出处）
_PLATFORM_KB_IDS = (
    "608807ec-29ff-4fc0-b15b-73d0609c93a8",  # 巨量云图
    "1d6c0d68-5b4a-4ceb-ade8-10f887e895c6",  # 巨量千川
)


def _build_platform_queries(
    sku_category: str | None,
    sku_name: str | None,
    layer_tags: list[str],
    matrix_md: str,
) -> list[str]:
    """构造云图+千川 KB 召回 query 清单。
    覆盖：平台维度通用 / SKU 品类锚 / 人群圈层锚 / matrix 卖点锚。
    """
    queries = [
        "巨量云图 自定义人群 标签维度",
        "巨量云图 数据工厂 圈选方式",
        "巨量云图 行为意向 标签层级",
        "巨量云图 行业兴趣 三级品类",
        "巨量云图 8A 人群分层",
        "巨量云图 5A 人群资产",
        "巨量千川 莱卡定向",
        "巨量千川 人群定向 圈包",
        "巨量千川 关键词定向 词包",
        "巨量千川 抖音号定向",
    ]
    if sku_category:
        queries.append(f"{sku_category} 行业偏好 人群标签")
    if sku_name:
        # 取 sku name 前 8 字作为锚（避免长 query 召回偏）
        queries.append(f"{sku_name[:8]} 人群定向")
    for tag in (layer_tags or [])[:5]:
        queries.append(f"{tag} 圈层人群 标签")
    # matrix 卖点关键词
    seed = _extract_seed_phrases(matrix_md)
    for s in seed[:5]:
        queries.append(f"{s} 标签 兴趣")
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


async def _recall_platform_kb_chunks(
    queries: list[str],
    top_k_per_query: int = 3,
    max_chunks: int = 30,
) -> list[dict]:
    """从巨量云图 + 巨量千川 authoritative KB 多 query 召回 chunks，doc round-robin 去重。"""
    name_map: dict[str, str] = {}
    try:
        from app.services import ingestion as _ingestion
        kbs = await _ingestion.list_kbs()
        name_map = {k["id"]: k["name"] for k in kbs}
    except Exception:
        pass

    async def _one(q: str) -> tuple[str, list[dict]]:
        try:
            hits = await rag_chain.retrieve_multi_kb(
                q,
                list(_PLATFORM_KB_IDS),
                top_k_per_kb=top_k_per_query,
                kb_name_map=name_map,
            )
            return q, hits
        except Exception:
            return q, []

    results = await asyncio.gather(*[_one(q) for q in queries])
    seen: set[str] = set()
    merged: list[dict] = []
    for q, hits in results:
        for h in hits:
            cid = str(h.get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            h2 = dict(h)
            h2["query_origin"] = q
            merged.append(h2)

    by_doc: dict[str, list[dict]] = {}
    for h in merged:
        title = (h.get("title") or "").strip() or "（无标题）"
        by_doc.setdefault(title, []).append(h)
    for d in by_doc:
        by_doc[d].sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    diversified: list[dict] = []
    while len(diversified) < max_chunks and any(by_doc.values()):
        for d in list(by_doc.keys()):
            if by_doc[d]:
                diversified.append(by_doc[d].pop(0))
                if len(diversified) >= max_chunks:
                    break
    return diversified


@tool_with_audit(mcp, require_approval=False)
async def generate_audience_pack(
    audience_record_id: str,
    extra_context: str | None = None,
) -> dict:
    """生成单个人群的圈包 SOP（sku-pipeline step 4）。

    输入老板已勾选的某个 audience_record，自动拉它关联的 matrix_run + sku +
    巨量云图/千川 authoritative KB 召回，LLM 翻译成可在巨量云图后台一步步勾选 +
    可推到千川的圈人 SOP。

    输出固定 5 节：
    - 第 0 部分 4 维度人群画像扩展（带 KB / matrix / 行业推理 来源 tag）
    - 第 1 部分 1.1 概览表 + 1.2 ASCII 圈人架构图（前置工具 → 单元 → 组合 ∩∪- → 推千川）
    - 第 2 部分 N 个圈人单元（数量无上下限，每个细到三级菜单 + 大白话理由 + 跟其他单元的关系）
    - 第 3 部分 交并排拓配方（只在 1 单元不够时才给，按真需要数）
    - 第 4 部分 关键词扩展（按 system 4.7 判定，目的地是云图数据工厂关键词夹）

    严禁：脚本/钩子/文案 / 预测 ROI 或 GMV / 推计划类型 / 重写 KB 原文 /
    预算（测试期/放量期日预算）/ A/B 测试矩阵 / P0-P2 优先级 /
    虚构 KB 不存在的标签（IP 偏好只 5 类等）。

    Args:
        audience_record_id: pipeline.audience_records.id；通常老板从 SKU 已收藏池里选 1 个
        extra_context: 额外要求（如"主推送礼场景""避开同行已饱和标签"）

    Returns:
        {ok, result: {pack_md, audience_pack_id, audience_record_id, sku_id,
                      matrix_run_id, audience_run_id}, trace, next_step_hint(generate_brief 脚本)}
    """
    # 1. 拉 audience_record
    record = await pipeline_lineage.get_audience_record(audience_record_id)
    if not record:
        return {
            "ok": False,
            "error": "audience_record_not_found",
            "hint": "audience_record_id 无效。先调 pipeline_list_audience_records 拉某 sku 的人群池找候选。",
        }

    # 2. 拉关联的 matrix_run（取 record 的 matrix_run_id）
    matrix_run_id = record.get("matrix_run_id")
    audience_run_id = record.get("audience_run_id")
    sku_id = record.get("sku_id")
    if not matrix_run_id or not sku_id:
        return {
            "ok": False,
            "error": "lineage_broken",
            "hint": "audience_record 缺 matrix_run_id 或 sku_id（数据异常）",
            "record_summary": {"id": record.get("id"), "name": record.get("name")},
        }

    matrix_run = await pipeline_lineage.get_matrix_run(matrix_run_id)
    if not matrix_run:
        return {
            "ok": False,
            "error": "matrix_run_not_found",
            "hint": f"audience_record 关联的 matrix_run_id={matrix_run_id} 已不存在（可能被删了）",
        }

    # 3. 拉 SKU 信息
    pool = get_pool()
    sku = await pool.fetchrow(
        "SELECT id, name, category, price_min, price_max, specifications, "
        "owner_selling_points, owner_notes, platform_status "
        "FROM mvp_sku WHERE id = $1",
        sku_id,
    )
    if not sku:
        return {
            "ok": False,
            "error": "sku_not_found",
            "hint": f"sku_id={sku_id} 已不存在",
        }

    # 售价表达
    if sku["price_min"] is not None and sku["price_max"] is not None:
        if sku["price_min"] == sku["price_max"]:
            price_str = f"¥{sku['price_min']}"
        else:
            price_str = f"¥{sku['price_min']} - ¥{sku['price_max']}"
    else:
        price_str = "（信息不足，老板补 SKU 售价后预算才能算准）"

    sku_md = (
        f"- SKU id：{sku['id']}\n"
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '（未分类，调味品）'}\n"
        f"- 规格：{sku['specifications'] or '（无）'}\n"
        f"- 售价：{price_str}\n"
        f"- 抖店平台状态：{sku['platform_status'] or '（unknown）'}\n"
    )

    # 4. 拼 audience 输入段（KB chunk + 5 理由）
    kb_chunk = (record.get("kb_chunk_text") or "（KB chunk 缺失）").rstrip()
    reasons = record.get("match_reasons") or []
    if reasons:
        reasons_md = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(reasons))
    else:
        reasons_md = "（无 — 历史拆分未保留 5 条理由）"
    layer_tags = record.get("layer_tags") or []
    layer_tags_str = " / ".join(layer_tags) if layer_tags else "（无）"
    kb_section_suffix = f" / {record['kb_section']}" if record.get("kb_section") else ""

    # 5. 召回巨量云图 + 巨量千川 KB（让标签真实可勾选，不让 LLM 凭空想象）
    platform_queries = _build_platform_queries(
        sku_category=sku["category"],
        sku_name=sku["name"],
        layer_tags=record.get("layer_tags") or [],
        matrix_md=(matrix_run.get("matrix_md") or ""),
    )
    platform_chunks = await _recall_platform_kb_chunks(
        queries=platform_queries,
        top_k_per_query=3,
        max_chunks=30,
    )
    platform_kb_context = _format_kb_recall(platform_chunks)

    # 6. system + user prompt
    sys_msg = prompts.load("audience_pack.system")
    user_msg = prompts.render(
        "audience_pack.user",
        sku_md=sku_md,
        matrix_md=(matrix_run.get("matrix_md") or "（matrix 缺失）").strip(),
        audience_name=record.get("name") or "（无名）",
        audience_kb_doc=record.get("kb_doc") or "（KB doc 缺失）",
        audience_kb_section_suffix=kb_section_suffix,
        audience_layer_tags=layer_tags_str,
        audience_kb_chunk=kb_chunk,
        audience_match_reasons_md=reasons_md,
        extra_context=extra_context.strip() if extra_context else "（无）",
        platform_kb_context=platform_kb_context,
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    # 6. 调 LLM
    model_cfg = get_model_for_tool("generate_audience_pack")
    client = AIHubClient(timeout=300.0)
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        temperature=model_cfg.get("temperature", 0.3),
        max_tokens=model_cfg.get("max_tokens", 8000),
        enforce_human_voice=True,
    )
    pack_md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()

    # 7. 落库 pipeline.audience_packs
    audience_pack_id = await pipeline_lineage.save_audience_pack(
        audience_record_id=audience_record_id,
        audience_run_id=audience_run_id,
        matrix_run_id=matrix_run_id,
        sku_id=sku_id,
        pack_md=pack_md,
        # dmp_tags / budget_suggestion 留空 jsonb（phase B 先存整段 markdown，
        # 后续切片再加 markdown → 结构化 jsonb 解析）
        dmp_tags=[],
        budget_suggestion={},
        extra_context=extra_context,
        model_provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        final_prompt=final_prompt,
        cost_estimate="1 quota call (~3-5k tokens)",
    )

    result = {
        "ok": True,
        "result": {
            "pack_md": pack_md,
            "audience_pack_id": audience_pack_id,
            "audience_record_id": audience_record_id,
            "audience_run_id": audience_run_id,
            "matrix_run_id": matrix_run_id,
            "sku_id": sku_id,
            "audience_name": record.get("name"),
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.3),
                "max_tokens": model_cfg.get("max_tokens", 8000),
                "audience_pack_id": audience_pack_id,
                "platform_kb_queries": len(platform_queries),
                "platform_kb_chunks": len(platform_chunks),
                "platform_kb_ids": list(_PLATFORM_KB_IDS),
            },
            cost_estimate="1 quota call (~3-5k tokens) + 巨量云图/千川 KB 召回",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_brief",
        suggested_args={
            "sku_id": sku_id,
            "channel": "douyin",
            "extra_context": f"基于 audience_pack_id={audience_pack_id} 出脚本（人群：{record.get('name')}）",
        },
        human_text="step 5/6 出脚本 — generate_brief 拿这个 pack 的标签 + 预算建议作上下文，给单条人群定制脚本",
    )


# ============================================================
# W4-B 切片 14.3 phase B+：500 词关键词扩展（可下载粘贴千川后台）
# ============================================================


def _clean_keyword_pack(text: str, target_count: int) -> tuple[str, int]:
    """清洗 LLM 输出为 N 行纯文本：每行 1 词，无标点无数字，长度 2-15 字。

    Returns:
        (cleaned_text 拼接 \\n, keyword_count)
    """
    if not text:
        return "", 0
    # 去掉 markdown 围栏
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text, flags=re.M)
    text = re.sub(r"\n?```$", "", text, flags=re.M)

    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 保留中英文，去掉数字 / 标点 / emoji / 空白 等所有非字母汉字
        word = re.sub(r"[^一-龥A-Za-z]+", "", line)
        if not word:
            continue
        if len(word) < 2 or len(word) > 15:
            continue
        if word in seen:
            continue
        seen.add(word)
        out.append(word)
        if len(out) >= target_count:
            break
    return "\n".join(out), len(out)


@tool_with_audit(mcp, require_approval=False)
async def generate_keyword_pack(
    seed_keywords: str,
    target_count: int = 500,
    sku_id: str | None = None,
    audience_record_id: str | None = None,
    audience_pack_id: str | None = None,
    extra_context: str | None = None,
) -> dict:
    """生成 N 个相关关键词扩展包（默认 500 词），可下载粘贴进巨量千川/云图后台。

    输出**纯文本一行一词无标点无数字**。后处理会清洗 LLM 输出，确保格式严格正确。

    Args:
        seed_keywords: 种子关键词（逗号 / 空格 / 换行 分隔均可，会自动 normalize）
        target_count: 目标词数（默认 500，最大 1000）
        sku_id: SKU id（可选；不传时尝试从 audience_record/pack 反查）
        audience_record_id: 关联人群 record（可选；自动拉人群信息作 prompt 上下文）
        audience_pack_id: 关联圈包（可选；不传 record_id 时从 pack 反查 record + sku）
        extra_context: 额外要求

    Returns:
        {ok, result: {keyword_text, keyword_count, target_count, keyword_pack_id, sku_id, ...},
         trace, next_step_hint}
    """
    target_count = max(50, min(int(target_count or 500), 1000))

    if not seed_keywords or not seed_keywords.strip():
        return {
            "ok": False,
            "error": "seed_keywords 为空",
            "hint": "至少给 1 个种子词。多个用换行 / 逗号 / 空格分隔。",
        }

    pool = get_pool()

    # 反查 record + sku（如果只给了 audience_pack_id）
    record = None
    if audience_record_id:
        record = await pipeline_lineage.get_audience_record(audience_record_id)
    elif audience_pack_id:
        pack = await pipeline_lineage.get_audience_pack(audience_pack_id)
        if pack:
            audience_record_id = pack.get("audience_record_id")
            if audience_record_id:
                record = await pipeline_lineage.get_audience_record(audience_record_id)
            sku_id = sku_id or pack.get("sku_id")

    if record:
        sku_id = sku_id or record.get("sku_id")

    if not sku_id:
        return {
            "ok": False,
            "error": "sku_id 缺失",
            "hint": "至少给 sku_id 或 audience_record_id 或 audience_pack_id 之一",
        }

    # 拉 SKU 信息
    sku = await pool.fetchrow(
        "SELECT id, name, category, price_min, price_max, specifications "
        "FROM mvp_sku WHERE id = $1",
        sku_id,
    )
    if not sku:
        return {"ok": False, "error": "sku_not_found", "sku_id": sku_id}

    if sku["price_min"] is not None:
        price_str = f"¥{sku['price_min']}" + (f" - ¥{sku['price_max']}" if sku['price_max'] and sku['price_max'] != sku['price_min'] else "")
    else:
        price_str = "（信息不足）"

    sku_md = (
        f"- SKU id：{sku['id']}\n"
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '调味品'}\n"
        f"- 售价：{price_str}\n"
        f"- 规格：{sku['specifications'] or '（无）'}"
    )

    # audience 摘要（如果有）
    if record:
        layer_tags_str = " / ".join(record.get("layer_tags") or []) or "（无）"
        audience_summary = (
            f"- 人群名：{record.get('name')}\n"
            f"- KB 来源：{record.get('kb_doc') or '（无）'}\n"
            f"- 圈层标签：{layer_tags_str}\n"
        )
        # 简短 KB chunk 提示（截短，避免 prompt 太大）
        chunk = (record.get("kb_chunk_text") or "").strip()
        if chunk:
            audience_summary += f"- KB 画像（节选 ≤ 300 字）：{chunk[:300]}"
    else:
        audience_summary = "（未关联人群，按种子词 + SKU 通用扩展）"

    # render prompt
    sys_msg = prompts.load("keyword_pack.system")
    user_msg = prompts.render(
        "keyword_pack.user",
        seed_keywords=seed_keywords.strip(),
        sku_md=sku_md,
        audience_summary=audience_summary,
        extra_context=(extra_context or "").strip() or "（无）",
        target_count=str(target_count),
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    model_cfg = get_model_for_tool("generate_keyword_pack")
    client = AIHubClient(timeout=120.0)
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        temperature=model_cfg.get("temperature", 0.5),
        max_tokens=model_cfg.get("max_tokens", 4500),
        enforce_human_voice=False,  # 关键词包不是人话，关掉防 AI 化检查
    )
    raw = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    )
    keyword_text, keyword_count = _clean_keyword_pack(raw, target_count)

    # 落库
    keyword_pack_id = await pipeline_lineage.save_keyword_pack(
        sku_id=sku_id,
        seed_keywords=seed_keywords,
        keyword_text=keyword_text,
        keyword_count=keyword_count,
        target_count=target_count,
        audience_record_id=audience_record_id,
        audience_pack_id=audience_pack_id,
        extra_context=extra_context,
        model_provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        final_prompt=final_prompt,
        cost_estimate="1 quota call (~1.5-2k tokens)",
    )

    warnings: list[str] = []
    if keyword_count < target_count * 0.8:
        warnings.append(
            f"实际清洗后只 {keyword_count} 词 / 目标 {target_count} 词；"
            f"可能 LLM 输出本身少 / 或重复多被去掉。可加 extra_context 后重跑。"
        )

    result = {
        "ok": True,
        "result": {
            "keyword_text": keyword_text,
            "keyword_count": keyword_count,
            "target_count": target_count,
            "keyword_pack_id": keyword_pack_id,
            "sku_id": sku_id,
            "audience_record_id": audience_record_id,
            "audience_pack_id": audience_pack_id,
            "warnings": warnings,
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.5),
                "max_tokens": model_cfg.get("max_tokens", 4500),
                "target_count": target_count,
                "keyword_count": keyword_count,
                "keyword_pack_id": keyword_pack_id,
            },
            cost_estimate="1 quota call (~1.5-2k tokens)",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool=None,
        suggested_args={"keyword_pack_id": keyword_pack_id},
        human_text="老板下载 .txt 后粘贴进巨量千川 / 云图后台关键词定向输入框即可",
    )


# ============================================================
# W4-B 切片 14.4 phase C：generate_creative_pack（6 类素材脚本）
# ============================================================

_KIND_LABELS = {
    "video_soft_ad": "视频 · 软广（A2 触动）",
    "video_planting": "视频 · 种草（A3 共鸣）",
    "video_harvest": "视频 · 收割（A4 行动）",
    "graphic_harvest": "图文 · 收割",
    "product_main_image": "商品视觉 · 主图",
    "product_detail_page": "商品视觉 · 详情页",
}


# ============================================================
# 创意素材 metrics_json 后端校验（反"LLM 自检装饰"）
# ============================================================

# regex 抠最后一个 ```json {...} ``` 代码块
_METRICS_JSON_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.S,
)


def _extract_metrics_json(script_md: str) -> dict | None:
    """从 LLM 输出尾部抠 metrics_json 代码块。失败返 None 不抛。"""
    if not script_md:
        return None
    matches = _METRICS_JSON_RE.findall(script_md)
    if not matches:
        return None
    raw = matches[-1].strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _compute_actual_scene_gaps(scenes: list[dict]) -> tuple[int | None, int, list[int]]:
    """从 scenes 数组的 time_range 字段（如 "0-4s" / "23-30s"）算每段实际时长。

    返回 (max_gap_seconds, segment_count, durations_list)；
    某段 time_range 解析失败则跳过该段，不影响其他段。
    全部解析失败返 (None, 0, [])。
    """
    pattern = re.compile(r'^\s*(\d+)\s*-\s*(\d+)\s*s\s*$', re.I)
    durations: list[int] = []
    for s in scenes or []:
        tr = (s.get("time_range") or "").strip()
        if not tr:
            continue
        m = pattern.match(tr)
        if not m:
            continue
        try:
            start, end = int(m.group(1)), int(m.group(2))
            if end > start:
                durations.append(end - start)
        except (ValueError, TypeError):
            continue
    if not durations:
        return (None, 0, [])
    return (max(durations), len(durations), durations)


def _validate_creative_metrics(metrics: dict, kind: str, scenes: list[dict] | None = None) -> list[str]:
    """按 kind 路由到对应 validator，返回 warnings list（空 = 全过）。

    设计：v1 只 warn 不 fail（不 retry / 不挂掉调用）。warnings 写到 result，
    前端展示给老板。老板看 metrics 数字 + warnings 自己判断要不要重跑。

    路由：
    - video_soft_ad：8 模块体系（O→A1 让人知道）— v8.5
    - video_planting：9 模块双层体系（A1/A2→A3 让人相信）— v2
    - 其他 kind：暂未实现校验，返空列表
    """
    if kind == "video_soft_ad":
        return _validate_video_soft_ad_metrics(metrics, scenes=scenes)
    if kind == "video_planting":
        return _validate_video_planting_metrics(metrics, scenes=scenes)
    return []


def _validate_video_soft_ad_metrics(metrics: dict, *, scenes: list[dict] | None = None) -> list[str]:
    """video_soft_ad（O→A1 软广 8 模块）metrics 校验。

    v8（W4-B 14.4 phase C v8 八模块）：按 selected_framework 分支校验
    （pixar_spine / slice_of_life / cer / hero_journey / empathy /
    cultural_tension / aspirational / mini_documentary 之一）。
    """
    warnings: list[str] = []
    framework = (metrics.get("selected_framework") or "").strip().lower()

    # === 总时长按 framework ===
    duration_ranges = {
        "pixar_spine": (15, 32),       # M1 标 30s，给 ±2 容差
        "slice_of_life": (15, 32),     # M2
        "cer": (25, 36),               # M3
        "hero_journey": (28, 47),      # M4
        "empathy": (28, 47),           # M5
        "cultural_tension": (43, 62),  # M6
        "aspirational": (28, 47),      # M7
        "mini_documentary": (60, 240), # M8 60s+ ~ 4min
    }
    if framework not in duration_ranges:
        warnings.append(
            f"selected_framework={framework!r} 非法（应为 8 模块之一：pixar_spine/slice_of_life/cer/"
            "hero_journey/empathy/cultural_tension/aspirational/mini_documentary）"
        )
    else:
        dmin, dmax = duration_ranges[framework]
        dur = metrics.get("duration_seconds")
        try:
            if dur is None or not (dmin <= float(dur) <= dmax):
                warnings.append(
                    f"duration_seconds={dur} 不在 {framework} 合理区间 [{dmin}, {dmax}]"
                )
        except (TypeError, ValueError):
            warnings.append(f"duration_seconds={dur!r} 不是数字")

    # === 台词密度按 framework（仅短素材 M1-M3 严格，M4-M8 不强求） ===
    # Slice of Life / CER 都留白主义，极简版可以很低（情绪叙事需要呼吸感）
    # Pixar 因为是 6 句话填空结构，密度需要稍高保证信息推进
    density_ranges = {
        "slice_of_life": (1.0, 4.5),
        "pixar_spine": (3.0, 5.0),
        "cer": (1.0, 4.0),
    }
    if framework in density_ranges:
        dmin, dmax = density_ranges[framework]
        density = metrics.get("dialog_words_per_second")
        if density is not None:
            try:
                d = float(density)
                if not (dmin <= d <= dmax):
                    warnings.append(
                        f"dialog_words_per_second={d} 不在 {framework} 合理区间 [{dmin}, {dmax}]"
                    )
            except (TypeError, ValueError):
                warnings.append(f"dialog_words_per_second={density!r} 不是数字")

    # === 8 模块共同硬约束 ===
    if int(metrics.get("selling_point_dialog_count") or 0) > 0:
        warnings.append(
            f"selling_point_dialog_count={metrics.get('selling_point_dialog_count')} "
            "应为 0（8 模块全程零产品讲解；通用强制原则 #2）"
        )

    if metrics.get("identity_or_setting_hook_present") is False:
        warnings.append(
            "identity_or_setting_hook_present=false（必须身份钩子/Setting 钩子，不准信息钩子）"
        )

    # M7/M8 可豁免截图传播点 + 评论召唤点（按 prompt 通用强制原则 #4 #5）
    framework_no_share_summon = {"aspirational", "mini_documentary"}
    if framework not in framework_no_share_summon:
        if metrics.get("screenshot_share_point_present") is False:
            warnings.append("screenshot_share_point_present=false（必须有截图传播点 — 社交货币）")
        if metrics.get("comment_summon_point_present") is False:
            warnings.append("comment_summon_point_present=false（必须有评论召唤点）")

    # 品牌出现次数（video_soft_ad 统一 O→A1：== 1 次，最后 Brand Mark 字幕算这 1 次）
    brand_count = metrics.get("brand_total_mention_count")
    try:
        bc = int(brand_count) if brand_count is not None else None
        if bc is not None:
            if bc < 1:
                warnings.append(
                    f"brand_total_mention_count={bc} 缺品牌识别（O→A1 命脉是品牌可识别，"
                    "最后 Brand Mark 字幕至少 1 次，否则用户看完不知道是哪个品牌 = 白做）"
                )
            elif bc > 1:
                warnings.append(
                    f"brand_total_mention_count={bc} 超过 1（video_soft_ad 统一 O→A1，"
                    "通用强制 #3 ≤ 1，最后 Brand Mark 字幕只能算这 1 次）"
                )
    except (TypeError, ValueError):
        pass

    # 署名格式（除 M6 文化张力可有 Slogan，其他都禁广告口号 + 必须有署名）
    sig = (metrics.get("brand_signature_format") or "").strip().lower()
    framework_strict_credit = {
        "pixar_spine", "slice_of_life", "cer",
        "hero_journey", "empathy", "aspirational", "mini_documentary",
    }
    if framework in framework_strict_credit:
        if sig not in ("content_credit", "brand_mark"):
            warnings.append(
                f"brand_signature_format={sig!r} 应为 content_credit/brand_mark "
                f"（{framework} 必须有署名，禁广告口号 + 禁 none — A1A2 阶段没署名 = 用户看完不知道是哪个品牌）"
            )
    if sig == "ad_slogan" and framework != "cultural_tension":
        warnings.append(f"brand_signature_format=ad_slogan（{framework} 禁广告口号；M6 文化张力例外可有 Manifesto）")

    # 传播动机：必须单值，禁连接词
    target = (metrics.get("transmission_target") or "").strip()
    if framework not in framework_no_share_summon:
        if not target or target.lower() == "all":
            warnings.append("transmission_target 必须填具体的人（母亲/伴侣/闺蜜/自己等），不能 all 或空")
        elif any(c in target for c in ("或", "和", "/", "&", "、", ",", "，")):
            warnings.append(
                f"transmission_target={target!r} 含多目标连接词（或/和/、/, 等）— 必须单值。"
                "传播动机理论强调'想让某个具体的人看到'，双值 = 稀释传播动机"
            )

    # === 通用底层 8 条 ===
    fsc = metrics.get("first_subtitle_chars")
    try:
        if fsc is not None and int(fsc) > 12:
            warnings.append(f"地板 3 · first_subtitle_chars={fsc} 超过 12（最佳 7-10）")
    except (TypeError, ValueError):
        pass

    # 单段时长上限（反 LLM 自报自欺：用 scenes 实际 time_range 算）
    sg_self = metrics.get("scene_change_max_gap_seconds")
    actual_max_gap, actual_seg_count, actual_durations = _compute_actual_scene_gaps(scenes or [])
    if actual_max_gap is not None:
        if actual_max_gap > 8:
            warnings.append(
                f"地板 4 硬上限 · 实际最长段 {actual_max_gap}s（durations={actual_durations}）超过 8s—画面停滞断完播率"
            )
        # 软广 25-30s 段数下限 5（mini_documentary 例外 4 段）
        target_min = 4 if framework == "mini_documentary" else 5
        if actual_seg_count < target_min:
            warnings.append(
                f"地板 4 段数下限 · 实际段数 {actual_seg_count} < {target_min}（{framework} 框架）"
            )
        if sg_self is not None:
            try:
                if abs(int(sg_self) - actual_max_gap) > 1:
                    warnings.append(
                        f"地板 4 自报数据自欺 · LLM 自报 scene_change_max_gap_seconds={sg_self} 但 scenes 实际最长段 {actual_max_gap}s"
                    )
            except (TypeError, ValueError):
                pass
    else:
        try:
            if sg_self is not None and float(sg_self) > 8:
                warnings.append(f"地板 4 · scene_change_max_gap_seconds={sg_self} 超过 8（无 scenes 数据反验，仅信自报）")
        except (TypeError, ValueError):
            pass

    if metrics.get("first_3s_mentions_product"):
        warnings.append("钩子前 3s 不准提产品（first_3s_mentions_product 必须 false）")

    if metrics.get("ending_open") is False:
        warnings.append("地板 5 · ending_open=false（必须开放性收尾）")

    if metrics.get("hardad_words_present") is True:
        warnings.append("地板 7 · 检测到硬广敏感词（最/第一/绝对/治愈/功效/根治）")

    # === 品牌出现时机按 framework ===
    bfa = metrics.get("brand_first_appearance_second")
    try:
        bfa_val = float(bfa) if bfa is not None else None
    except (TypeError, ValueError):
        bfa_val = None
        warnings.append(f"brand_first_appearance_second={bfa!r} 不是数字")

    if bfa_val is not None:
        if framework == "cer" and bfa_val < 28:
            warnings.append(f"CER 隐身策略 · brand_first_appearance_second={bfa_val} 必须 ≥ 28")
        elif framework == "pixar_spine" and bfa_val < 25:
            warnings.append(
                f"Pixar 隐身策略 · brand_first_appearance_second={bfa_val} 提示品牌名出现过早 "
                "（品类词可中途但品牌名应仅最后 2-3s 署名）"
            )
        elif framework == "mini_documentary" and bfa_val < 60:
            warnings.append(
                f"M8 极克制 · brand_first_appearance_second={bfa_val} 出现过早（M8 通常仅片尾落款）"
            )

    # === M1 Pixar 专属 ===
    if framework == "pixar_spine":
        psc = metrics.get("pixar_six_sentence_count")
        try:
            if psc is None or int(psc) != 6:
                warnings.append(f"M1 Pixar 硬约束 · pixar_six_sentence_count={psc} 必须严格 = 6")
        except (TypeError, ValueError):
            pass

    # === M2 Slice of Life 专属 ===
    if framework == "slice_of_life":
        if metrics.get("slice_setting_specificity_high") is not True:
            warnings.append(
                "M2 Slice of Life · slice_setting_specificity_high=false "
                "（场景必须具体到时间+地点+状态）"
            )
        try:
            qmc = int(metrics.get("slice_quality_moment_close_up_count") or 0)
            if qmc < 1:
                warnings.append(
                    "M2 Slice of Life · slice_quality_moment_close_up_count < 1 "
                    "（至少 1 个质感瞬间特写）"
                )
        except (TypeError, ValueError):
            pass

    # === M3 CER 专属 ===
    if framework == "cer":
        if metrics.get("cer_twist_present") is not True:
            warnings.append("M3 CER · cer_twist_present 必须 true（20-25s 必须有 Twist 反转）")
        rtype = (metrics.get("cer_emotion_release_type") or "").strip().lower()
        if rtype in ("", "none"):
            warnings.append(
                f"M3 CER · cer_emotion_release_type={rtype!r} 不能 none "
                "（必须 tearful/pleasant/enlightened/comforting 之一）"
            )

    # === M4 Hero's Journey 专属 ===
    if framework == "hero_journey":
        if metrics.get("hero_protagonist_is_ordinary") is not True:
            warnings.append(
                "M4 Hero · hero_protagonist_is_ordinary=false（主角必须是普通人，不是成功者）"
            )

    # === M5 Empathy 专属（最关键 — 防贩卖焦虑）===
    if framework == "empathy":
        if metrics.get("empathy_validation_no_blame") is not True:
            warnings.append(
                "M5 Empathy · empathy_validation_no_blame=false（Validation 必须给"
                "'这不是你的错'，不准'你应该更努力' = 贩卖焦虑）"
            )

    # === M6 Cultural Tension 专属 ===
    if framework == "cultural_tension":
        if metrics.get("cultural_tension_real") is not True:
            warnings.append(
                "M6 Cultural Tension · cultural_tension_real=false（必须真实社会文化张力，"
                "不能品牌自己造的伪张力）"
            )

    # === M7 Aspirational 专属 ===
    if framework == "aspirational":
        if metrics.get("aspirational_middle_class_reachable") is not True:
            warnings.append(
                "M7 Aspirational · aspirational_middle_class_reachable=false（生活方式必须"
                "'中产可达' — 不豪宅奢侈品，不出租屋廉价道具）"
            )

    # === M8 Mini-Documentary 专属 ===
    if framework == "mini_documentary":
        if metrics.get("doc_real_subject") is not True:
            warnings.append("M8 Mini-Doc · doc_real_subject=false（必须真实人物，禁演员）")
        if metrics.get("doc_real_interview") is not True:
            warnings.append("M8 Mini-Doc · doc_real_interview=false（必须真实采访，禁配音/后期改语气）")

    # === image_prompt + 角色清单（W4-B 切片 14.4 phase D：脚本=单一创意源）===
    csc = metrics.get("character_sheet_count")
    try:
        csc_val = int(csc) if csc is not None else None
        if csc_val is None or csc_val < 1:
            warnings.append(
                f"phase D · character_sheet_count={csc} 至少 1（出场 ≥ 2 段的角色都要列；"
                "step 6.5 拿这清单先出锁脸定妆照）"
            )
        elif csc_val > 5:
            warnings.append(
                f"phase D · character_sheet_count={csc_val} 偏多（>5 个固定角色不利锁脸；"
                "考虑合并次要角色为'路人'）"
            )
    except (TypeError, ValueError):
        warnings.append(f"phase D · character_sheet_count={csc!r} 不是整数")

    swip = metrics.get("scenes_with_image_prompt_count")
    stc = metrics.get("scenes_total_count")
    try:
        swip_val = int(swip) if swip is not None else None
        stc_val = int(stc) if stc is not None else None
        if swip_val is None or stc_val is None:
            warnings.append(
                f"phase D · scenes_with_image_prompt_count={swip}/scenes_total_count={stc} "
                "必填（每段都需 image_prompt 字段，step 6 直接喂图模型）"
            )
        elif swip_val != stc_val:
            warnings.append(
                f"phase D · scenes_with_image_prompt_count={swip_val} != scenes_total_count={stc_val} "
                "（每段 scene 都必须有 image_prompt，少一段都不行）"
            )
    except (TypeError, ValueError):
        warnings.append(f"phase D · scenes_with_image_prompt_count={swip!r}/scenes_total_count={stc!r} 不是整数")

    ipac = metrics.get("image_prompt_avg_chars")
    try:
        ipac_val = float(ipac) if ipac is not None else None
        if ipac_val is None or not (120 <= ipac_val <= 250):
            warnings.append(
                f"phase D · image_prompt_avg_chars={ipac} 不在 [120, 250] 区间 "
                "（< 120 信息不够、> 250 chatgpt-image-2 易截断）"
            )
    except (TypeError, ValueError):
        warnings.append(f"phase D · image_prompt_avg_chars={ipac!r} 不是数字")

    spa = metrics.get("scene_product_appearance")
    if not isinstance(spa, list):
        warnings.append(
            f"phase D · scene_product_appearance={spa!r} 必须是 boolean 数组 "
            "（每段产品出不出场，长度 == scenes_total_count）"
        )
    else:
        try:
            stc_val_for_spa = int(stc) if stc is not None else None
        except (TypeError, ValueError):
            stc_val_for_spa = None
        if stc_val_for_spa is not None and len(spa) != stc_val_for_spa:
            warnings.append(
                f"phase D · scene_product_appearance 长度 {len(spa)} != scenes_total_count {stc_val_for_spa}"
            )
        true_count = sum(1 for x in spa if x is True)
        if true_count == 0:
            warnings.append(
                "phase D · scene_product_appearance 全 false（每个脚本至少 1 段产品出场，"
                "否则品牌不入画 = 老板的酱油白做了）"
            )
        # 与 brand_total_mention_count 对得上（产品出场段数应 ≥ 品牌出现次数 - 1，因为 Brand Mark 字幕段不需要产品入画）
        try:
            bcv = int(metrics.get("brand_total_mention_count") or 0)
            if bcv > 0 and true_count > bcv + 1:
                warnings.append(
                    f"phase D · scene_product_appearance true 计数 {true_count} 显著超过 "
                    f"brand_total_mention_count {bcv}（产品太频繁出场但品牌不署名 = 廉价感）"
                )
        except (TypeError, ValueError):
            pass

    return warnings


def _validate_video_planting_metrics(metrics: dict, *, scenes: list[dict] | None = None) -> list[str]:
    """video_planting（A1/A2→A3 种草 9 模块双层体系）metrics 校验。

    v2（W4-B 14.4 phase C v2 九模块）：双层结构 — 必须 1 相关性层 (M1/M2) +
    1 判断依据层 (M3-M9)。按 selected_relevance_module + selected_justification_module
    各自分支校验。
    """
    warnings: list[str] = []
    relevance = (metrics.get("selected_relevance_module") or "").strip().lower()
    justification = (metrics.get("selected_justification_module") or "").strip().lower()
    is_dual = bool(metrics.get("is_dual_justification"))

    # === 必须双层结构 ===
    valid_relevance = {"slice_of_life", "problem_naming"}
    valid_justification = {
        "insider_reveal", "origin_story", "comparison_frame", "reason_why",
        "testimonial", "demonstration", "authority_endorsement",
    }
    if relevance not in valid_relevance:
        warnings.append(
            f"selected_relevance_module={relevance!r} 非法（A1A2→A3 必须 "
            "slice_of_life/problem_naming 之一 — 缺相关性层会让用户停在 A1）"
        )
    if justification not in valid_justification:
        warnings.append(
            f"selected_justification_module={justification!r} 非法（A1A2→A3 必须 "
            "insider_reveal/origin_story/comparison_frame/reason_why/testimonial/"
            "demonstration/authority_endorsement 之一 — 缺判断依据层会让用户停在 A2）"
        )

    # === 时长按 单/双 组合 ===
    duration = metrics.get("duration_seconds")
    try:
        d = float(duration) if duration is not None else None
        if d is not None:
            if is_dual and not (38 <= d <= 50):
                warnings.append(
                    f"duration_seconds={d} 双判断组合应 ~ 45s ± 5"
                )
            elif not is_dual and not (25 <= d <= 35):
                warnings.append(
                    f"duration_seconds={d} 单组合应 ~ 30s ± 3（80% 素材应该是单组合）"
                )
    except (TypeError, ValueError):
        warnings.append(f"duration_seconds={duration!r} 不是数字")

    # === 卖点严限（A3 阶段产品功能介绍 ≤ 1 句）===
    spc = metrics.get("selling_point_dialog_count")
    try:
        spc_val = int(spc) if spc is not None else None
        if spc_val is not None and spc_val > 1:
            warnings.append(
                f"selling_point_dialog_count={spc_val} 超过 1（A3 阶段产品功能介绍"
                "全片 ≤ 1 句，自检清单第 3 条；卖点轰炸是 A3 大忌）"
            )
    except (TypeError, ValueError):
        pass

    # === 真实身份披露细节数（中段 ≥ 3 处，桌面自检清单第 5 条）===
    ridc = metrics.get("real_identity_disclosure_count")
    try:
        ridc_val = int(ridc) if ridc is not None else None
        if ridc_val is not None and ridc_val < 3:
            warnings.append(
                f"real_identity_disclosure_count={ridc_val} 少于 3（自检清单第 5 条 — "
                "中段必须有真实身份披露细节 ≥ 3 处，决定 Slice 代入感和 Testimonial 真实度）"
            )
    except (TypeError, ValueError):
        pass

    # === 前 5 秒禁忌（自检清单第 4 条）===
    if metrics.get("first_5s_brand_name_mentioned") is True:
        warnings.append("first_5s_brand_name_mentioned=true（前 5 秒禁出现品牌名 — 自检 #4）")
    if metrics.get("first_5s_product_close_up") is True:
        warnings.append("first_5s_product_close_up=true（前 5 秒禁产品特写 — 自检 #4）")
    if metrics.get("first_5s_ad_style_address") is True:
        warnings.append(
            "first_5s_ad_style_address=true（前 5 秒禁广告化称呼 — 宝子们/家人们/姐妹们 等 — 自检 #4）"
        )

    # === 截图传播点 + 评论召唤点（M8 Demo 可豁免）===
    if justification != "demonstration":
        if metrics.get("screenshot_share_point_present") is False:
            warnings.append(
                "screenshot_share_point_present=false（必须有截图传播点，作为延时画面联想锚点）"
            )
        if metrics.get("comment_summon_point_present") is False:
            warnings.append("comment_summon_point_present=false（必须有评论召唤点）")

    # === 结尾必须具体未来场景画面（自检清单第 7 条）===
    if metrics.get("ending_concrete_future_scene") is False:
        warnings.append(
            "ending_concrete_future_scene=false（结尾必须具体未来场景画面 — 自检 #7，"
            "不是抽象评价/CTA 指令/完结感收尾）"
        )
    if metrics.get("ending_has_cta") is True:
        warnings.append(
            "ending_has_cta=true（A3 阶段不做硬转化 / 结尾不能 CTA — 破坏 A3 形成的心理过程）"
        )

    # === 通用底层 ===
    fsc = metrics.get("first_subtitle_chars")
    try:
        if fsc is not None and int(fsc) > 12:
            warnings.append(f"地板 3 · first_subtitle_chars={fsc} 超过 12（最佳 7-10）")
    except (TypeError, ValueError):
        pass
    # 单段时长上限校验（反"LLM 自报数字自欺"陷阱：从 scenes 实际 time_range 算 max_gap）
    sg_self = metrics.get("scene_change_max_gap_seconds")
    actual_max_gap, actual_seg_count, actual_durations = _compute_actual_scene_gaps(scenes or [])
    if actual_max_gap is not None:
        # 硬上限：单段 > 8s 失败（M8 demonstration 完整动作镜头可豁免，但 prompt 已要求超 8 必拆）
        if actual_max_gap > 8:
            warnings.append(
                f"地板 4 硬上限 · 实际最长段 {actual_max_gap}s（durations={actual_durations}）超过 8s 上限—画面停滞断完播率"
            )
        # 段数下限：30s/45s 视频段数不足（5/7）
        duration_total = metrics.get("duration_seconds")
        try:
            dt = int(duration_total) if duration_total is not None else None
        except (TypeError, ValueError):
            dt = None
        if dt is not None:
            target = 5 if dt <= 35 else 7  # 30s 阈值 5 / 45s 阈值 7
            if actual_seg_count < target:
                warnings.append(
                    f"地板 4 段数下限 · 实际段数 {actual_seg_count} < {target}（{dt}s 视频应 ≥ {target} 段）"
                )
        # 自报数据 vs 实际比对（反自欺）
        if sg_self is not None:
            try:
                sg_int = int(sg_self)
                if abs(sg_int - actual_max_gap) > 1:
                    warnings.append(
                        f"地板 4 自报数据自欺 · LLM 自报 scene_change_max_gap_seconds={sg_int} 但 scenes 实际最长段 {actual_max_gap}s"
                    )
            except (TypeError, ValueError):
                pass
    else:
        # 无法从 scenes 解析（time_range 全空或格式坏）→ 退到 LLM 自报检查
        try:
            if sg_self is not None and float(sg_self) > 8:
                warnings.append(f"地板 4 · scene_change_max_gap_seconds={sg_self} 超过 8（无 scenes 数据反验，仅信自报）")
        except (TypeError, ValueError):
            pass
    if metrics.get("hardad_words_present") is True:
        warnings.append(
            "地板 7 · 检测到硬广敏感词（最/第一/绝对/治愈/功效/根治/限时/仅剩/抢购）"
        )
    if metrics.get("vague_words_present") is True:
        warnings.append(
            "通用强制 #2 · 检测到模糊词（很多/不少/大多数/众所周知/业内人士都说 "
            "— A3 大忌；M6 Reason-Why 严限）"
        )

    # === 品牌出现时机（前 5 秒禁）===
    bfa = metrics.get("brand_first_appearance_second")
    try:
        bfa_val = float(bfa) if bfa is not None else None
        if bfa_val is not None and bfa_val < 5:
            warnings.append(
                f"brand_first_appearance_second={bfa_val} 早于 5（前 5 秒禁品牌名）"
            )
    except (TypeError, ValueError):
        pass

    # === 传播动机单值（M8 Demo 可豁免）===
    if justification != "demonstration":
        target = (metrics.get("transmission_target") or "").strip()
        if not target or target.lower() == "all":
            warnings.append(
                "transmission_target 必须填具体的人（嫂子/同事/邻居/妈妈/伴侣 等），"
                "不能 all 或空"
            )
        elif any(c in target for c in ("或", "和", "/", "&", "、", ",", "，")):
            warnings.append(
                f"transmission_target={target!r} 含多目标连接词（或/和/、/, 等）"
                "— 必须单值。延时口碑传播理论强调'想让某个具体的人看到'"
            )

    # === M1 Slice of Life 专属 ===
    if relevance == "slice_of_life":
        if metrics.get("slice_setting_specificity_high") is not True:
            warnings.append(
                "M1 · slice_setting_specificity_high=false（场景必须具体到时间+地点+状态）"
            )
        if metrics.get("slice_brand_appearance_seconds_le_2") is not True:
            warnings.append(
                "M1 · slice_brand_appearance_seconds_le_2=false（Moment 里品牌画面停留 ≤ 2 秒）"
            )
        try:
            rdc = int(metrics.get("slice_routine_disclosure_count") or 0)
            if rdc < 2:
                warnings.append(
                    f"M1 · slice_routine_disclosure_count={rdc} 少于 2（Routine 必须 "
                    "≥ 2 个真实身份披露细节）"
                )
        except (TypeError, ValueError):
            pass

    # === M2 Problem-Naming 专属 ===
    if relevance == "problem_naming":
        if metrics.get("problem_naming_real_anxiety") is not True:
            warnings.append(
                "M2 · problem_naming_real_anxiety=false（命名的焦虑必须真实存在不能臆造）"
            )
        if metrics.get("problem_naming_cause_external_no_blame") is not True:
            warnings.append(
                "M2 · problem_naming_cause_external_no_blame=false（Cause 必须归因到"
                "外部因素，不能甩锅给用户 — 用户感觉被指责会反向远离品牌）"
            )
        if metrics.get("problem_naming_relief_directly_corresponds") is not True:
            warnings.append(
                "M2 · problem_naming_relief_directly_corresponds=false（Relief 必须跟 "
                "Cause 直接对应不能跑题）"
            )

    # === M3 Insider Reveal 专属 ===
    if justification == "insider_reveal":
        if metrics.get("insider_identity_verifiable") is not True:
            warnings.append("M3 · insider_identity_verifiable=false（内行身份必须真实可验证）")
        if metrics.get("insider_misconception_real") is not True:
            warnings.append(
                "M3 · insider_misconception_real=false（戳破的误区必须用户脑子里真实存在）"
            )
        if metrics.get("insider_standard_actionable") is not True:
            warnings.append(
                "M3 · insider_standard_actionable=false（判断标准必须具体可操作，不能抽象观点）"
            )

    # === M4 Origin Story 专属 ===
    if justification == "origin_story":
        if metrics.get("origin_skeptic_real") is not True:
            warnings.append("M4 · origin_skeptic_real=false（怀疑必须真实，不能假装）")
        if metrics.get("origin_trigger_specific_event") is not True:
            warnings.append(
                "M4 · origin_trigger_specific_event=false（Trigger 必须具体可还原 = "
                "时间+地点+人物）"
            )
        if metrics.get("origin_self_verification") is not True:
            warnings.append(
                "M4 · origin_self_verification=false（必须'我自己试'，不准'专家说''研究表明'）"
            )
        if metrics.get("origin_integration_concrete_scene") is not True:
            warnings.append(
                "M4 · origin_integration_concrete_scene=false（Integration 必须具体画面"
                "不是抽象总结）"
            )

    # === M5 Comparison Frame 专属 ===
    if justification == "comparison_frame":
        if metrics.get("comparison_visual_difference_clear") is not True:
            warnings.append(
                "M5 · comparison_visual_difference_clear=false（差异必须肉眼可见，"
                "不能只是口播差异）"
            )
        if metrics.get("comparison_no_competitor_disparage") is not True:
            warnings.append(
                "M5 · comparison_no_competitor_disparage=false（不能贬损同类竞品 — 平台规则）"
            )
        if metrics.get("comparison_verdict_user_self_drawn") is not True:
            warnings.append(
                "M5 · comparison_verdict_user_self_drawn=false（结论必须用户自己得出 — "
                "激活判断主权感）"
            )

    # === M6 Reason-Why 专属 ===
    if justification == "reason_why":
        if metrics.get("reason_why_fact_verifiable") is not True:
            warnings.append(
                "M6 · reason_why_fact_verifiable=false（事实必须可验证，禁模糊陈述）"
            )
        if metrics.get("reason_why_implication_user_lang") is not True:
            warnings.append(
                "M6 · reason_why_implication_user_lang=false（Implication 必须翻译成"
                "用户日常语言，禁行业术语堆砌）"
            )

    # === M7 Testimonial 专属 ===
    if justification == "testimonial":
        if metrics.get("testimonial_speaker_real_no_actor") is not True:
            warnings.append(
                "M7 · testimonial_speaker_real_no_actor=false（Speaker 必须真实非演员 — "
                "同期声 + 自然光 + 自然场景）"
            )
        if metrics.get("testimonial_experience_specific_detail") is not True:
            warnings.append(
                "M7 · testimonial_experience_specific_detail=false（Experience 必须有"
                "具体可信细节）"
            )
        if metrics.get("testimonial_continuation_present_tense") is not True:
            warnings.append(
                "M7 · testimonial_continuation_present_tense=false（Continuation 必须"
                "当下进行时画面，不是过去式回忆）"
            )

    # === M8 Demonstration 专属 ===
    if justification == "demonstration":
        if metrics.get("demo_action_complete_no_edit_tricks") is not True:
            warnings.append(
                "M8 · demo_action_complete_no_edit_tricks=false（Action 必须完整连贯，"
                "不剪辑造成魔术效果）"
            )
        if metrics.get("demo_reveal_repeatable_real") is not True:
            warnings.append(
                "M8 · demo_reveal_repeatable_real=false（Reveal 必须真实可重复，"
                "不能特殊条件极端展示）"
            )
        if metrics.get("demo_daily_no_lab_feel") is not True:
            warnings.append(
                "M8 · demo_daily_no_lab_feel=false（Daily 不能实验室感）"
            )

    # === M9 Authority Endorsement 专属 ===
    if justification == "authority_endorsement":
        if metrics.get("authority_real_verifiable") is not True:
            warnings.append(
                "M9 · authority_real_verifiable=false（权威必须真实可查，禁'业内人士'"
                "'专家'模糊表述）"
            )
        if metrics.get("authority_recognition_evidence_provided") is not True:
            warnings.append(
                "M9 · authority_recognition_evidence_provided=false（Recognition 必须"
                "有可验证证据 — 证书/报道/数据）"
            )
        if metrics.get("authority_translation_user_lang") is not True:
            warnings.append(
                "M9 · authority_translation_user_lang=false（Translation 必须翻译成"
                "用户语言，禁堆砌专业术语）"
            )

    # === 谨慎组合提示（不阻塞，仅 hint）===
    if relevance == "slice_of_life" and justification == "authority_endorsement":
        warnings.append(
            "★ 谨慎组合提示 · M1+M9 — 权威感容易破坏 Slice of Life 真实感，"
            "需把权威落地到生活细节里（路由 2.2 节）"
        )
    if relevance == "problem_naming" and justification == "origin_story":
        warnings.append(
            "★ 谨慎组合提示 · M2+M4 — 焦虑命名后讲长故事容易拖节奏，30s 内要小心控时（路由 2.2 节）"
        )
    if relevance == "slice_of_life" and justification == "reason_why":
        warnings.append(
            "★ 谨慎组合提示 · M1+M6 — Slice of Life 真实感跟反常识事实的'打断'感"
            "需要平衡（路由 2.2 节）"
        )

    # === image_prompt + 角色清单（W4-B 切片 14.4 phase D：脚本=单一创意源）===
    csc = metrics.get("character_sheet_count")
    try:
        csc_val = int(csc) if csc is not None else None
        if csc_val is None or csc_val < 1:
            warnings.append(
                f"phase D · character_sheet_count={csc} 至少 1（出场 ≥ 2 段的角色都要列；"
                "step 6.5 拿这清单先出锁脸定妆照）"
            )
        elif csc_val > 5:
            warnings.append(
                f"phase D · character_sheet_count={csc_val} 偏多（>5 个固定角色不利锁脸）"
            )
    except (TypeError, ValueError):
        warnings.append(f"phase D · character_sheet_count={csc!r} 不是整数")

    swip = metrics.get("scenes_with_image_prompt_count")
    stc = metrics.get("scenes_total_count")
    try:
        swip_val = int(swip) if swip is not None else None
        stc_val = int(stc) if stc is not None else None
        if swip_val is None or stc_val is None:
            warnings.append(
                f"phase D · scenes_with_image_prompt_count={swip}/scenes_total_count={stc} "
                "必填（每段都需 image_prompt 字段，step 6 直接喂图模型）"
            )
        elif swip_val != stc_val:
            warnings.append(
                f"phase D · scenes_with_image_prompt_count={swip_val} != scenes_total_count={stc_val} "
                "（每段 scene 都必须有 image_prompt，少一段都不行）"
            )
    except (TypeError, ValueError):
        warnings.append(f"phase D · scenes_with_image_prompt_count={swip!r}/scenes_total_count={stc!r} 不是整数")

    ipac = metrics.get("image_prompt_avg_chars")
    try:
        ipac_val = float(ipac) if ipac is not None else None
        if ipac_val is None or not (120 <= ipac_val <= 250):
            warnings.append(
                f"phase D · image_prompt_avg_chars={ipac} 不在 [120, 250] 区间"
            )
    except (TypeError, ValueError):
        warnings.append(f"phase D · image_prompt_avg_chars={ipac!r} 不是数字")

    spa = metrics.get("scene_product_appearance")
    if not isinstance(spa, list):
        warnings.append(
            f"phase D · scene_product_appearance={spa!r} 必须是 boolean 数组"
        )
    else:
        try:
            stc_val_for_spa = int(stc) if stc is not None else None
        except (TypeError, ValueError):
            stc_val_for_spa = None
        if stc_val_for_spa is not None and len(spa) != stc_val_for_spa:
            warnings.append(
                f"phase D · scene_product_appearance 长度 {len(spa)} != scenes_total_count {stc_val_for_spa}"
            )
        true_count = sum(1 for x in spa if x is True)
        if true_count == 0:
            warnings.append(
                "phase D · scene_product_appearance 全 false（每个脚本至少 1 段产品出场）"
            )

    return warnings


@tool_with_audit(mcp, require_approval=False)
async def generate_creative_pack(
    kind: str,
    sku_id: str | None = None,
    audience_record_id: str | None = None,
    audience_pack_id: str | None = None,
    extra_context: str | None = None,
) -> dict:
    """生成 6 类素材之一：视频软广/种草/收割 + 图文收割 + 主图 + 详情页（sku-pipeline step 5）。

    弹性挂：
    - 给 audience_pack_id：拉 pack + 关联的 record + matrix + sku（最完整链路）
    - 给 audience_record_id：拉 record + matrix + sku（绕过 step 4）
    - 都不给但给 sku_id：单 SKU 模式，prompt 里 audience/pack 段写"通用画像"

    kind 6 选 1：
    - `video_soft_ad`：A2 触动层视频，内容娱乐化软植入，30s 内
    - `video_planting`：A3 共鸣层视频，痛点共鸣 + 卖点植入，30-45s
    - `video_harvest`：A4 行动层视频，强卖点 + 强 CTA，15-25s
    - `graphic_harvest`：抖店/小红书收割图文，标题 + 5 段正文 + 配图 brief
    - `product_main_image`：电商主图设计 brief，5-9 张
    - `product_detail_page`：电商详情页设计 brief，8-12 段叙事长图

    Args:
        kind: 素材类型 6 选 1（必填）
        sku_id: 单 SKU 模式时必填；其他模式从 record/pack 反查
        audience_record_id: 推荐 — 从 SKU 人群池选 1 条
        audience_pack_id: 最完整 — 已跑过 step 4 圈包时挂上
        extra_context: 临时要求（"主推送礼场景""避开同行已饱和卖点"等）

    Returns:
        {ok, result: {script_md, script_id, kind, sku_id, audience_record_id?,
                      audience_pack_id?, matrix_run_id?}, trace, next_step_hint}
    """
    if kind not in pipeline_lineage.CREATIVE_KINDS:
        return {
            "ok": False,
            "error": f"非法 kind={kind}",
            "hint": f"必须 6 选 1：{list(pipeline_lineage.CREATIVE_KINDS)}",
        }

    pool = get_pool()

    # === 弹性反查 record / pack / matrix ===
    record = None
    pack = None
    matrix_run = None
    audience_run_id = None
    matrix_run_id = None

    if audience_pack_id:
        pack = await pipeline_lineage.get_audience_pack(audience_pack_id)
        if not pack:
            return {"ok": False, "error": "audience_pack_not_found", "audience_pack_id": audience_pack_id}
        sku_id = sku_id or pack.get("sku_id")
        audience_record_id = audience_record_id or pack.get("audience_record_id")
        audience_run_id = pack.get("audience_run_id")
        matrix_run_id = pack.get("matrix_run_id")

    if audience_record_id:
        record = await pipeline_lineage.get_audience_record(audience_record_id)
        if record:
            sku_id = sku_id or record.get("sku_id")
            audience_run_id = audience_run_id or record.get("audience_run_id")
            matrix_run_id = matrix_run_id or record.get("matrix_run_id")

    if matrix_run_id:
        matrix_run = await pipeline_lineage.get_matrix_run(matrix_run_id)

    if not sku_id:
        return {
            "ok": False,
            "error": "sku_id 缺失",
            "hint": "至少给 sku_id 或 audience_record_id 或 audience_pack_id 之一",
        }

    # === 拉 SKU ===
    sku = await pool.fetchrow(
        "SELECT id, name, category, price_min, price_max, specifications, "
        "owner_selling_points, owner_notes, platform_status "
        "FROM mvp_sku WHERE id = $1",
        sku_id,
    )
    if not sku:
        return {"ok": False, "error": "sku_not_found", "sku_id": sku_id}

    if sku["price_min"] is not None and sku["price_max"] is not None:
        if sku["price_min"] == sku["price_max"]:
            price_str = f"¥{sku['price_min']}"
        else:
            price_str = f"¥{sku['price_min']} - ¥{sku['price_max']}"
    else:
        price_str = "（信息不足）"

    sku_md = (
        f"- SKU id：{sku['id']}\n"
        f"- 品名：{sku['name']}\n"
        f"- 品类：{sku['category'] or '调味品'}\n"
        f"- 规格：{sku['specifications'] or '（无）'}\n"
        f"- 售价：{price_str}\n"
        f"- 老板自填卖点：{sku['owner_selling_points'] or '（无）'}\n"
        f"- 抖店平台状态：{sku['platform_status'] or '（unknown）'}\n"
    )

    # === 拼 matrix / audience / pack 段 ===
    matrix_md = (matrix_run.get("matrix_md") if matrix_run else None) or "（无 — 单 SKU 模式或未跑 step 2 卖点矩阵）"

    if record:
        layer_tags = " / ".join(record.get("layer_tags") or []) or "（无）"
        kb_chunk = (record.get("kb_chunk_text") or "").strip() or "（KB 原文缺）"
        reasons = record.get("match_reasons") or []
        reasons_md = "\n".join(f"  {i + 1}. {r}" for i, r in enumerate(reasons)) if reasons else "  （无）"
        audience_md = (
            f"- 人群名：{record.get('name')}\n"
            f"- KB 来源：{record.get('kb_doc') or '（无）'}{(' / ' + record['kb_section']) if record.get('kb_section') else ''}\n"
            f"- 圈层标签：{layer_tags}\n"
            f"- KB 原文画像：\n\n{kb_chunk}\n\n"
            f"- 5 条匹配理由：\n{reasons_md}\n"
        )
    else:
        audience_md = "（无 — 单 SKU 模式或未跑 step 3 人群匹配，按 SKU 通用画像出稿）"

    if pack:
        pack_md_full = (pack.get("pack_md") or "").strip()
        # 截 pack 头 800 字给 LLM 当上下文（避免 prompt 太大）
        pack_md_excerpt = pack_md_full[:800] + ("\n\n（…后略）" if len(pack_md_full) > 800 else "")
        audience_pack_summary = f"已跑 step 4 圈包（id={audience_pack_id}）摘要：\n\n{pack_md_excerpt}"
    else:
        audience_pack_summary = "（无 — 未跑 step 4 圈包；本素材直接用 audience 画像 + matrix 卖点出稿）"

    # === render prompt ===
    sys_template = f"creative_pack.{kind}.system"
    sys_msg = prompts.load(sys_template)
    user_msg = prompts.render(
        "creative_pack.user",
        kind=kind,
        kind_label=_KIND_LABELS.get(kind, kind),
        sku_md=sku_md,
        matrix_md=matrix_md.strip(),
        audience_md=audience_md.strip(),
        audience_pack_summary=audience_pack_summary.strip(),
        extra_context=(extra_context or "").strip() or "（无）",
    )
    final_prompt = sys_msg + "\n\n" + user_msg

    # === 调 LLM ===
    model_cfg = get_model_for_tool("generate_creative_pack")
    client = AIHubClient(timeout=300.0)
    resp = await client.chat(
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        temperature=model_cfg.get("temperature", 0.4),
        max_tokens=model_cfg.get("max_tokens", 8000),
        enforce_human_voice=True,
    )
    script_md = (
        ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
        or resp.get("text")
        or resp.get("content")
        or ""
    ).strip()

    # === 拉 metrics_json + 跑后端硬约束校验（反"LLM 自检装饰") ===
    # 同时 parse scenes 给 validator 用 time_range 实际算 max_gap（防 LLM 自报自欺）
    metrics = _extract_metrics_json(script_md)
    try:
        parsed_scenes = pipeline_lineage.parse_scenes_from_script_md(script_md, kind)
    except Exception:
        parsed_scenes = []
    if metrics is None:
        validation_warnings = ["⚠ LLM 没输出 metrics_json 代码块（或 JSON 解析失败），无法跑硬约束校验。改 prompt 或重跑。"]
    else:
        validation_warnings = _validate_creative_metrics(metrics, kind, scenes=parsed_scenes)

    # === 落库 ===
    script_id = await pipeline_lineage.save_creative_pack(
        sku_id=sku_id,
        kind=kind,
        script_md=script_md,
        audience_record_id=audience_record_id,
        audience_pack_id=audience_pack_id,
        audience_run_id=audience_run_id,
        matrix_run_id=matrix_run_id,
        hooks=[],   # phase C v1 先存整段 markdown，后续切片再加 hooks/scenes 解析
        scenes=[],
        extra_context=extra_context,
        model_provider=model_cfg.get("provider", "gemini"),
        model=model_cfg.get("model", "gemini-3-flash-preview"),
        final_prompt=final_prompt,
        cost_estimate="1 quota call (~3-6k tokens)",
    )

    next_hint = {
        "video_soft_ad": "step 6 拿主脚本里的分镜清单调 generate_image 出 5-7 张分镜图",
        "video_planting": "step 6 拿主脚本里的分镜清单调 generate_image 出 6-9 张分镜图",
        "video_harvest": "step 6 拿主脚本里的分镜清单调 generate_image 出 4-6 张分镜图",
        "graphic_harvest": "step 6 拿配图 brief 调 generate_image 出 4-6 张图文配图",
        "product_main_image": "step 6 拿主图 brief 调 generate_image 出 5-9 张主图",
        "product_detail_page": "step 6 拿详情页段落 brief 调 generate_image 出 8-12 段长图",
    }.get(kind, "step 6 调 generate_image 出图")

    result = {
        "ok": True,
        "result": {
            "script_md": script_md,
            "script_id": script_id,
            "kind": kind,
            "kind_label": _KIND_LABELS.get(kind, kind),
            "sku_id": sku_id,
            "audience_record_id": audience_record_id,
            "audience_pack_id": audience_pack_id,
            "matrix_run_id": matrix_run_id,
            "metrics": metrics,  # LLM 自报的结构化指标（None = 没输出 JSON）
            "validation_warnings": validation_warnings,  # 后端硬约束校验失败项；空 = 全过
        },
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt,
            params={
                "temperature": model_cfg.get("temperature", 0.4),
                "max_tokens": model_cfg.get("max_tokens", 8000),
                "kind": kind,
                "script_id": script_id,
                "validation_warnings_count": len(validation_warnings),
                "metrics_extracted": metrics is not None,
                "lineage": {
                    "sku_id": sku_id,
                    "audience_record_id": audience_record_id,
                    "audience_pack_id": audience_pack_id,
                    "matrix_run_id": matrix_run_id,
                },
            },
            cost_estimate="1 quota call (~3-6k tokens)",
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_image",
        suggested_args={"sku_id": sku_id, "script_id": script_id},
        human_text=next_hint,
    )
