"""Prompt templates for Content Studio pipeline steps.

Core capabilities:
  1. Copy/script generation prompts (original)
  2. Script analysis — extract characters & product appearances
  3. Character face generation prompt
  4. Image prompt transformer — scene → image-gen-optimized prompt with product/character anchors
  5. Video prompt transformer — scene → video-gen-optimized prompt with reference images
"""

from __future__ import annotations

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

## 要求
- 风格：{style_desc}
- 语气：{tone_desc}
- 文案长度：150-300字，适合15-30秒短视频的旁白量
- 结构清晰：开头吸引注意力（hook）→ 中间传递核心卖点 → 结尾引导行动（CTA）
- 语言自然流畅，适合口播朗读
- 不要使用 Markdown 格式，直接输出纯文本文案

请直接输出文案内容，不要加任何前缀说明。"""


def build_script_prompt(copy_text: str, config: dict) -> str:
    pace = config.get("pace", "medium")
    pace_desc = PACE_DESCRIPTIONS.get(pace, PACE_DESCRIPTIONS["medium"])
    image_style = config.get("image_style", "lifestyle_photo")
    product_desc = config.get("product_description", "")
    product_hint = ""
    if product_desc:
        product_hint = f"\n- 产品信息：{product_desc}（产品白底图由用户单独上传，脚本中需标注哪些场景出现产品）"

    return f"""你是一位专业的短视频分镜脚本编剧。请将以下营销文案拆解为结构化的短视频分镜脚本。

## 营销文案
{copy_text}

## 要求
- 节奏：{pace_desc}
- 画面风格：{image_style}{product_hint}
- 总时长控制在15-30秒
- 每个场景包含：画面描述、旁白文字、镜头运动、字幕花字
- 画面描述要非常具体详细，包含构图、光线、色调、主体动作等
- 如果场景中出现人物，给人物命名（如"小美"、"模特A"），并用 characters 数组列出
- 如果场景中出现产品，设置 has_product: true
- 镜头运动从以下选择：static, slow_push_in, slow_pull_out, pan_left, pan_right, tilt_up, tilt_down, tracking
- 转场从以下选择：cut, fade, dissolve, wipe, zoom

请严格按照以下 JSON 格式输出，不要输出任何其他内容：

```json
{{
  "title": "视频标题",
  "duration_seconds": 25,
  "scenes": [
    {{
      "scene_id": 1,
      "duration": "5s",
      "visual_description": "详细的画面描述，包含构图、光线、色调、主体动作、场景环境",
      "narration": "这个场景的旁白文字",
      "camera_movement": "slow_push_in",
      "text_overlay": "需要叠加的字幕或花字（可为空字符串）",
      "transition": "fade",
      "characters": ["小美"],
      "has_product": true
    }}
  ]
}}
```"""


# ══════════════════════════════════════════════════
# 2. Script analysis — extract characters + product map
# ══════════════════════════════════════════════════

def build_script_analysis_prompt(script_json: dict) -> str:
    """Analyze a script to extract all characters and their scene appearances."""
    import json
    script_text = json.dumps(script_json, ensure_ascii=False, indent=2)

    return f"""你是一位视觉总监。请分析以下短视频脚本，提取所有出现的人物角色和产品出现信息。

## 脚本
{script_text}

## 任务
1. 识别脚本中所有出现的**人物角色**（不包括纯环境人物如"路人"）
2. 对每个角色给出：名称、外貌描述（性别、年龄段、发型、体型、着装风格）、出现的场景ID列表
3. 标注哪些场景包含产品展示

请严格按以下 JSON 格式输出：

```json
{{
  "characters": [
    {{
      "id": "char_1",
      "name": "小美",
      "gender": "female",
      "age_range": "20-25",
      "appearance": "长发、瓜子脸、清新自然妆容、穿白色T恤",
      "scene_ids": [1, 3, 5]
    }}
  ],
  "product_scenes": [2, 4, 5],
  "product_description_from_script": "产品在脚本中的描述摘要"
}}
```"""


# ══════════════════════════════════════════════════
# 3. Character face generation prompt
# ══════════════════════════════════════════════════

def build_character_face_prompt(character: dict, image_style: str = "lifestyle_photo") -> str:
    """Build a prompt to generate a consistent character portrait/face reference."""
    name = character.get("name", "角色")
    gender = character.get("gender", "")
    age = character.get("age_range", "")
    appearance = character.get("appearance", "")

    gender_en = {"male": "male", "female": "female"}.get(gender, "person")
    style_hints: dict[str, str] = {
        "lifestyle_photo": "photorealistic portrait photography, natural lighting, clean background, sharp focus on face",
        "cinematic": "cinematic portrait, dramatic rim lighting, shallow depth of field, film grain",
        "vibrant": "vibrant commercial portrait, bold colors, studio lighting, confident expression",
        "clean_modern": "clean modern headshot, studio lighting, neutral background, professional look",
        "warm_illustration": "warm digital illustration portrait, soft pastel colors, gentle expression",
    }
    hint = style_hints.get(image_style, style_hints["lifestyle_photo"])

    return (
        f"A {gender_en} portrait, age {age}, {appearance}. "
        f"Front-facing bust shot, neutral expression, looking at camera. "
        f"{hint}, high resolution, 1:1 aspect ratio, "
        f"suitable as character reference sheet for video production"
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
                char_parts.append(
                    f"  - {cname}：{profile.get('gender', '')}，"
                    f"{profile.get('age_range', '')}岁，"
                    f"{profile.get('appearance', '')}。"
                    f"（已有参考人像，生成时必须保持此人物外貌特征完全一致）"
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
1. 使用英文输出，长度 80-200 词
2. 结构顺序：主体 → 动作/姿态 → 场景环境 → 光线色调 → 构图 → 画面风格
3. 如果场景有人物，必须详细描述人物的五官、发型、肤色、表情、服装，确保与上述人物档案一致
4. 如果场景有产品，必须详细描述产品外观（形状、颜色、logo位置、包装材质），确保与白底图一致
5. 同一个人物在不同场景的提示词中，外貌描述用词必须完全相同（锚定一致性）
6. 不要出现中文，不要加引号或额外说明
7. 画面比例默认 16:9

请直接输出英文提示词，不要加任何前缀。"""


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

## Seedance 2.0 提示词规则
1. 使用中文输出
2. 通过「图片N」引用参考图片（N 是该图片在 content 中同类型素材中的序号，从1开始）
3. 如果有人物参考图：写「图片N中的人物...」来锚定人物外貌
4. 如果有产品参考图：写「图片N中的产品...」来锚定产品外观
5. 明确描述运镜方式（如：{camera_zh}）
6. 描述关键动作的时间节点（如：0-2秒做什么，2-4秒做什么）
7. 人物口播可用「说"台词内容"」格式
8. 产品出现时强调产品细节清晰、标签可见
9. 不要加任何 JSON 格式或额外说明

请直接输出提示词内容。"""


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
