"""character_anchor.py — 5-layer character prompt generator for step 6.5.

Layer 1: 8 structured input fields (from pipeline.scripts.character_sheets JSONB)
Layer 2: Rule-based feature lookup (age / gender / personality / scene / realism)
Layer 3: Recipe selection (intensity ratios per archetype)
Layer 4: 13-dim prompt assembly → ~400-500 word character anchor
Layer 5: Shot-variant additions (applied at step 6 scene level, not here)

Designed to replace the previous 6-field free-text keyword approach.
Falls back gracefully to old format when new fields are absent.
"""

from __future__ import annotations

import random


# ── Layer 2 rule tables ──────────────────────────────────────────────────────

_AGE_TO_FEATURES: dict[str, dict] = {
    "0-2": {
        "bracket": "infant",
        "skin": "dewy plump infant skin, baby fat cheeks, fine peach fuzz visible, rosy flush",
        "eyes": "oversized eye-to-face ratio, bright catchlight, drool sheen possible on chin",
        "teeth": "gummy smile, no visible teeth, or single emerging baby tooth",
        "hair": "fine sparse baby hair, sometimes bald patches, peach fuzz at temples",
        "asymmetry": "natural asymmetry from sleeping positions, slightly uneven head shape",
        "neck_hands": "chubby wrist rolls, plump dimpled knuckles, soft rounded nails",
        "expression_note": "unguarded involuntary expressions only — no adult micro-expressions",
        "posture": "supported posture, no independent stance",
    },
    "4-12": {
        "bracket": "child",
        "skin": "dewy childlike skin, slight redness in cheeks from play, smooth but not airbrushed",
        "eyes": "bright wide eyes, occasional mucus crust in corners, clear iris",
        "teeth": "gap-toothed, missing baby teeth, slightly crooked emerging permanent teeth",
        "hair": "messy from play, cowlicks, occasional hair stuck to sweaty forehead",
        "asymmetry": "natural unself-conscious asymmetry, small scabs or scratches possible",
        "neck_hands": "short stubby fingers, food residue near fingernails, scraped knuckles possible",
        "expression_note": "spontaneous unguarded emotions, no social masking",
        "posture": "slightly awkward, self-unconscious fidgeting",
    },
    "13-19": {
        "bracket": "teen",
        "skin": "hormonal skin changes, occasional acne on forehead and chin, oily T-zone, uneven texture",
        "eyes": "alert but slightly self-conscious, awkward fleeting eye contact",
        "teeth": "braces possible, teeth still developing, slight overcrowding",
        "hair": "attempted styling but slightly messy, flyaways, maybe dyed fading ends",
        "asymmetry": "self-aware but still natural imperfections, possible acne scarring beginning",
        "neck_hands": "lanky fingers, bitten nails possible",
        "expression_note": "slightly guarded, self-aware micro-tension, social performance beginning",
        "posture": "slight slouch or exaggerated upright — both from self-consciousness",
    },
    "20-29": {
        "bracket": "young_adult",
        "skin": "smooth but with visible pores, natural fine texture, no significant aging",
        "eyes": "bright clear eyes, full eyelashes, no significant under-eye darkness",
        "teeth": "healthy but slightly imperfect, natural off-white color, no veneers",
        "hair": "full thick hair, styled but with natural flyaways",
        "asymmetry": "subtle facial asymmetry, possible single dimple one side only",
        "neck_hands": "smooth neck, fine-textured hands, natural nail condition",
        "expression_note": "spontaneous varied emotional range, less social masking than older",
        "posture": "confident relaxed natural",
    },
    "30-39": {
        "bracket": "young_adult",
        "skin": "visible pores, fine laugh lines starting at eye corners, slight under-eye fatigue",
        "eyes": "subtle crow's feet beginning at corners when smiling, occasional tired look",
        "teeth": "real teeth color with slight wear, possible dental work becoming visible",
        "hair": "occasional gray strand near temples possible, still full",
        "asymmetry": "more settled asymmetry, first faint permanent laugh lines",
        "neck_hands": "first faint neck horizontal lines, hands showing slight wear",
        "expression_note": "more controlled professional micro-expressions, smile lines from years of laughing",
        "posture": "settled confident, slight professional tension",
    },
    "40-49": {
        "bracket": "middle_aged",
        "skin": "established laugh lines, nasolabial folds clearly present, sun spots starting, skin losing early elasticity",
        "eyes": "defined crow's feet even at rest, slight upper eyelid beginning to hood",
        "teeth": "slight yellowing, dental work visible on molars, natural gum recession beginning",
        "hair": "scattered gray especially at temples and crown, possibly thinning slightly",
        "asymmetry": "settled permanent asymmetry, forehead lines present",
        "neck_hands": "first neck vertical cords visible, dorsal hand veins more prominent",
        "expression_note": "settled life-experience expressions, less performative, more genuine",
        "posture": "established body language from professional or domestic role",
    },
    "50-59": {
        "bracket": "middle_aged",
        "skin": "pronounced wrinkles throughout, age spots visible especially on temples/cheeks, early jowling",
        "eyes": "hooded upper eyelids, deep crow's feet, slight under-eye hollowing",
        "teeth": "yellowed teeth, dental work prominent, slight gum recession",
        "hair": "significant gray mixing, thinning starting, visible scalp near crown possible",
        "asymmetry": "deep permanent asymmetry, one side more lined than other from habitual expressions",
        "neck_hands": "visible neck wrinkles, pronounced hand veins, age spots on hands",
        "expression_note": "weight of accumulated decisions visible, genuine emotional depth",
        "posture": "settled posture of decades, slight forward tilt common",
    },
    "60-74": {
        "bracket": "elderly",
        "skin": "deep wrinkles throughout, prominent age spots, significant skin sagging under jaw and cheeks, papery thinning on forehead",
        "eyes": "watery elderly eyes, early to moderate cataract haze giving milky quality, deeply hooded upper lids, visible inner corner moisture",
        "teeth": "significantly yellowed, dental work prominent, missing teeth possible, slight denture line if present",
        "hair": "mostly gray/white, thinning with visible scalp, baby hairs along hairline still, natural gray texture",
        "asymmetry": "deep permanent facial asymmetry from decades of habitual expressions, one eye more hooded",
        "neck_hands": "pronounced neck folds and cords, prominent veins on hands, age spots on backs of hands, arthritic joint enlargement, short ridged nails",
        "expression_note": "slow-developing expressions carrying weight of years, minimal but meaningful micro-expressions",
        "posture": "slight stoop from decades of work, shorter apparent stature, deliberate unhurried movements",
    },
    "75+": {
        "bracket": "elderly",
        "skin": "deep grooves and folds, thin papery skin, very prominent age spots, significant sagging throughout",
        "eyes": "heavy cataracts, very droopy lids, watery constantly, diminished iris clarity",
        "teeth": "dentures likely, multiple missing teeth, visible gum recession",
        "hair": "white and sparse, bald patches possible, very fine texture",
        "asymmetry": "extreme permanent asymmetry, asymmetric sagging",
        "neck_hands": "extremely papery neck, very frail-looking hands, skeletal structure visible",
        "expression_note": "childlike returning openness, less social self-consciousness than middle-age",
        "posture": "significantly stooped, frail visible, cautious deliberate movements",
    },
}


_GENDER_FEATURES: dict[str, dict] = {
    "female": {
        "facial_structure": "softer jawline definition, fuller lips, narrower jaw width",
        "hair_default": "longer or deliberately styled hair",
        "skin_note": "finer pore pattern, no beard shadow",
        "neck": "slimmer neck, more visible neck definition",
        "hands": "more slender finger proportions",
        "hair_extras": "",
    },
    "male": {
        "facial_structure": "more defined angular jawline, thinner lips, wider jaw width",
        "hair_default": "shorter or masculine-styled hair",
        "skin_note": "slightly thicker skin texture, more pronounced pores",
        "neck": "more muscular neck, visible Adam's apple",
        "hands": "broader palms, wider finger proportions",
        "hair_extras": "visible five o'clock shadow if 20+, ear hair and nose hair if 40+, arm hair visible",
    },
    "child": {
        "facial_structure": "gender-minimized, childlike features foregrounded",
        "hair_default": "depends on character, not gender-signaling",
        "skin_note": "child skin features override gender skin",
        "neck": "short rounded neck",
        "hands": "small chubby or growing fingers",
        "hair_extras": "",
    },
}


_PERSONALITY_TO_EXPRESSION: dict[str, dict] = {
    "安静的权威感": {
        "default": "relaxed but observant, minimal smiling, eyes carrying weight of experience",
        "smile_type": "subtle Duchenne (eye muscles engaged), never broad grin",
        "muscle_note": "zygomatic muscles at rest, expressiveness concentrated in eyes",
        "transition": "expressions develop slowly and stay briefly, deliberate",
    },
    "内敛": {
        "default": "controlled facial muscles, more expression in the eyes than the mouth, micro-tensions visible",
        "smile_type": "closed-mouth smile or eye-only smile",
        "muscle_note": "jaw slightly set, brow tension minimal but present",
        "transition": "expressions are small in amplitude, high in authenticity",
    },
    "活泼热情": {
        "default": "frequent micro-smiles, eyes engaging actively with environment, mouth often slightly parted",
        "smile_type": "full Duchenne with teeth showing",
        "muscle_note": "high zygomatic activity, animated brow movement",
        "transition": "fast expression transitions, high amplitude",
    },
    "焦虑紧张": {
        "default": "subtle masseter tension, slight brow furrow at rest, eyes scanning environment",
        "smile_type": "nervous smile that doesn't reach eyes, lip compression",
        "muscle_note": "slight corrugator tension at rest, lip pressed together when not speaking",
        "transition": "quick micro-expressions, overriding base tension",
    },
    "沧桑沉稳": {
        "default": "deeply settled presence, small deliberate movements only, long-pause expressions",
        "smile_type": "slow-developing Duchenne, meaningful when it appears",
        "muscle_note": "all muscles at settled rest, no unnecessary tension",
        "transition": "very slow expression development, high emotional weight when present",
    },
    "孩童天真": {
        "default": "unguarded emotions transparent on face, no social masking",
        "smile_type": "full uninhibited open-mouth smile",
        "muscle_note": "all muscles follow genuine emotion with zero filtering",
        "transition": "fast unguarded transitions, complete emotional transparency",
    },
    "default": {
        "default": "natural expression at rest, genuine emotional response",
        "smile_type": "natural Duchenne smile",
        "muscle_note": "neutral facial muscles",
        "transition": "natural expression transitions",
    },
}


_SCENE_DEFAULTS: dict[str, dict] = {
    "domestic_kitchen": {
        "clothing": "practical cotton or linen, possibly wearing apron, casual worn at-home clothing",
        "lighting_default": "warm 3000K tungsten or natural window light, side-directional",
        "posture_context": "relaxed but in-motion working stance, slight lean toward work surface",
        "environment_hint": "kitchen environment implied by context and posture",
    },
    "office_professional": {
        "clothing": "business casual or formal, deliberate grooming, attention to detail",
        "lighting_default": "neutral 5000K, often overhead or window-diffused",
        "posture_context": "alert professional posture, slight forward lean toward subject",
        "environment_hint": "professional indoor setting context",
    },
    "outdoor_natural": {
        "clothing": "seasonal appropriate, weather-influenced, relaxed outdoor wear",
        "lighting_default": "natural daylight, golden hour preferred, directional sun light",
        "posture_context": "relaxed environment-aware stance, slight movement",
        "environment_hint": "outdoor natural light and context",
    },
    "cafe_social": {
        "clothing": "stylish but casual, conversation-ready, mid-layer comfortable",
        "lighting_default": "warm ambient with window accent, low-medium intensity",
        "posture_context": "leaning in, engaged, slightly relaxed forward",
        "environment_hint": "social seating context implied",
    },
    "studio_portrait": {
        "clothing": "role-appropriate clothing, clean styling",
        "lighting_default": "controlled directional softbox, 5000-5500K neutral",
        "posture_context": "aware but natural, camera-adjacent gaze",
        "environment_hint": "clean neutral background, pure portrait context",
    },
}


_REALISM_TO_CAMERA: dict[str, dict] = {
    "documentary": {
        "camera": "shot on Sony A7IV with 50mm f/1.4 Summilux prime lens",
        "film": "Kodak Portra 400 film aesthetic",
        "style": "documentary photojournalism, candid moment, real photograph captured naturally, not AI generated",
        "grain": "subtle organic film grain, available light photography",
    },
    "commercial": {
        "camera": "shot on Hasselblad X2D with 80mm f/1.9 lens",
        "film": "clean medium format digital aesthetic",
        "style": "high-end commercial photography, controlled but natural feel",
        "grain": "minimal grain, sharp detail, professional retouching level",
    },
    "cinematic": {
        "camera": "shot on ARRI Alexa Mini LF with 35mm anamorphic Signature Prime",
        "film": "Kodak Vision3 250D color science",
        "style": "cinematic film aesthetic, slightly desaturated, anamorphic character",
        "grain": "subtle film grain, possible anamorphic lens flare at light edges",
    },
    "casual": {
        "camera": "shot on iPhone 15 Pro with natural lighting",
        "film": "modern smartphone color science, slightly warm auto-exposure",
        "style": "candid lifestyle photography, unposed, spontaneous moment",
        "grain": "minimal, natural digital noise in shadows",
    },
}


# ── Layer 3 recipe tables ────────────────────────────────────────────────────

_RECIPES: dict[str, dict] = {
    "elderly": {
        "L1_skin": "极强", "L2_eyes": "强", "L3_asymmetry": "强",
        "L4_age": "极强", "L5_expression": "中", "L6_lighting": "强",
        "L7_context": "强", "L8_camera": "强", "L9_teeth": "强",
        "L10_hair": "强", "L11_edge": "强", "L12_muscle": "中", "L13_breath": "中",
    },
    "young_adult": {
        "L1_skin": "中", "L2_eyes": "中", "L3_asymmetry": "强",
        "L4_age": "中", "L5_expression": "强", "L6_lighting": "中",
        "L7_context": "强", "L8_camera": "强", "L9_teeth": "中",
        "L10_hair": "强", "L11_edge": "中", "L12_muscle": "强", "L13_breath": "中",
    },
    "child": {
        "L1_skin": "强", "L2_eyes": "极强", "L3_asymmetry": "极强",
        "L4_age": "强", "L5_expression": "强", "L6_lighting": "中",
        "L7_context": "强", "L8_camera": "中", "L9_teeth": "极强",
        "L10_hair": "强", "L11_edge": "弱", "L12_muscle": "中", "L13_breath": "中",
    },
    "infant": {
        "L1_skin": "极强", "L2_eyes": "极强", "L3_asymmetry": "强",
        "L4_age": "极强", "L5_expression": "弱", "L6_lighting": "弱",
        "L7_context": "强", "L8_camera": "中", "L9_teeth": "强",
        "L10_hair": "强", "L11_edge": "弱", "L12_muscle": "弱", "L13_breath": "强",
    },
    "middle_aged": {
        "L1_skin": "强", "L2_eyes": "中", "L3_asymmetry": "强",
        "L4_age": "强", "L5_expression": "中", "L6_lighting": "中",
        "L7_context": "强", "L8_camera": "强", "L9_teeth": "中",
        "L10_hair": "强", "L11_edge": "强", "L12_muscle": "中", "L13_breath": "中",
    },
    "teen": {
        "L1_skin": "强", "L2_eyes": "中", "L3_asymmetry": "强",
        "L4_age": "强", "L5_expression": "强", "L6_lighting": "中",
        "L7_context": "强", "L8_camera": "中", "L9_teeth": "中",
        "L10_hair": "强", "L11_edge": "弱", "L12_muscle": "中", "L13_breath": "弱",
    },
}

_AGE_SPECIFIC_NEGATIVES: dict[str, str] = {
    "elderly": (
        "young manicured hands, hand model perfection, smooth neck, airbrushed neck, "
        "youthful skin on elderly subject, lifted face, smoothed wrinkles, anti-aging filter, "
        "botox look, exaggerated theatrical aging makeup, Halloween elderly costume, "
        "Korean drama grandma idealization, K-drama auntie filter"
    ),
    "young_adult": (
        "premature aging, excessive under-eye circles, advanced wrinkles, gray hair unless specified, "
        "over-retouched commercial skin, instagram filter, snow filter"
    ),
    "child": (
        "adult expressions, sophisticated micro-expressions, controlled poses, model child look, "
        "perfect grooming, staged expression, adult composure"
    ),
    "infant": (
        "adult facial expressions, walking stance, developed musculature"
    ),
    "middle_aged": (
        "excessive aging beyond years, heavily retouched skin, youthful skin inconsistent with age"
    ),
    "teen": (
        "adult composure, mature confidence, perfect grooming, model-ready expression"
    ),
}


def _age_bracket(age: int) -> str:
    if age <= 2:
        return "0-2"
    elif age <= 12:
        return "4-12"
    elif age <= 19:
        return "13-19"
    elif age <= 29:
        return "20-29"
    elif age <= 39:
        return "30-39"
    elif age <= 49:
        return "40-49"
    elif age <= 59:
        return "50-59"
    elif age <= 74:
        return "60-74"
    else:
        return "75+"


def _select_recipe(age: int) -> str:
    if age <= 2:
        return "infant"
    elif age <= 19:
        return "child" if age <= 12 else "teen"
    elif age <= 39:
        return "young_adult"
    elif age <= 59:
        return "middle_aged"
    else:
        return "elderly"


def _resolve_personality(personality: str) -> dict:
    """Match personality string to closest known entry; fall back to default."""
    if not personality:
        return _PERSONALITY_TO_EXPRESSION["default"]
    for key in _PERSONALITY_TO_EXPRESSION:
        if key != "default" and key in personality:
            return _PERSONALITY_TO_EXPRESSION[key]
    # Try first keyword
    first_kw = personality.split("、")[0].split("，")[0].strip()
    if first_kw in _PERSONALITY_TO_EXPRESSION:
        return _PERSONALITY_TO_EXPRESSION[first_kw]
    return _PERSONALITY_TO_EXPRESSION["default"]


def build_character_anchor_prompt(sheet: dict, for_portrait: bool = True) -> str:
    """Build a rich 400-500 word character anchor prompt from the 8-field sheet.

    Args:
        sheet: character sheet dict with keys: age, gender, ethnicity, body_type,
               role, life_context, personality, scene_type, realism_level,
               custom_imperfections (list[str]), name, role_id.
               Falls back gracefully if new fields are absent.
        for_portrait: if True, appends white-background portrait framing
                      (for step 6.5 character_sheet image generation).
                      If False, returns core anchor only (for embedding in scene prompts).

    Returns:
        Assembled prompt string ready to pass to image generation API.
    """
    # ── parse inputs ──────────────────────────────────────────────
    try:
        raw_age = sheet.get("age") or "30"
        age_int = int(str(raw_age).replace("岁", "").strip().split("-")[0].split("–")[0])
    except (ValueError, TypeError):
        age_int = 30

    gender_zh = (sheet.get("gender") or "").strip()
    gender_en = "woman" if "女" in gender_zh else "man" if "男" in gender_zh else "person"
    ethnicity = "Chinese"  # 硬锁中国人，不读 sheet.ethnicity
    body_type = (sheet.get("body_type") or "average").strip()
    role = (sheet.get("role") or sheet.get("name") or "").strip()
    life_context = (sheet.get("life_context") or "").strip()
    personality = (sheet.get("personality") or "").strip()
    scene_type = (sheet.get("scene_type") or "domestic_kitchen").strip()
    realism_level = (sheet.get("realism_level") or "documentary").strip()
    custom_imperfections: list[str] = sheet.get("custom_imperfections") or []

    # ── backward compat: fall back to old appearance_keywords if new fields absent ──
    appearance_keywords = (sheet.get("appearance_keywords") or "").strip()
    aura = (sheet.get("aura") or "").strip()
    has_new_fields = bool(role or life_context or personality)

    # ── Layer 2 lookups ───────────────────────────────────────────
    bracket = _age_bracket(age_int)
    age_features = _AGE_TO_FEATURES.get(bracket, _AGE_TO_FEATURES["30-39"])
    gender_feat = _GENDER_FEATURES.get(gender_en, _GENDER_FEATURES["female"])
    expr_tend = _resolve_personality(personality)
    scene_cfg = _SCENE_DEFAULTS.get(scene_type, _SCENE_DEFAULTS["domestic_kitchen"])
    cam_cfg = _REALISM_TO_CAMERA.get(realism_level, _REALISM_TO_CAMERA["documentary"])

    # ── Layer 3 recipe ────────────────────────────────────────────
    recipe_key = _select_recipe(age_int)
    recipe = _RECIPES[recipe_key]

    # ── Layer 4 assembly ──────────────────────────────────────────
    parts: list[str] = []

    # 族裔锚点放最前（图像模型头部权重最高，必须第一行）
    parts.append(
        f"East Asian Han Chinese {gender_en}, {age_int} years old, "
        "single eyelid or low-crease double eyelid, epicanthic fold, "
        "warm yellow-olive skin tone (Fitzpatrick III-IV), "
        "black straight hair, flat nasal bridge with rounded soft tip, "
        "softer rounded jaw — definitively East Asian face, NOT Caucasian NOT Western NOT European,"
    )

    # Camera & Style
    parts.append(
        f"{cam_cfg['camera']}, {cam_cfg['film']}, "
        f"{cam_cfg['style']}, {cam_cfg['grain']},"
    )

    # Identity
    identity_parts = [f"a {age_int}-year-old Chinese {gender_en}"]
    if body_type and body_type != "average":
        identity_parts.append(f"of {body_type} build")
    else:
        identity_parts.append("of average build")
    if role:
        identity_parts.append(f"— {role}")
    if life_context:
        identity_parts.append(f"— {life_context}")
    parts.append(", ".join(identity_parts) + ",")

    # L4 Age features (always 极强 framing for portrait quality)
    af = age_features
    age_section = (
        f"Age features [L4 - {recipe['L4_age']}]: "
        f"{af['skin']}, "
        f"{af['expression_note']}, "
        f"{af['posture']},"
    )
    parts.append(age_section)

    # L1 Skin
    skin_intensity = recipe["L1_skin"]
    skin_detail = af["skin"]
    if skin_intensity == "极强":
        skin_extra = "no retouching, no beauty filter, all age-appropriate skin imperfections fully visible"
    elif skin_intensity == "强":
        skin_extra = "visible pores and texture, no airbrushing"
    else:
        skin_extra = "natural skin texture visible"
    gender_skin = gender_feat["skin_note"]
    parts.append(f"Skin [L1 - {skin_intensity}]: {skin_detail}, {gender_skin}, {skin_extra},")

    # L10 Hair
    hair_intensity = recipe["L10_hair"]
    hair_detail = af["hair"]
    hair_gender = gender_feat["hair_extras"]
    hair_gender_part = f" {hair_gender}," if hair_gender else ","
    parts.append(f"Hair [L10 - {hair_intensity}]: {hair_detail}{hair_gender_part}")

    # L2 Eyes
    eyes_intensity = recipe["L2_eyes"]
    parts.append(f"Eyes [L2 - {eyes_intensity}]: {af['eyes']},")

    # L3 Asymmetry + custom imperfections
    asym_intensity = recipe["L3_asymmetry"]
    asym_base = af["asymmetry"]
    if custom_imperfections:
        imp_str = "; ".join(custom_imperfections)
        parts.append(
            f"Asymmetry & imperfections [L3 - {asym_intensity}]: "
            f"{asym_base}. Specific marks: {imp_str},"
        )
    else:
        parts.append(
            f"Asymmetry [L3 - {asym_intensity}]: "
            f"{asym_base}, subtly asymmetric features for individuality,"
        )

    # L9 Teeth
    teeth_intensity = recipe["L9_teeth"]
    parts.append(f"Teeth [L9 - {teeth_intensity}]: {af['teeth']}, no Hollywood-white teeth, no veneers,")

    # L11 Edge details (neck/hands)
    edge_intensity = recipe["L11_edge"]
    if edge_intensity in ("强", "极强"):
        neck_note = gender_feat.get("neck", "")
        neck_part = f" {neck_note}," if neck_note else ""
        parts.append(
            f"Edge details [L11 - {edge_intensity}]: "
            f"{af['neck_hands']},{neck_part} {gender_feat['facial_structure']},"
        )

    # L12 Muscle / expression anatomy
    expr_intensity = recipe["L5_expression"]
    parts.append(
        f"Expression tendency [L12 - {expr_intensity}]: "
        f"{expr_tend['default']}, "
        f"smile type: {expr_tend['smile_type']}, "
        f"{expr_tend['muscle_note']}, "
        f"expression transitions: {expr_tend['transition']},"
    )

    # L6 Lighting
    light_intensity = recipe["L6_lighting"]
    parts.append(
        f"Lighting [L6 - {light_intensity}]: "
        f"{scene_cfg['lighting_default']}, revealing skin texture and facial structure,"
    )

    # L7 Context
    ctx_intensity = recipe["L7_context"]
    ctx_base = scene_cfg["posture_context"]
    if has_new_fields and life_context:
        parts.append(
            f"Context [L7 - {ctx_intensity}]: "
            f"{ctx_base}, "
            f"demeanor shaped by {life_context}, "
            f"unaware of being photographed, captured in candid {realism_level} moment,"
        )
    elif appearance_keywords:
        parts.append(
            f"Context [L7 - {ctx_intensity}]: "
            f"{ctx_base}. Additional descriptors: {appearance_keywords},"
        )
    else:
        parts.append(
            f"Context [L7 - {ctx_intensity}]: "
            f"{ctx_base}, authentic candid moment,"
        )

    # L13 Breath / life signs
    breath_intensity = recipe["L13_breath"]
    if breath_intensity in ("中", "强"):
        parts.append(
            f"Life signs [L13 - {breath_intensity}]: "
            "subtle chest rise from natural breathing, natural body warmth, alive and present,"
        )

    # Clothing & posture
    clothing = scene_cfg["clothing"]
    parts.append(f"Clothing: {clothing}, natural fabric wrinkles from real wear,")
    parts.append(f"Posture: {scene_cfg['posture_context']},")

    # 随机变体因子 — 防止同参数重复出同一张脸
    _hair_vars = [
        "hair tucked behind one ear, loose strand falling across forehead",
        "hair neatly pulled back, a few wispy strands at the temples",
        "hair down and slightly disheveled from activity",
        "short practical haircut with natural part on the left",
        "hair in a loose low bun with several strands escaping",
    ]
    _eye_vars = [
        "gaze directed slightly to the left of camera, pensive",
        "direct soft eye contact with camera, calm",
        "gaze slightly downward, absorbed in thought",
        "eyes slightly narrowed in a natural Duchenne micro-smile",
        "wide open eyes, alert and present",
    ]
    _mark_vars = [
        "faint sun-darkened patch on left cheekbone from outdoor exposure",
        "very faint chicken-pox scar near right temple",
        "slight nasolabial shadow asymmetry, right side deeper",
        "one barely visible broken capillary on left nostril wing",
        "faint horizontal scar at left eyebrow from old minor injury",
    ]
    parts.append(
        f"Individuality variation: {random.choice(_hair_vars)}. "
        f"{random.choice(_eye_vars)}. "
        f"Distinguishing micro-detail: {random.choice(_mark_vars)},"
    )

    # Aura (old format support or role-derived)
    if aura:
        parts.append(f"Overall aura: {aura},")
    elif role and personality:
        parts.append(f"Overall aura: {personality} {gender_en}, role shaped by {role},")

    # ── Portrait framing (step 6.5 only) ─────────────────────────
    if for_portrait:
        parts.append(
            "Character reference portrait framing: "
            "front-facing pose, neutral relaxed expression, "
            "shoulders-up framing, looking slightly past the camera, "
            "pure pristine white seamless background, "
            "even soft-box lighting from slightly above-front, no harsh shadows, "
            "no environmental elements, clean isolated subject on white, "
            "professional character reference sheet for film production, "
            "1:1 aspect ratio,"
        )

    # ── Negative anchor ───────────────────────────────────────────
    age_neg = _AGE_SPECIFIC_NEGATIVES.get(recipe_key, "")
    negative_parts = [
        "Negative:",
        "Caucasian features, Western European face, blond hair, blue eyes, green eyes, hazel eyes, "
        "deep-set eyes, prominent brow ridge, high nasal bridge, Anglo-Saxon bone structure, "
        "South Asian features, African features, Middle Eastern features — must be Han Chinese face,",
        "AI face, plastic skin, airbrushed, smooth skin, porcelain skin, doll-like,",
        "glassy eyes, dead stare, perfect symmetry, beauty filter, instagram filter,",
        "posed expression, model pose, magazine cover, CGI, 3D render, illustration,",
        "anime, digital painting, flat lighting, even retouching light, mannequin,",
        "waxy skin, frozen body, perfect white teeth, Hollywood smile, veneers, AI teeth,",
        "identical teeth, salon-styled hair, perfect blowout, helmet hair, doll hair,",
        "broad uninhibited grin unless appropriate, theatrical satisfaction,",
        "mouth-only smile, smile without eye engagement, frozen forehead, botox look,",
    ]
    if age_neg:
        negative_parts.append(age_neg + ",")
    if gender_en == "male":
        negative_parts.append("feminine facial structure on male subject,")

    parts.extend(negative_parts)

    return "\n".join(parts)
