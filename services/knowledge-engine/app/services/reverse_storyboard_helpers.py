"""reverse_storyboard_video 配套 helper:校验 + markdown 拼装。

不放 media.py 里是因为 media.py 已经 4000+ 行,这里独立便于复用 + 测试。
"""
from __future__ import annotations

import re
from typing import Any

METHODOLOGY_WHITELIST = {
    "Pixar",
    "Slice of Life",
    "CER",
    "Hero",
    "Empathy",
    "Cultural Tension",
    "Aspirational",
    "Mini-Doc",
}

COMPLETION_ESTIMATE_WHITELIST = {"<5%", "5-15%", ">15%"}

_PLACEHOLDER_RE = re.compile(r"\{(product|face)_ref_(\d+)\}")


def validate_reverse_result(
    result: dict[str, Any],
    video_duration_sec: float | None = None,
    expected_product_refs: int = 1,
    expected_face_refs: int = 1,
) -> tuple[list[str], list[str]]:
    """校验 LLM 返回的 reverse storyboard JSON。

    Returns:
        (errors, warnings) — errors 非空 = 校验失败,tool 应返 ok=False
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── 顶层结构 ──
    for key in ("scenes", "storyboard_for_image_set", "storyboard_for_video_segments",
                "storyboard_for_video_long", "placeholders", "methodology_guess",
                "hook_analysis", "meta"):
        if key not in result:
            errors.append(f"顶层缺字段: {key}")
    if errors:
        return errors, warnings

    scenes = result.get("scenes") or []
    if not isinstance(scenes, list) or len(scenes) == 0:
        errors.append("scenes 不是 list 或为空")
        return errors, warnings

    # ── scene 字段完整性 ──
    # structured 字段缺 = errors(硬错,反推不可用)
    # prompts 包字段缺 = warnings(顶层 storyboard_for_image_set/video_segments/video_long
    #   已经覆盖同一信息,scene 级重复输出只是额外冗余,LLM 跳过没问题)
    scene_field_groups = {
        "structured": [
            "idx", "time_range", "duration_sec",
            "subject", "action", "environment",
            "shot_type", "camera_motion",
            "lighting", "style_keywords", "mood_keywords", "color_palette",
            "dialogue", "voiceover_guess", "sfx_ambient", "on_screen_text",
            "first_frame_hint", "last_frame_hint",
            "negative_hints",
        ],
        "prompts": ["prompt_for_image", "prompt_for_video_i2v", "prompt_for_video_t2v"],
    }
    scenes_missing_prompts: list[int] = []
    for i, s in enumerate(scenes, 1):
        for f in scene_field_groups["structured"]:
            if f not in s:
                errors.append(f"scene[{i}] 缺字段 {f}")
        # prompts 字段降级为 warning,只汇总不阻断
        missing = [f for f in scene_field_groups["prompts"] if f not in s]
        bad = [f for f in scene_field_groups["prompts"]
               if f in s and (not isinstance(s[f], dict) or not s[f].get("zh") or not s[f].get("en"))]
        if missing or bad:
            scenes_missing_prompts.append(i)
    if scenes_missing_prompts:
        warnings.append(
            f"scene 级 prompt 包字段(prompt_for_image / prompt_for_video_i2v / prompt_for_video_t2v) "
            f"在 {len(scenes_missing_prompts)} 段缺/不全(seg {scenes_missing_prompts[:5]}...); "
            f"已用顶层 storyboard_for_image_set / video_segments / video_long 覆盖,不影响产物可用"
        )
    if errors:
        return errors, warnings

    # ── scene 时间不重叠 + 总时长 ──
    for i in range(len(scenes) - 1):
        cur_end = scenes[i]["time_range"][1]
        nxt_start = scenes[i + 1]["time_range"][0]
        if cur_end > nxt_start + 0.5:
            errors.append(f"scene[{i+1}] end={cur_end} > scene[{i+2}] start={nxt_start} (重叠)")
    total_dur = sum(s.get("duration_sec", 0) for s in scenes)
    if video_duration_sec and abs(total_dur - video_duration_sec) > 1.0:
        warnings.append(
            f"scene 总时长 {total_dur:.1f}s 跟视频时长 {video_duration_sec:.1f}s 差超 1s"
        )

    # ── 占位符语法 + 数量 ──
    placeholders = result.get("placeholders") or {}
    product_keys = sorted([k for k in placeholders if k.startswith("product_ref_")])
    face_keys = sorted([k for k in placeholders if k.startswith("face_ref_")])
    if len(product_keys) != expected_product_refs:
        warnings.append(
            f"期望 product_ref_count={expected_product_refs}, "
            f"LLM 输出 {len(product_keys)} 个 ({product_keys})"
        )
    if len(face_keys) != expected_face_refs:
        warnings.append(
            f"期望 face_ref_count={expected_face_refs}, "
            f"LLM 输出 {len(face_keys)} 个 ({face_keys})"
        )
    # 扫所有 scene 里出现的占位符 vs placeholders 字典里定义的
    referenced: set[str] = set()
    for s in scenes:
        for field in ("subject", "action", "environment",
                      "first_frame_hint", "last_frame_hint",
                      "prompt_for_image", "prompt_for_video_i2v", "prompt_for_video_t2v"):
            v = s.get(field)
            if isinstance(v, dict):
                for sub in ("zh", "en"):
                    text = v.get(sub, "")
                    for m in _PLACEHOLDER_RE.finditer(text):
                        referenced.add(f"{m.group(1)}_ref_{m.group(2)}")
            elif isinstance(v, str):
                for m in _PLACEHOLDER_RE.finditer(v):
                    referenced.add(f"{m.group(1)}_ref_{m.group(2)}")
    defined = set(placeholders.keys())
    if referenced - defined:
        warnings.append(f"scene 里引用了未在 placeholders 定义的占位: {sorted(referenced - defined)}")
    if defined - referenced - set([k for k in defined if any(s in k for s in ('description', 'appearance'))]):
        unused = defined - referenced
        if unused:
            warnings.append(f"placeholders 定义了但 scene 没用: {sorted(unused)}")

    # ── methodology + hook ──
    mg = result.get("methodology_guess") or {}
    if mg.get("primary") not in METHODOLOGY_WHITELIST:
        warnings.append(
            f"methodology_guess.primary={mg.get('primary')!r} 不在白名单 {METHODOLOGY_WHITELIST}"
        )
    ha = result.get("hook_analysis") or {}
    if ha.get("completion_estimate") not in COMPLETION_ESTIMATE_WHITELIST:
        warnings.append(
            f"hook_analysis.completion_estimate={ha.get('completion_estimate')!r} "
            f"不在白名单 {COMPLETION_ESTIMATE_WHITELIST}"
        )

    # ── 3 类全局产物非空 ──
    sis = result.get("storyboard_for_image_set") or {}
    if not sis.get("prompt_zh") or not sis.get("prompt_en"):
        errors.append("storyboard_for_image_set.prompt_zh/en 缺")
    svs = result.get("storyboard_for_video_segments") or {}
    segs = svs.get("segments") or []
    if not isinstance(segs, list) or len(segs) == 0:
        errors.append("storyboard_for_video_segments.segments 为空")
    svl = result.get("storyboard_for_video_long") or {}
    if not svl.get("prompt_zh"):
        errors.append("storyboard_for_video_long.prompt_zh 缺")

    return errors, warnings


def _to_midjourney_prompt(en: str) -> str:
    """en prompt → MJ v7 推荐 flag 版(--ar 9:16 --v 7 --style raw --s 50)。"""
    base = (en or "").strip().rstrip('., \n')
    if not base:
        return ""
    return f"{base} --ar 9:16 --v 7 --style raw --s 50"


def _to_veo_timestamp(scenes: list[dict[str, Any]]) -> str:
    """多 scene → Veo 3.1 官方 timestamp 多镜头 + with audio。

    audio cue 检测:如果 t2v.en 末尾已经有 'With the sound of'(LLM 按新版 prompt
    自己加了),就不重复加;否则用 sfx_ambient 补一个。
    """
    lines: list[str] = []
    for s in scenes:
        tr = s.get("time_range") or [0, 0]
        try:
            start_s, end_s = float(tr[0]), float(tr[1])
        except (TypeError, ValueError, IndexError):
            continue
        ts = (f"[{int(start_s // 60):02d}:{int(start_s % 60):02d}-"
              f"{int(end_s // 60):02d}:{int(end_s % 60):02d}]")
        pt = ((s.get("prompt_for_video_t2v") or {}).get("en") or "").strip()
        if not pt:
            pt = " ".join(
                str(s.get(k) or "") for k in ("subject", "action", "environment")
            ).strip()
        line = f"{ts} {pt}"
        # 已经含 audio cue 就不重复加(LLM 按新版 system prompt 自己会加)
        if "with the sound of" not in pt.lower():
            audio = (s.get("sfx_ambient") or "").strip()
            if audio:
                line += f" With the sound of {audio}."
        lines.append(line)
    return "\n\n".join(lines)


def _adapt_zh_with_suffix(zh: str, suffix: str = "") -> str:
    """国产平台中文 prompt 加平台偏好后缀。"""
    if not zh:
        return ""
    base = zh.rstrip("。.,, \n")
    return f"{base}。{suffix}" if suffix else zh


def _adapt_en_with_suffix(en: str, suffix: str = "") -> str:
    """国外平台英文 prompt 加平台偏好后缀。"""
    if not en:
        return ""
    base = en.rstrip(". ,\n")
    return f"{base}. {suffix}" if suffix else en


def _adapt_hailuo_video(en: str, camera_motion: str) -> str:
    """Hailuo 02: 开头加 [Camera motion: xxx]。"""
    if not en:
        return ""
    if en.lstrip().startswith("[Camera"):
        return en
    cam = (camera_motion or "static shot").strip()
    return f"[Camera motion: {cam}] {en}"


def _adapt_pika_video(en: str, dialogue: str) -> str:
    """Pika 2.5: 末尾加 lipsync hint。"""
    if not en:
        return ""
    base = en.rstrip(". ")
    if dialogue:
        return f'{base}. Lipsync to dialogue: "{dialogue}".'
    return en


def _first_image_zh(result: dict[str, Any]) -> str:
    """拿全局产物 1 的中文 prompt 第 1 行(去 '1. ' 前缀)作展示样本。"""
    sis_zh = ((result.get("storyboard_for_image_set") or {}).get("prompt_zh") or "").strip()
    if not sis_zh:
        return ""
    first = sis_zh.split("\n")[0].strip()
    if first[:3] in ("1. ", "1.、", "1、 "):
        first = first[3:].strip()
    return first


def _first_image_en(result: dict[str, Any]) -> str:
    sis_en = ((result.get("storyboard_for_image_set") or {}).get("prompt_en") or "").strip()
    if not sis_en:
        return ""
    first = sis_en.split("\n")[0].strip()
    if first[:3] in ("1. ", "1, "):
        first = first[3:].strip()
    return first


def _first_video_zh(result: dict[str, Any]) -> str:
    """全局产物 3 中文 t2v 第 1 段(去 [00:00-00:0X] timestamp)。"""
    svl_zh = ((result.get("storyboard_for_video_long") or {}).get("prompt_zh") or "").strip()
    if not svl_zh:
        return ""
    first_section = svl_zh.split("\n\n")[0].strip()
    # 去掉前面 [00:00-00:0X]
    import re as _re
    cleaned = _re.sub(r"^\[\d{2}:\d{2}-\d{2}:\d{2}\]\s*", "", first_section)
    return cleaned


def _first_video_en(result: dict[str, Any]) -> str:
    svl_en = ((result.get("storyboard_for_video_long") or {}).get("prompt_en") or "").strip()
    if not svl_en:
        return ""
    first_section = svl_en.split("\n\n")[0].strip()
    import re as _re
    cleaned = _re.sub(r"^\[\d{2}:\d{2}-\d{2}:\d{2}\]\s*", "", first_section)
    return cleaned


def _first_scene_field(result: dict[str, Any], field: str) -> str:
    scenes = result.get("scenes") or []
    if not scenes:
        return ""
    return (scenes[0].get(field) or "").strip()


def _i2v_first_segment(result: dict[str, Any], lang: str = "zh") -> tuple[str, str, str]:
    """i2v 第 1 段:返(first_frame_prompt, last_frame_prompt, motion_prompt)。"""
    svs = result.get("storyboard_for_video_segments") or {}
    segs = svs.get("segments") or []
    if not segs:
        return "", "", ""
    s = segs[0]
    if lang == "zh":
        return (s.get("first_frame_prompt_zh") or "",
                s.get("last_frame_prompt_zh") or "",
                s.get("motion_prompt_zh") or "")
    return (s.get("first_frame_prompt_en") or "",
            s.get("last_frame_prompt_en") or "",
            s.get("motion_prompt_en") or "")


def _render_model_playbook(result: dict[str, Any]) -> list[str]:
    """生成「喂回 9 厂商操作手册」段。

    按厂商(vendor)分组:每段含图模型 + 视频模型配套链路 + 网站 + 适配 prompt
    + step-by-step 操作。

    9 厂商:即梦 / GPT / Gemini / Midjourney / Runway / 可灵 / Pika / 海螺 / Flux

    每段输出"第 1 个 scene 的适配 prompt"作样本,完整 prompt 老板从上面 3 个
    全局产物里 copy(避免重复 N 倍)。
    """
    scenes = result.get("scenes") or []
    img_zh = _first_image_zh(result)
    img_en = _first_image_en(result)
    vid_zh = _first_video_zh(result)
    vid_en = _first_video_en(result)
    i2v_first_zh, i2v_last_zh, i2v_motion_zh = _i2v_first_segment(result, "zh")
    i2v_first_en, i2v_last_en, i2v_motion_en = _i2v_first_segment(result, "en")
    first_camera = _first_scene_field(result, "camera_motion")
    first_dialogue = _first_scene_field(result, "dialogue")

    sis = result.get("storyboard_for_image_set") or {}
    sis_en = (sis.get("prompt_en") or "").strip()
    mj_lines: list[str] = []
    if sis_en:
        for line in sis_en.split("\n"):
            line = line.strip()
            if not line:
                continue
            mj_lines.append(_to_midjourney_prompt(line))
    mj_block = "\n".join(mj_lines)
    veo_block = _to_veo_timestamp(scenes) if scenes else ""

    lines: list[str] = []
    lines.append("---")
    lines.append("")
    lines.append("## 🚀 按 9 厂商分组的操作手册(图模型 → 视频模型配套)")
    lines.append("")
    lines.append("> 上面 3 个全局产物是**通用 prompt 包**。下面按 9 家主流 AI 厂商分段,")
    lines.append("> 每段告诉你该厂商**图模型 → 视频模型**的配套链路 + 网站 + **已经按该厂商协议适配过的 prompt 样本**(第 1 个 scene)。")
    lines.append("> 完整 N 个 scene 的 prompt 老板从「全局产物 1/2/3」里直接 copy 同样套路即可。")
    lines.append("")
    lines.append("**索引**(点击跳):")
    lines.append("[即梦](#1-即梦-字节-) | [GPT/OpenAI](#2-gptopenai-) | [Gemini/Google](#3-geminigoogle-) | "
                 "[Midjourney](#4-midjourney-) | [Runway](#5-runway-) | "
                 "[可灵](#6-可灵-快手-) | [Pika](#7-pika-) | [海螺](#8-海螺-minimax-) | [Flux](#9-flux-bfl-)")
    lines.append("")

    # ───────── 厂商 1: 即梦 (字节) ─────────
    lines.append("### 1. 即梦 (字节) ⭐ 国产首选")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | Seedream 4.5 / 4.0 lite |")
    lines.append("| **视频模型** | Seedance 2.0 pro |")
    lines.append("| **网站** | https://jimeng.jianying.com (即梦 web) / https://www.volcengine.com/product/aigc-ark (火山方舟 API) |")
    lines.append("| **偏好语言** | 中文 |")
    lines.append("| **配套链路** | Seedream 出图 → Seedance 2.0 i2v 用图当首帧出视频(全链路中文) |")
    lines.append("| **价格** | ~¥0.5/张图 + ~¥3-15/段视频(对比国外 1/3) |")
    lines.append("")
    lines.append("**步骤 1 · Seedream 出图**(中文 prompt + 国产偏好后缀):")
    lines.append("```")
    lines.append(_adapt_zh_with_suffix(img_zh, "真人感, 纪实风格, 烟火气, 浅景深, 9:16 竖版"))
    lines.append("```")
    lines.append("操作:即梦 web → 图像生成 → 粘上面 → 画幅 9:16 → 上传角色/产品参考图 → 出 N 张")
    lines.append("")
    lines.append("**步骤 2 · Seedance 出视频**(中文 i2v):")
    lines.append("```")
    lines.append(_adapt_zh_with_suffix(i2v_motion_zh, "运镜平稳缓慢, 真人感, 9:16 竖版"))
    lines.append("```")
    lines.append("操作:选步骤 1 的某张图 → 视频生成 i2v → 粘上面 motion → 选 5-10s → 出视频")
    lines.append("")
    lines.append("**注意**:Seedance pro 单段 ≤10s,>10s 切多段;t2v 模式也支持(质量比 i2v 略弱)。")
    lines.append("")

    # ───────── 厂商 2: GPT / OpenAI ─────────
    lines.append("### 2. GPT/OpenAI 🎯 t2v 强")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | ChatGPT-Image-2 (DALL-E 3 后继) / GPT-image-1.5 |")
    lines.append("| **视频模型** | Sora 2 |")
    lines.append("| **网站** | https://chat.openai.com (Plus/Pro) / https://sora.com (单独 Sora 2 入口) |")
    lines.append("| **偏好语言** | 英文(GPT 内部会改写优化,中文也吃) |")
    lines.append("| **配套链路** | ChatGPT 出图(同对话上传 ref)→ Sora 2 出视频(同账号) |")
    lines.append("| **价格** | Plus $20/月含基础额度;Pro $200/月含 Sora Pro |")
    lines.append("")
    lines.append("**步骤 1 · ChatGPT-Image-2 出图**(英文长描述 + 多 ref):")
    lines.append("```")
    lines.append(img_en)
    lines.append("```")
    lines.append("操作:ChatGPT 对话框粘上面 + 上传 1-4 张参考图(face/product/scene)→ 网页右下选 `Portrait 9:16`")
    lines.append("")
    lines.append("**步骤 2 · Sora 2 出视频**(英文 t2v 长 timestamp):")
    lines.append("```")
    lines.append(_adapt_en_with_suffix(vid_en, "Cinematic motion, realistic physics, vertical 9:16."))
    lines.append("```")
    lines.append("操作:sora.com → 粘整段「全局产物 3 英文版」timestamp → 选 9:16 → 时长 4/8/12/20s → 选 Pro quality")
    lines.append("")
    lines.append("**注意**:Sora 2 强调 motion + physics + camera,prompt 里已经有 `natural gravity, fluid motion`。")
    lines.append("")

    # ───────── 厂商 3: Gemini / Google ─────────
    lines.append("### 3. Gemini/Google ⭐ 推荐高质量复刻 + 原生 audio")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | Imagen 4 (摄影写实最强) + Nano Banana / Gemini 2.5 Flash Image (编辑图) |")
    lines.append("| **视频模型** | Veo 3.1 (t2v + i2v 双模式,**原生 audio 生成**) |")
    lines.append("| **网站** | https://aistudio.google.com / https://labs.google.com/flow / https://labs.google.com/fx/tools/image-fx |")
    lines.append("| **偏好语言** | 英文 |")
    lines.append("| **配套链路** | Imagen 4 出图 → Veo 3.1 i2v 用图驱动 motion + audio cue 一并生成 |")
    lines.append("| **特长** | Veo 3.1 是当下唯一 **prompt 写 `With the sound of ...` 直接生成音频** 的视频模型 |")
    lines.append("")
    lines.append("**步骤 1 · Imagen 4 出图**(英文 + 摄影术语):")
    lines.append("```")
    lines.append(_adapt_en_with_suffix(img_en, "Shot on 35mm film, shallow depth of field, photojournalism style."))
    lines.append("```")
    lines.append("操作:aistudio.google.com → Imagen 4 → 粘 → Aspect Ratio 9:16 → 出图")
    lines.append("")
    lines.append("**步骤 2 · Veo 3.1 出视频**(英文 timestamp + audio cue,自动 dedupe):")
    if veo_block:
        lines.append("```")
        lines.append(veo_block)
        lines.append("```")
        lines.append("操作:labs.google.com/flow → 粘上面整段 timestamp → 单段 8s 上限 → 9:16 → audio 自动生成")
    else:
        lines.append("(无 scene 数据,无法生成 timestamp 版本)")
    lines.append("")
    lines.append("**注意**:Veo 3.1 单段 8s 硬上限,>8s 需多段拼 (i2v 模式下,本段尾帧 = 下段首帧 串场)。")
    lines.append("")

    # ───────── 厂商 4: Midjourney ─────────
    lines.append("### 4. Midjourney")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | MJ v7 |")
    lines.append("| **视频模型** | (无,串外部 — 出图后扔 Runway/Veo i2v) |")
    lines.append("| **网站** | https://discord.com (主) + https://midjourney.com (网页) |")
    lines.append("| **偏好语言** | 英文 |")
    lines.append("| **必带 flag** | `--ar 9:16 --v 7 --style raw --s 50` |")
    lines.append("| **价格** | $10-60/月 |")
    lines.append("")
    lines.append("**步骤 · MJ v7 出图**(英文 + 自动 flag,Discord 直接粘):")
    if mj_block:
        lines.append("```")
        lines.append(mj_block)
        lines.append("```")
        lines.append("操作:Discord MJ bot → `/imagine prompt: <粘任意一行>` → 出 4 张 → upscale/variation")
    lines.append("")
    lines.append("**锁脸锁场景**:在每行末尾再加 `--cref <角色定妆照 URL>` + `--sref <场景参考图 URL>`(URL 上传到 Discord 后右键复制)")
    lines.append("")
    lines.append("**配套出视频**:MJ 自家不出视频,可以下载图 → 上传 Runway Gen-4 / Veo 3.1 i2v / Seedance i2v 出动效。")
    lines.append("")

    # ───────── 厂商 5: Runway ─────────
    lines.append("### 5. Runway")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | Frames (Runway 文生图,2025 新出) |")
    lines.append("| **视频模型** | Gen-4 (强项: References 多参考图一致性) |")
    lines.append("| **网站** | https://runwayml.com |")
    lines.append("| **偏好语言** | 英文 |")
    lines.append("| **配套链路** | Frames 出图 → Gen-4 i2v (绑定 References 锁角色/场景/物体) |")
    lines.append("| **价格** | $15-95/月 |")
    lines.append("")
    lines.append("**步骤 1 · Frames 出图**:")
    lines.append("```")
    lines.append(img_en)
    lines.append("```")
    lines.append("操作:runwayml.com → Frames → 粘 → 9:16")
    lines.append("")
    lines.append("**步骤 2 · Gen-4 出视频**:")
    lines.append("```")
    lines.append(_adapt_en_with_suffix(vid_en, "Use 3 reference images: [1] character face, [2] scene/environment, [3] key prop/object."))
    lines.append("```")
    lines.append("操作:Gen-4 → 粘 + 上传 3 张 References → 5s/10s → 9:16 → 出视频")
    lines.append("")
    lines.append("**强项**:Gen-4 的 References 是当下最强的多 ref 一致性视频模型。")
    lines.append("")

    # ───────── 厂商 6: 可灵 / Kling (快手) ─────────
    lines.append("### 6. 可灵 (快手)")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | Kolors (虚谷光年,可灵旗下) |")
    lines.append("| **视频模型** | Kling 2.1 (5s 标准 / 10s 专业) |")
    lines.append("| **网站** | https://klingai.com / https://kling.kuaishou.com |")
    lines.append("| **偏好语言** | 中文 |")
    lines.append("| **配套链路** | Kolors 出图 → Kling 2.1 i2v + 多 reference 锁脸/场景/道具 |")
    lines.append("| **特长** | 国产模型里多 reference 最强 + 价格便宜 |")
    lines.append("")
    lines.append("**步骤 1 · Kolors 出图**:")
    lines.append("```")
    lines.append(_adapt_zh_with_suffix(img_zh, "纪实风格, 真人感, 浅景深, 9:16 竖版"))
    lines.append("```")
    lines.append("操作:klingai.com → 图像生成 → 粘 + 上传参考图 → 9:16")
    lines.append("")
    lines.append("**步骤 2 · Kling 2.1 出视频**(中文 + 多 reference):")
    lines.append("```")
    lines.append(_adapt_zh_with_suffix(vid_zh, "镜头平稳缓慢, 真人感, 9:16 竖版。上传 3 张参考图: 角色定妆 + 场景 + 道具。"))
    lines.append("```")
    lines.append("操作:klingai.com → 视频生成 → 粘 + 上传 3 张参考图 → 5s/10s")
    lines.append("")

    # ───────── 厂商 7: Pika ─────────
    lines.append("### 7. Pika")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | (主要做视频,可串 MJ/Imagen 来的图) |")
    lines.append("| **视频模型** | Pika 2.5 |")
    lines.append("| **网站** | https://pika.art |")
    lines.append("| **偏好语言** | 英文 |")
    lines.append("| **特长** | **lipsync 最强** — 上传音频文件 / 文字台词 → 角色嘴形对你的台词 |")
    lines.append("")
    lines.append("**步骤 · Pika 2.5 出视频**(英文 t2v + lipsync):")
    lines.append("```")
    lines.append(_adapt_pika_video(vid_en, first_dialogue))
    lines.append("```")
    lines.append("操作:pika.art → 粘 prompt → 上传你的台词音频文件(MP3/WAV)→ 选 character → 出视频")
    lines.append("")
    lines.append("**适合**:你自己录台词 → Pika 让 AI 角色对口型(婆媳/婚姻这种台词驱动的题材最适合)")
    lines.append("")

    # ───────── 厂商 8: 海螺 / Hailuo (MiniMax) ─────────
    lines.append("### 8. 海螺 (MiniMax)")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | Hailuo Image (新出,主力还是视频) |")
    lines.append("| **视频模型** | Hailuo 02 / 02-pro |")
    lines.append("| **网站** | https://hailuoai.video |")
    lines.append("| **偏好语言** | 英文/中文 |")
    lines.append("| **特长** | prompt 开头加 **`[Camera motion: xxx]`** 标签格式驱动运镜 |")
    lines.append("")
    lines.append("**步骤 · Hailuo 02 出视频**(英文 + [Camera] 标签):")
    lines.append("```")
    lines.append(_adapt_hailuo_video(vid_en, first_camera))
    lines.append("```")
    lines.append("操作:hailuoai.video → 粘 → 6s(标准)/ 10s(pro)→ 9:16")
    lines.append("")

    # ───────── 厂商 9: Flux (BFL) ─────────
    lines.append("### 9. Flux (BFL)")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| **图模型** | Flux 1.1 Pro (主图模型) + Flux Kontext (编辑现有图) |")
    lines.append("| **视频模型** | (Flux video 较新,2025 Q4 出但还不主流) |")
    lines.append("| **网站** | https://replicate.com/black-forest-labs/flux-1.1-pro / https://fal.ai / https://bfl.ai |")
    lines.append("| **偏好语言** | 英文 |")
    lines.append("| **特长** | 写实摄影感 + Kontext 模式可 `prompt + 一张图` 做局部编辑 |")
    lines.append("")
    lines.append("**步骤 · Flux 1.1 Pro 出图**(英文 tag 风格):")
    lines.append("```")
    lines.append(img_en)
    lines.append("```")
    lines.append("操作:replicate.com → flux-1.1-pro → API 参数 `aspect_ratio:'9:16'` + `safety_tolerance:5` → 出图")
    lines.append("")
    lines.append("**Kontext 模式**:上传 1 张原图 + 一句话描述要改成啥(如 `Change kitchen lighting to warmer tone`)")
    lines.append("")

    # ───────── 推荐组合 ─────────
    lines.append("---")
    lines.append("")
    lines.append("### 🎯 按你想要啥推荐厂商组合")
    lines.append("")
    lines.append("| 想要 | 推荐厂商 + 模型 | 走法 |")
    lines.append("|---|---|---|")
    lines.append("| **1:1 复刻 + 原生 audio** | Gemini Veo 3.1 i2v | Imagen 4 出图 → Veo 3.1 i2v(已含 audio cue 自动生成音频) |")
    lines.append("| **中文链路 + 便宜** | 即梦 (Seedream + Seedance) | 全中文 prompt,从头到尾不用翻英文 |")
    lines.append("| **多角色锁脸** | Runway (Gen-4) 或 可灵 (Kling 2.1) | 3 张 reference image 锁角色+场景+物体 |")
    lines.append("| **AI 角色对台词 lipsync** | Pika 2.5 | 你录台词音频 → AI 嘴形对你的录音 |")
    lines.append("| **强物理 + cinematic** | OpenAI Sora 2 | t2v 一把梭出整段 ≤20s |")
    lines.append("| **单张高质感分镜** | Midjourney v7 | 自动 flag 版 Discord 直接 /imagine |")
    lines.append("| **编辑现有图** | Gemini Nano Banana 或 Flux Kontext | 上传原图 + prompt 改局部 |")
    lines.append("")

    # ───────── 一句话原则 ─────────
    lines.append("### 💡 一句话原则")
    lines.append("")
    lines.append("- **国产链路全中文**:即梦(Seedream + Seedance)/ 可灵(Kolors + Kling)— 理解准 + 国产人脸 + 价格 1/3")
    lines.append("- **国外链路全英文**:GPT(ChatGPT-Image + Sora 2)/ Gemini(Imagen + Veo)/ MJ / Runway / Flux — 质量稳")
    lines.append("- **占位符 `{face_ref_1}` / `{product_ref_1}` 喂模型前替换**成你的真实图 URL 或上传文件")
    lines.append("- **i2v 比 t2v 稳**:图像模型出准确首帧 → 视频模型驱动 motion(误差比 t2v 一把梭少)")
    lines.append("- **Veo 3.1 唯一原生 audio**:其他视频模型出哑片,需后期配音/配 BGM")
    lines.append("- **Sora 2 强物理**:重力/惯性/材质自然,适合复杂运动场景")
    lines.append("- **Pika 强 lipsync**:有具体台词 + 想要 AI 角色对你录音的话只能选 Pika")
    lines.append("")

    return lines


def render_markdown_report(result: dict[str, Any], meta: dict[str, Any]) -> str:
    """把 result 渲染成给老板眼看的 markdown 报告(带 3 个全局产物的代码块)。"""
    scenes = result.get("scenes") or []
    placeholders = result.get("placeholders") or {}
    mg = result.get("methodology_guess") or {}
    ha = result.get("hook_analysis") or {}
    sis = result.get("storyboard_for_image_set") or {}
    svs = result.get("storyboard_for_video_segments") or {}
    svl = result.get("storyboard_for_video_long") or {}

    lines: list[str] = []
    lines.append(f"# 反推故事板报告")
    lines.append("")
    lines.append(f"- 视频: `{meta.get('video_path', '?')}`")
    lines.append(f"- 时长: {meta.get('video_duration_sec', '?')}s")
    lines.append(f"- 模型: `{meta.get('model_used', '?')}`")
    lines.append(f"- 分镜数: {len(scenes)}")
    lines.append(f"- 方法论: **{mg.get('primary', '?')}** (备选 {mg.get('alternative', '?')})")
    lines.append(f"- 完播估算: **{ha.get('completion_estimate', '?')}**")
    lines.append("")

    # ── 警告 ──
    warnings = meta.get("warnings") or []
    if warnings:
        lines.append("## ⚠ 警告")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    # ── 占位符表 ──
    if placeholders:
        lines.append("## 占位符字典")
        lines.append("")
        lines.append("| key | 中文描述 | 英文描述 | 出现 scene |")
        lines.append("|---|---|---|---|")
        for k in sorted(placeholders.keys()):
            p = placeholders[k]
            scenes_str = ",".join(str(x) for x in (p.get("appearance_scenes") or []))
            # 兼容旧版 description 单字段 + 新版 description_zh/description_en 双字段
            desc_zh = p.get("description_zh") or p.get("description", "?")
            desc_en = p.get("description_en", "—")
            lines.append(f"| `{{{k}}}` | {desc_zh} | {desc_en} | {scenes_str} |")
        lines.append("")

    # ── 钩子 ──
    lines.append("## 钩子分析")
    lines.append("")
    lines.append(f"- 前 3s: {ha.get('first_3s', '?')}")
    lines.append(f"- 估完播: {ha.get('completion_estimate', '?')}")
    if ha.get("why_it_might_work"):
        lines.append(f"- 工作原因:")
        for r in ha["why_it_might_work"]:
            lines.append(f"  - {r}")
    lines.append("")

    # ── 方法论 ──
    lines.append("## 方法论判断")
    lines.append("")
    lines.append(f"- 主要: **{mg.get('primary', '?')}**")
    if mg.get("evidence"):
        lines.append(f"- 证据:")
        for e in mg["evidence"]:
            lines.append(f"  - {e}")
    lines.append(f"- 备选: {mg.get('alternative', '?')}")
    lines.append("")

    # ── 分镜表 ──
    lines.append("## 分镜表")
    lines.append("")
    lines.append("| # | 时间 | 时长 | 主体 | 镜头/运动 | 光影/风格 | 字幕 |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in scenes:
        tr = s.get("time_range", [0, 0])
        tr_str = f"{tr[0]:.1f}-{tr[1]:.1f}"
        camera = f"{s.get('shot_type', '?')} / {s.get('camera_motion', '?')}"
        light_style = f"{s.get('lighting', '?')[:20]} / {','.join((s.get('style_keywords') or [])[:2])}"
        lines.append(
            f"| {s.get('idx', '?')} | {tr_str}s | {s.get('duration_sec', '?')}s | "
            f"{(s.get('subject') or '?')[:30]} | {camera} | {light_style} | "
            f"{(s.get('on_screen_text') or '')[:15]} |"
        )
    lines.append("")

    # ── 全局产物 1: 图像组 ──
    lines.append("## 全局产物 1 — 故事板分镜图组（喂图像模型）")
    lines.append("")
    lines.append(f"> {sis.get('usage', '')}")
    lines.append("")
    lines.append("### 中文版")
    lines.append("```")
    lines.append(sis.get("prompt_zh", "(空)"))
    lines.append("```")
    lines.append("")
    lines.append("### 英文版")
    lines.append("```")
    lines.append(sis.get("prompt_en", "(empty)"))
    lines.append("```")
    lines.append("")

    # ── 全局产物 2: i2v 段组 ──
    lines.append("## 全局产物 2 — i2v 视频段组（喂 Veo3.1 / Seedance i2v）")
    lines.append("")
    lines.append(f"> {svs.get('usage', '')}")
    lines.append("")
    segs = svs.get("segments") or []
    for seg in segs:
        lines.append(f"### Segment {seg.get('idx', '?')} ({seg.get('duration_sec', '?')}s)")
        lines.append("")
        lines.append("**起始帧 (zh):**")
        lines.append("```")
        lines.append(seg.get("first_frame_prompt_zh", "(空)"))
        lines.append("```")
        lines.append("**结束帧 (zh):**")
        lines.append("```")
        lines.append(seg.get("last_frame_prompt_zh", "(空)"))
        lines.append("```")
        lines.append("**镜头运动 (zh):**")
        lines.append("```")
        lines.append(seg.get("motion_prompt_zh", "(空)"))
        lines.append("```")
        lines.append("")

    # ── 全局产物 3: t2v 长视频 ──
    lines.append("## 全局产物 3 — t2v 长视频（喂 Sora2 / Runway / Veo3.1 t2v）")
    lines.append("")
    lines.append(f"> {svl.get('usage', '')} — 总时长 {svl.get('total_duration_sec', '?')}s")
    lines.append("")
    lines.append("### 中文版")
    lines.append("```")
    lines.append(svl.get("prompt_zh", "(空)"))
    lines.append("```")
    lines.append("")
    lines.append("### 英文版")
    lines.append("```")
    lines.append(svl.get("prompt_en", "(empty)"))
    lines.append("```")
    lines.append("")

    # ── 🚀 喂回模型操作手册(13 模型 + 自动 MJ flag 版 + Veo timestamp 版) ──
    lines.extend(_render_model_playbook(result))

    # ── 每 scene 的 3 类 prompt 详情 (折叠展示) ──
    lines.append("## Scene 级 3 类 prompt 详情")
    lines.append("")
    for s in scenes:
        idx = s.get("idx", "?")
        lines.append(f"### Scene {idx} (`{s.get('time_range', [0,0])[0]:.1f}-{s.get('time_range', [0,0])[1]:.1f}s`)")
        lines.append("")
        lines.append(f"- 主体: {s.get('subject', '?')}")
        lines.append(f"- 动作: {s.get('action', '?')}")
        lines.append(f"- 环境: {s.get('environment', '?')}")
        lines.append(f"- 镜头: {s.get('shot_type', '?')} / 运动 {s.get('camera_motion', '?')}")
        lines.append(f"- 光影: {s.get('lighting', '?')}")
        lines.append(f"- 风格: {','.join(s.get('style_keywords') or [])}")
        lines.append(f"- 情绪: {','.join(s.get('mood_keywords') or [])}")
        if s.get("dialogue"):
            lines.append(f"- 台词: {s['dialogue']}")
        if s.get("voiceover_guess"):
            lines.append(f"- 旁白: {s['voiceover_guess']}")
        if s.get("sfx_ambient"):
            lines.append(f"- 环境音: {s['sfx_ambient']}")
        if s.get("on_screen_text"):
            lines.append(f"- 字幕: {s['on_screen_text']}")
        lines.append("")
        # scene 级 3 类 prompt 包(LLM 可选输出;缺失就跳过,顶层全局产物已覆盖)
        pi = s.get("prompt_for_image")
        pv = s.get("prompt_for_video_i2v")
        pt = s.get("prompt_for_video_t2v")
        if pi and isinstance(pi, dict) and (pi.get("zh") or pi.get("en")):
            lines.append("**A. 图像生成 prompt (喂 generate_image / Imagen / MJ):**")
            lines.append("```")
            lines.append(f"[zh] {pi.get('zh', '')}")
            lines.append(f"[en] {pi.get('en', '')}")
            lines.append("```")
        if pv and isinstance(pv, dict) and (pv.get("zh") or pv.get("en")):
            lines.append("**B. i2v 视频 prompt (喂 Veo3.1 i2v / Seedance i2v):**")
            lines.append("```")
            lines.append(f"[zh motion] {pv.get('zh', '')}")
            lines.append(f"[en motion] {pv.get('en', '')}")
            lines.append(f"[first_frame_hint] {s.get('first_frame_hint', '')}")
            lines.append(f"[last_frame_hint] {s.get('last_frame_hint', '')}")
            lines.append("```")
        if pt and isinstance(pt, dict) and (pt.get("zh") or pt.get("en")):
            lines.append("**C. t2v 视频 prompt (喂 Sora2 / Veo3.1 t2v):**")
            lines.append("```")
            lines.append(f"[zh] {pt.get('zh', '')}")
            lines.append(f"[en] {pt.get('en', '')}")
            lines.append("```")
        # 都缺时给个提示,让老板知道全局产物里还有
        if not (pi or pv or pt):
            lines.append("> _scene 级 3 类 prompt 包 LLM 这次没单独输出,直接看上面的「全局产物 1/2/3」即可(已覆盖)。_")
        if s.get("negative_hints"):
            lines.append(f"**反向提示:** {','.join(s['negative_hints'])}")
        lines.append("")

    return "\n".join(lines)
