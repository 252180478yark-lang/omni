"""Prompt templates for Content Studio pipeline steps.

Core capabilities:
  1. Copy/script generation prompts (original)
  2. Script analysis — extract characters & product appearances
  3. Character face generation prompt
  4. Image prompt transformer — scene → image-gen-optimized prompt with product/character anchors
  5. Video prompt transformer — scene → video-gen-optimized prompt with reference images
"""

from __future__ import annotations

from app.services.prompt_commons import (
    CONSISTENCY_ANCHOR_RULE,
    JSON_OUTPUT_DISCIPLINE,
    NO_AI_SLANG,
)

STYLE_DESCRIPTIONS: dict[str, str] = {
    "grassplanting": "种草安利风格：口语化、真实体验感、像朋友推荐一样自然，适合小红书/抖音",
    "brand": "品牌宣传风格：高端大气、电影感文案、注重品牌调性和情感共鸣",
    "promotion": "促销活动风格：突出优惠力度、制造紧迫感、强调性价比和限时机会",
    "tech_review": "科技测评风格：理性客观、数据驱动、专业术语适度、结构化分析",
    "storytelling": "温馨故事风格：情感共鸣、生活化场景、以人物故事带动产品",
}

TONE_DESCRIPTIONS: dict[str, str] = {
    "casual": "轻松活泼、口语化",
    "professional": "专业正式、品牌感",
    "exciting": "热情激昂、有感染力",
    "analytical": "冷静理性、数据说话",
    "emotional": "温情感性、引发共鸣",
}

PACE_DESCRIPTIONS: dict[str, str] = {
    "fast": "快节奏，每个场景2-3秒，信息密度高",
    "medium": "中等节奏，每个场景3-5秒，张弛有度",
    "slow": "慢节奏，每个场景5-8秒，注重氛围渲染",
}


# ══════════════════════════════════════════════════
# 三目的分流（曝光 / 种草 / 收割）— 完整说明书
# ══════════════════════════════════════════════════

PURPOSE_PLAYBOOK: dict[str, dict[str, str]] = {
    "awareness": {
        "label": "曝光",
        "intent": "让大量泛人群第一次认识品牌或产品，建立眼缘与记忆点",
        "content_principle": (
            "泛娱乐 80% + 产品 20%。前 1.5 秒必须有强钩子（冲突/悬念/反差/视觉冲击）。"
            "产品仅作为情节中的视觉线索出现，不强调功能与卖点。"
            "适合穿插剧情、热点梗、生活段子、视觉奇观。"
        ),
        "scene_emphasis": "强情绪节拍 / 冲突反转 / 视觉记忆符号；卖点最多带 1 条最直观的（如外观/品牌色）。",
        "audience_match": "宽口径，年龄/性别覆盖广；A1 级别人群（认知层）。",
        "kpi_focus": "完播率 / 互动率 / 涨粉率 / 品牌搜索词增长。",
        "do_nots": "不要堆功能点；不要硬广腔；不要密集出现产品镜头。",
    },
    "planting": {
        "label": "种草",
        "intent": "让中度兴趣人群对产品产生好感与冲动加购，沉浸式建立信任",
        "content_principle": (
            "真实体验 + 场景化解决方案。前 3 秒讲清楚『这个东西能解决你哪个具体痛』。"
            "中段必须出现 1-2 个独特卖点的可视化证据（特写/对比/工艺细节/真实使用场景）。"
            "末尾给一个具体的尝试理由（试用价/搭配方法/某类人群必入）。"
        ),
        "scene_emphasis": "痛点共鸣 → 产品出场 → 独特卖点可视化 → 体验时刻 → 推荐动作。",
        "audience_match": "A2-A3 级别（兴趣 → 询问），匹配人群画像精准。",
        "kpi_focus": "加购率 / 评论求购率 / A3 级人群增量 / 收藏率。",
        "do_nots": "不要讲价格促销；不要泛泛 USP；不要让产品晚出场（≥3秒未现产品视为失败）。",
    },
    "conversion": {
        "label": "收割",
        "intent": "把高意向人群推上付款临门一脚，强转化",
        "content_principle": (
            "强促销 + 紧迫感 + 信任背书。前 3 秒必须出现『今日/限时/专属』关键词与价格利益点。"
            "中段堆叠社会证据（销量/评价/达人背书/复购证言）。"
            "结尾必须明确 CTA：『点小黄车』『限今日』『N 件套优惠』。"
        ),
        "scene_emphasis": "价格利益点 → 销量/口碑证据 → 限时机制 → CTA 闭环。",
        "audience_match": "A4 级别（行动），已经被种过草的高意向人群。",
        "kpi_focus": "GMV / CVR / ROI / 客单价。",
        "do_nots": "不要拖戏；不要讲品牌故事；不要让 CTA 出现在 5 秒之后。",
    },
}


def get_purpose_block(target_purpose: str | None) -> str:
    """根据 target_purpose 返回完整的『目的说明书』段落，可拼到任何 prompt 里。

    target_purpose:
      - None / 未指定：返回空字符串（让 LLM 自己推断）
      - awareness / planting / conversion：返回该目的的硬约束段落
    """
    if not target_purpose:
        return ""
    book = PURPOSE_PLAYBOOK.get(target_purpose)
    if not book:
        return ""
    return f"""
## 目的（target_purpose = {target_purpose} · {book['label']}）
- **意图**：{book['intent']}
- **内容原则**：{book['content_principle']}
- **场景重点**：{book['scene_emphasis']}
- **目标人群层级**：{book['audience_match']}
- **核心 KPI**：{book['kpi_focus']}
- **禁忌**：{book['do_nots']}
"""


# ══════════════════════════════════════════════════
# 1. Original: copy / script generation
# ══════════════════════════════════════════════════

def build_copy_prompt(source_text: str, config: dict) -> str:
    style = config.get("copy_style", "grassplanting")
    tone = config.get("tone", "casual")
    style_desc = STYLE_DESCRIPTIONS.get(style, STYLE_DESCRIPTIONS["grassplanting"])
    tone_desc = TONE_DESCRIPTIONS.get(tone, TONE_DESCRIPTIONS["casual"])

    return f"""你是一位资深短视频营销文案专家。请根据以下运营方案，撰写一段用于短视频的营销文案。

## 运营方案
{source_text}

## 写作要求
- 风格：{style_desc}
- 语气：{tone_desc}
- 文案长度：150-300 字，适合 15-30 秒短视频的旁白量
- 结构：开头 3 秒 hook（痛点/反常识/利益点）→ 中段卖点 1-2 条（带具体细节或数字）→ 结尾 CTA（明确下一步动作）
- 语言适合口播朗读：句短、节奏清晰、避免长定语

## Hook 写法参考（三选一，不要都用）
1. 反问式："你是不是也试过 XX 都没效果？"
2. 痛点式："XX 人群最怕的就是 XX"
3. 场景式："早上起来头疼到不行，我才知道……"

{NO_AI_SLANG}

## 输出
直接输出文案纯文本（不加前缀说明，不加 Markdown 标题/列表/代码块）。"""


def build_script_prompt(
    copy_text: str,
    config: dict,
    *,
    banned_words: list[str] | None = None,
    voice_examples: list[str] | None = None,
    target_purpose: str | None = None,
) -> str:
    pace = config.get("pace", "medium")
    pace_desc = PACE_DESCRIPTIONS.get(pace, PACE_DESCRIPTIONS["medium"])
    image_style = config.get("image_style", "lifestyle_photo")
    product_desc = config.get("product_description", "")
    product_hint = ""
    if product_desc:
        product_hint = f"\n- 产品信息：{product_desc}（产品白底图由用户单独上传，脚本中需标注哪些场景出现产品）"

    banned_block = ""
    if banned_words:
        banned_block = (
            "\n\n## 口播禁用词（绝对不能出现在 narration 中）\n"
            + "、".join(banned_words)
            + "\n命中任意词即视为不合格，请改用更口语化、有真实感的表达。"
        )

    voice_block = ""
    if voice_examples:
        sample = "\n".join(f"- {ex}" for ex in voice_examples[:5])
        voice_block = (
            "\n\n## 真人口播语料示例（请模仿语气和句长）\n" + sample
        )

    purpose_block = get_purpose_block(target_purpose)

    return f"""你是一位专业的短视频分镜脚本编剧。请将以下营销文案拆解为结构化的短视频分镜脚本。

## 营销文案
{copy_text}
{purpose_block}
## 写作要求
- 节奏：{pace_desc}
- 画面风格：{image_style}{product_hint}
- 必须恰好输出 10 个 scenes，scene_id 必须从 1 到 10 连续编号
- 总时长 15-30 秒；10 个场景共同覆盖 hook、痛点、卖点、演示、信任背书、CTA
- **场景节奏须严格匹配上方 target_purpose**：曝光强钩子+泛娱乐占主、种草前 3 秒必出产品+独特卖点视觉化、收割前 3 秒必出价格利益点+CTA
- 画面描述要具体详细：构图、光线、色调、主体动作、场景环境全都要提
- 每个场景的 narration 适合口播朗读（句短、不带 Markdown）

## 枚举值字典（只能从中选）
- `camera_movement`: `static` / `slow_push_in` / `slow_pull_out` / `pan_left` / `pan_right` / `tilt_up` / `tilt_down` / `tracking`
- `transition`: `cut` / `fade` / `dissolve` / `wipe` / `zoom`

## 人物 & 产品字段
- `characters`：**字符串数组**（人物名字符串，非对象）。如 `["小美", "模特A"]`。纯环境路人/NPC 不计入。
- `has_product`：布尔值。场景中有产品出镜时为 `true`。

{NO_AI_SLANG}

{JSON_OUTPUT_DISCIPLINE}

## 输出 Schema
```json
{{
  "title": "视频标题",
  "duration_seconds": 25,
  "scenes": [
    {{
      "scene_id": 1,
      "duration": "5s",
      "visual_description": "详细的画面描述（构图/光线/色调/主体动作/场景环境）",
      "narration": "本场景旁白（口播朗读的那句话）",
      "camera_movement": "slow_push_in",
      "text_overlay": "字幕或花字（无则空字符串）",
      "transition": "fade",
      "characters": ["小美"],
      "has_product": true
    }}
  ]
}}
```
注意：上面的 scenes 示例只展示了 1 个对象，实际输出必须包含恰好 10 个 scene 对象。{banned_block}{voice_block}"""


# ══════════════════════════════════════════════════
# 2. Script analysis — extract characters + product map
# ══════════════════════════════════════════════════

def build_script_analysis_prompt(script_json: dict, avatar_guidance: str | None = None) -> str:
    """Analyze a script to extract all characters and their scene appearances."""
    import json
    script_text = json.dumps(script_json, ensure_ascii=False, indent=2)

    guidance_block = ""
    if avatar_guidance and avatar_guidance.strip():
        guidance_block = f"""

## 用户输入的人脸/数字人基础指引（必须优先参考）
{avatar_guidance.strip()}

请把这些指引合并进主要人物的 `appearance`，但不要编造与脚本明显冲突的信息。
"""

    return f"""你是一位视觉总监。请分析以下短视频脚本，提取所有主要人物角色和产品出现信息。

## 脚本
{script_text}
{guidance_block}

## 人物识别标准
**纳入**：
- 有台词 / 有特写 / 在多个场景重复出现的人物（主角、助播、模特、嘉宾）
- 脚本中给出名字或明确身份标识的人物

**排除**（不计入 characters）：
- 纯背景路人、NPC、人群远景
- 一次性出现、无台词、无特写的人物
- 抽象概念化描述（如"现代都市人"）

## 外貌字段规范（`appearance`）
用顿号分隔的短语，按固定顺序：**发型 → 脸型 → 妆容/气质 → 服装**。
示例："长发直发、瓜子脸、清新自然妆容、白色 T 恤 + 牛仔裤"

## 产品场景标注
- `product_scenes`：所有出现产品实物（而非口头提及）的 scene_id 数组
- `product_description_from_script`：聚合脚本中与产品相关的视觉描述（颜色、形状、包装、使用状态），不带品牌口号

{JSON_OUTPUT_DISCIPLINE}

## 输出 Schema
```json
{{
  "characters": [
    {{
      "id": "char_1",
      "name": "小美",
      "gender": "female",
      "age_range": "20-25",
      "appearance": "长发直发、瓜子脸、清新自然妆容、白色 T 恤",
      "scene_ids": [1, 3, 5]
    }}
  ],
  "product_scenes": [2, 4, 5],
  "product_description_from_script": "产品的视觉描述摘要"
}}
```"""


# ══════════════════════════════════════════════════
# 3. Character face generation prompt
# ══════════════════════════════════════════════════

def build_character_face_prompt(
    character: dict,
    image_style: str = "lifestyle_photo",
    avatar_guidance: str | None = None,
) -> str:
    """Build a prompt to generate a consistent character portrait/face reference.

    Direct image-gen prompt (not an LLM prompt). Output is English-only;
    the `appearance` field is expected to be converted to English features
    by the LLM pipeline upstream, or used as-is if already descriptive.
    """
    gender = character.get("gender", "")
    age = character.get("age_range", "")
    appearance = character.get("appearance", "")
    if avatar_guidance and avatar_guidance.strip():
        appearance = f"{appearance}. Additional user guidance: {avatar_guidance.strip()}"

    gender_en = {"male": "male", "female": "female"}.get(gender, "person")
    style_hints: dict[str, str] = {
        "lifestyle_photo": "photorealistic portrait photography, natural lighting, clean neutral background, sharp focus on face, true-to-life skin texture",
        "cinematic": "cinematic portrait, dramatic rim lighting, shallow depth of field, film grain, moody atmosphere",
        "vibrant": "vibrant commercial portrait, bold colors, studio lighting, confident expression",
        "clean_modern": "clean modern headshot, studio lighting, neutral background, professional look",
        "warm_illustration": "warm digital illustration portrait, soft pastel colors, gentle expression",
    }
    hint = style_hints.get(image_style, style_hints["lifestyle_photo"])

    # Anchor physical identity first (for cross-scene consistency),
    # then framing + style.
    return (
        f"A {gender_en} portrait, age range {age}. "
        f"Physical features (do NOT change across scenes): {appearance}. "
        f"Framing: front-facing bust shot, neutral relaxed expression, looking directly at camera. "
        f"Style: {hint}. "
        f"High resolution, 1:1 aspect ratio, character reference sheet for video production, "
        f"no text overlays, no watermarks."
    )


# ══════════════════════════════════════════════════
# 4. Image prompt transformer (scene → image-gen prompt)
# ══════════════════════════════════════════════════

def build_image_prompt(visual_description: str, image_style: str = "lifestyle_photo") -> str:
    """Original simple image prompt builder (backward compat)."""
    style_hints: dict[str, str] = {
        "lifestyle_photo": "photorealistic lifestyle photography, natural lighting, warm tones",
        "cinematic": "cinematic film still, dramatic lighting, shallow depth of field, anamorphic lens",
        "vibrant": "vibrant commercial photography, bold colors, high contrast, energetic composition",
        "clean_modern": "clean modern product photography, minimalist, studio lighting, white background accent",
        "warm_illustration": "warm digital illustration, soft pastel colors, cozy atmosphere, gentle lighting",
    }
    hint = style_hints.get(image_style, style_hints["lifestyle_photo"])
    return f"{visual_description}, {hint}, high quality, 16:9 aspect ratio"


def build_scene_to_image_prompt(
    scene: dict,
    *,
    image_style: str = "lifestyle_photo",
    product_images: list[str] | None = None,
    character_profiles: list[dict] | None = None,
) -> str:
    """Build the LLM prompt that transforms a scene description into an image-gen-optimized prompt.

    This is a PROMPT FOR THE LLM, which then outputs the actual image generation prompt.
    The LLM acts as a "prompt translator" that understands what image generation models prefer.
    """
    style_hints: dict[str, str] = {
        "lifestyle_photo": "photorealistic lifestyle photography, natural lighting, warm tones",
        "cinematic": "cinematic film still, dramatic lighting, shallow depth of field",
        "vibrant": "vibrant commercial photography, bold colors, high contrast",
        "clean_modern": "clean modern product photography, minimalist, studio lighting",
        "warm_illustration": "warm digital illustration, soft pastel colors, gentle lighting",
    }
    hint = style_hints.get(image_style, style_hints["lifestyle_photo"])

    visual = scene.get("visual_description", "")
    characters_in_scene = scene.get("characters", [])
    has_product = scene.get("has_product", False)

    # Build character reference descriptions
    char_instructions = ""
    if characters_in_scene and character_profiles:
        profile_map = {p["name"]: p for p in character_profiles}
        char_parts = []
        for cname in characters_in_scene:
            profile = profile_map.get(cname)
            if profile:
                ref_note = (
                    "已有参考人像，生成时必须保持此人物外貌特征完全一致"
                    if profile.get("face_url")
                    else "未提供参考人像，请严格按文字外貌描述生成并保持跨场景一致"
                )
                char_parts.append(
                    f"  - {cname}：{profile.get('gender', '')}，"
                    f"{profile.get('age_range', '')}岁，"
                    f"{profile.get('appearance', '')}。"
                    f"（{ref_note}）"
                )
        if char_parts:
            char_instructions = "\n## 本场景出现的人物（必须保持一致）\n" + "\n".join(char_parts)

    product_instructions = ""
    if has_product and product_images:
        product_instructions = (
            "\n## 产品展示要求\n"
            "本场景包含产品，用户已上传产品白底图。生成的提示词中必须：\n"
            "- 精确描述产品的外观、形状、颜色、包装细节\n"
            "- 确保产品在画面中清晰可辨、不变形\n"
            "- 产品外观必须与白底图完全一致\n"
        )

    return f"""你是一位专业的 AI 图像生成提示词工程师。请将以下短视频分镜的画面描述，转换为一段高质量的英文图像生成提示词。

## 原始画面描述
{visual}
{char_instructions}
{product_instructions}

## 目标画面风格
{hint}

## 提示词编写规则
1. **纯英文输出**，80-200 词。**禁止出现任何中文字符**（包括标点）。
2. 结构顺序：主体 → 动作/姿态 → 场景环境 → 光线色调 → 构图 → 画面风格。
3. 人物描写必须具体：发型/脸型/肤色/眼神/表情/服装（短语级，不要整句），与上方人物档案精确一致。
4. 产品描写必须具体：形状/颜色/logo 位置/材质/包装细节，与参考白底图精确一致。
5. 画面比例默认 16:9，除非描述中明确指定竖屏。
6. 不要加引号、前缀说明、markdown 包裹。

{CONSISTENCY_ANCHOR_RULE}

## 输出
直接输出英文提示词一段文本（无引号、无前缀）。"""


# ══════════════════════════════════════════════════
# 5. Video prompt transformer (scene → video-gen prompt)
# ══════════════════════════════════════════════════

def build_scene_to_video_prompt(
    scene: dict,
    *,
    product_images: list[str] | None = None,
    character_profiles: list[dict] | None = None,
) -> str:
    """Build the LLM prompt that transforms a scene description into a Seedance 2.0 video-gen prompt.

    Seedance 2.0 prompt conventions:
    - Reference images by "图片N" (Nth image_url in content array, 1-indexed within same type)
    - Reference videos by "视频N"
    - Reference audios by "音频N"
    - Describe camera movement, timing, actions in Chinese
    """
    visual = scene.get("visual_description", "")
    narration = scene.get("narration", "")
    camera = scene.get("camera_movement", "")
    duration = scene.get("duration", "5s")
    characters_in_scene = scene.get("characters", [])
    has_product = scene.get("has_product", False)

    # Count how many reference images will be passed to the API
    # Order: character faces first, then product images
    img_index = 1
    char_ref_map: dict[str, int] = {}
    if character_profiles:
        profile_map = {p["name"]: p for p in character_profiles if p.get("face_url")}
        for cname in characters_in_scene:
            if cname in profile_map:
                char_ref_map[cname] = img_index
                img_index += 1

    product_img_index = img_index if (has_product and product_images) else 0

    # Build character instructions for the prompt
    char_parts = []
    for cname, idx in char_ref_map.items():
        profile = next((p for p in (character_profiles or []) if p["name"] == cname), {})
        char_parts.append(
            f"  - 图片{idx} 是「{cname}」的人像参考"
            f"（{profile.get('appearance', '')}），"
            f"视频中此人物的外貌必须与图片{idx}完全一致"
        )

    product_part = ""
    if product_img_index and product_images:
        product_part = (
            f"  - 图片{product_img_index} 是产品白底图，"
            f"视频中产品的外观必须与图片{product_img_index}完全一致"
        )

    camera_zh = {
        "static": "固定机位",
        "slow_push_in": "缓慢推进",
        "slow_pull_out": "缓慢拉远",
        "pan_left": "左摇",
        "pan_right": "右摇",
        "tilt_up": "上摇",
        "tilt_down": "下摇",
        "tracking": "跟拍",
    }.get(camera, camera)

    ref_block = ""
    if char_parts or product_part:
        ref_block = "\n## 参考素材说明（在 Seedance API content 数组中的对应关系）\n"
        ref_block += "\n".join(char_parts)
        if product_part:
            ref_block += "\n" + product_part

    return f"""你是一位专业的 Seedance 2.0 视频生成提示词工程师。请将以下短视频分镜描述，转换为适合 Seedance 2.0 API 的中文视频生成提示词。

## 原始画面描述
{visual}

## 旁白
{narration}

## 运镜
{camera_zh}

## 时长
{duration}
{ref_block}

## Seedance 2.0 输出规则
1. **中文**输出（Seedance 2.0 的 prompt 语言要求）。
2. **参考图引用**：凡在"参考素材说明"中列出的「图片N」，必须用这个编号字面引用。
   - 人物："图片N 中的人物保持外貌一致，做 XX 动作"
   - 产品："图片N 中的产品以 XX 方式出现，细节清晰"
3. **运镜**：明确写出（如"{camera_zh}"），不要用模糊词（如"有镜头感"）。
4. **时间节点**：按秒级写关键动作，例如"0-2 秒 特写产品；2-4 秒 人物拿起产品并微笑"。
5. **口播**：台词用「说"台词内容"」格式表达，不要只写"人物讲解"。
6. **产品镜头**：强调产品细节清晰、标签可见、不变形。
7. 不要输出 JSON、markdown、额外说明或前缀。

## 输出
直接输出中文提示词（一整段文本，不加引号）。"""


# ══════════════════════════════════════════════════
# 6. Build reference_images order for Seedance API
# ══════════════════════════════════════════════════

def build_video_reference_images(
    scene: dict,
    *,
    character_profiles: list[dict] | None = None,
    product_images: list[str] | None = None,
) -> list[str]:
    """Determine the ordered list of reference_images to pass to the video API.

    Order must match the 图片N references in the prompt:
      1..K  = character face images (for characters in this scene)
      K+1   = product white-bg image (if scene has_product)
    """
    urls: list[str] = []
    characters_in_scene = scene.get("characters", [])
    has_product = scene.get("has_product", False)

    if character_profiles:
        profile_map = {p["name"]: p for p in character_profiles if p.get("face_url")}
        for cname in characters_in_scene:
            if cname in profile_map:
                urls.append(profile_map[cname]["face_url"])

    if has_product and product_images:
        urls.append(product_images[0])

    return urls


def build_typed_reference_images(
    scene: dict,
    *,
    character_profiles: list[dict] | None = None,
    product_images: list[str] | None = None,
) -> list[dict]:
    """Build typed refs for image/video generation.

    Output protocol:
      [{"url": "...", "type": "character|product", "weight": 1.0}]
    """
    refs: list[dict] = []
    characters_in_scene = scene.get("characters", [])
    has_product = scene.get("has_product", False)

    if character_profiles:
        profile_map = {p["name"]: p for p in character_profiles if p.get("face_url")}
        for cname in characters_in_scene:
            if cname in profile_map:
                refs.append({
                    "url": profile_map[cname]["face_url"],
                    "type": "character",
                    "weight": 1.0,
                })

    if has_product and product_images:
        refs.append({"url": product_images[0], "type": "product", "weight": 1.0})

    return refs
