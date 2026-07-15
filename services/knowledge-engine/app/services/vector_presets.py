"""投前向量预设库：在 creative_pack 生成前先选元素，再让脚本承接。

这层只做冷启动排序，不判断 winner；winner 仍然只认投后北极星。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import numpy as np

from app.config import settings
from app.services.embedding_client import embed_texts

_LANE_OUTPUT_WEIGHTS = {
    "visual": 0.40,
    "text": 0.35,
    "product_action": 0.20,
    "sound": 0.05,
}

_LANE_ANCHOR_WEIGHTS = {
    "visual": {"audience": 0.35, "scene": 0.35, "selling_point": 0.15, "product": 0.15},
    "text": {"audience": 0.45, "scene": 0.20, "selling_point": 0.25, "product": 0.10},
    "sound": {"audience": 0.50, "scene": 0.30, "selling_point": 0.05, "product": 0.15},
    "product_action": {
        "audience": 0.25,
        "scene": 0.25,
        "selling_point": 0.25,
        "product": 0.25,
    },
}

_DEFAULT_CANDIDATES = {
    "visual": [
        "使用上游人群事实中的日常场景，人物穿着、空间和物件保持真实一致",
        "产品自然处在实际使用动线内，不悬浮、不突然出现，也不遮挡人物动作",
        "镜头依次呈现使用前状态、一次清楚使用动作和可见结果",
        "手机直拍质感，人物与环境细节来自所给画像或参考资料，不做影棚摆拍",
        "同一人物、产品外观和空间位置连续，不在镜头间无依据改变",
    ],
    "text": [
        "用画像中的具体时刻说出问题，不用空泛身份标签代替真实处境",
        "产品出现时只说已核验的作用，不新增功效、资质、价格或承诺",
        "用一次可观察的变化说明结果，让画面承担证据而不是口号",
        "表达贴近目标人群日常用语，避免广告腔和强行叫卖",
        "结尾回到使用后的生活状态，不制造未经证实的夸张评价",
    ],
    "sound": [
        "保留所给场景内真实可发生的环境声和产品接触声",
        "低存在感生活流声音，不用强情绪音乐替代内容信息",
        "对白、环境声和动作声按实际发生顺序出现，不与画面错位",
    ],
    "product_action": [
        "人物从固定位置拿起产品，完成一种符合产品事实的真实使用动作",
        "产品必须真实接触适用对象或作用位置，不能只靠字幕或后期贴图表示使用",
        "产品外观严格按参考资料，不编造包装、结构、标签、配件或使用方式",
        "使用后展示可见结果并把产品放回稳定位置，保持动作和物件连续",
    ],
}


def _emb_model() -> str:
    return getattr(settings, "embedding_model", "gemini-embedding-2-preview")


def _emb_provider() -> str | None:
    return getattr(settings, "embedding_provider", "gemini")


def _profile_value(profile: object, key: str, default: Any = None) -> Any:
    if isinstance(profile, Mapping):
        return profile.get(key, default)
    return getattr(profile, key, default)


def _clip(text: str, limit: int = 2400) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text[:limit]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _context_lines(text: str) -> list[str]:
    raw = re.split(r"[\n。；;.!?？]+", text or "")
    lines: list[str] = []
    seen: set[str] = set()
    for item in raw:
        s = re.sub(r"^[\s>*#\-\d.、|]+", "", item).strip()
        s = re.sub(r"\s+", " ", s)
        if 6 <= len(s) <= 90 and s not in seen:
            seen.add(s)
            lines.append(s)
    return lines


def _pick_lines(
    lines: list[str], keywords: tuple[str, ...], limit: int = 10
) -> list[str]:
    picked = [line for line in lines if any(k in line for k in keywords)]
    return picked[:limit]


def _infer_action_chain(text: str) -> list[str]:
    """Use a food action chain only when food facts are actually supplied."""
    t = text or ""
    if any(k in t for k in ("面条", "拌面", "汤面", "煮面")):
        return [
            "锅里食物已经处于可见熟化状态，不拍从生到熟的复杂变化",
            "人物把面盛入碗里或把碗放到固定餐桌位置",
            "人物少量倒入产品，镜头看清液体进入碗内而不是凭空变色",
            "人物用筷子或勺子搅拌 1-2 圈，食物状态连续变化",
            "家人入口品尝，产品回到桌边或灶台边",
        ]
    if any(k in t for k in ("饺子", "馄饨", "包子", "蘸")):
        return [
            "食物已经在盘中或碗中，不拍复杂烹饪过程",
            "人物把产品少量倒入真实小碟或碗边",
            "筷子夹起食物，蘸取动作清楚且不夸张",
            "家人入口品尝，碟子和产品位置不跳变",
            "产品留在餐桌边，成为常备调味品",
        ]
    if any(k in t for k in ("凉拌", "拌菜", "黄瓜", "蔬菜", "沙拉")):
        return [
            "食材已经切好放在碗里，不拍刀具高速切菜",
            "人物少量倒入产品，液体真实接触食材",
            "人物用筷子或夹子翻拌 1-2 次，食材位置连续变化",
            "家人夹一口品尝，产品放回桌边",
        ]
    if any(k in t for k in ("炒", "锅", "菜", "灶")):
        return [
            "锅中菜已经半熟，人物只做一次可控调味动作",
            "产品靠近灶台但不遮挡火源，少量倒入锅边",
            "人物用锅铲翻动 1-2 下，食材和锅位保持连续",
            "菜盛出到盘中，产品回到灶台边",
        ]
    return [
        "先呈现上游事实明确的问题状态，不新增未经提供的场景或人物",
        "人物从固定位置拿起外观一致的产品",
        "人物完成一次符合产品说明或参考资料的真实使用动作",
        "画面展示可观察结果，产品和人物保持在连续空间内",
    ]


def _build_reality_constraints(
    *,
    sku_md: str,
    matrix_md: str,
    audience_md: str,
    audience_pack_summary: str,
    extra_context: str,
) -> dict[str, Any]:
    all_context = "\n".join(
        [sku_md, matrix_md, audience_md, audience_pack_summary, extra_context]
    )
    lines = _context_lines(all_context)
    allow = _pick_lines(
        lines,
        (
            "场景",
            "空间",
            "人物",
            "家庭",
            "上班",
            "浴室",
            "客厅",
            "卧室",
            "办公室",
            "户外",
            "厨房",
            "餐桌",
        ),
        8,
    )
    visual_allowlist = allow or [
        "只使用上游人群画像或补充事实明确给出的场景",
        "人物年龄、关系、穿着和活动必须有上游事实依据",
        "只保留与真实使用动作有关的环境物件",
        "产品外观、结构和作用对象以参考资料为准",
    ]
    visual_blocklist = [
        "无依据制服、工牌、公司字样、衣服 logo、乱码文字",
        "豪华样板间、影棚广告光、电影感摆拍",
        "第三个无关成年人、陌生路人、突然换脸换衣服",
        "其他品牌产品、竞品外观、可识别第三方包装或第三方 logo",
        "产品漂浮贴片、外观变形、标签乱码、错误规格或无依据配件",
    ]
    return {
        "visual_allowlist": visual_allowlist[:8],
        "visual_blocklist": visual_blocklist,
        "action_chain": _infer_action_chain(all_context),
        "shot_complexity_rules": [
            "每 3-5 秒只推进一个清楚动作，避免一段里同时堆叠多个使用步骤和对白",
            "每个镜头最多 2 个固定人物，除非人群画像明确需要更多人",
            "同一条片尽量固定一个上游事实明确的空间，物件位置不得跳变",
            "产品完成真实、可见且符合说明的作用动作才算使用，不能只靠字幕或贴图冒充",
        ],
    }


def _build_anchors(
    *,
    sku_md: str,
    matrix_md: str,
    audience_md: str,
    audience_pack_summary: str,
    extra_context: str,
) -> dict[str, str]:
    all_context = "\n".join(
        [sku_md, matrix_md, audience_md, audience_pack_summary, extra_context]
    )
    lines = _context_lines(all_context)
    scene = "\n".join(
        _pick_lines(
            lines,
            ("场景", "地点", "时间", "使用", "生活", "环境", "人物", "人群"),
            16,
        )
    )
    selling = "\n".join(
        _pick_lines(
            lines,
            ("卖点", "作用", "效果", "结果", "痛点", "证据", "利益", "方便"),
            16,
        )
    )
    product = "\n".join(
        _pick_lines(
            lines,
            ("SKU", "品名", "规格", "产品", "包装", "参考", "成分", "材质"),
            16,
        )
    )
    return {
        "audience": _clip(
            "\n".join([audience_md, audience_pack_summary, extra_context])
        ),
        "scene": _clip(scene or audience_md or all_context),
        "selling_point": _clip(selling or matrix_md or sku_md),
        "product": _clip(product or sku_md or matrix_md),
    }


def _build_candidates(
    *,
    sku_md: str,
    matrix_md: str,
    audience_md: str,
    audience_pack_summary: str,
    extra_context: str,
) -> list[dict[str, str]]:
    all_context = "\n".join(
        [sku_md, matrix_md, audience_md, audience_pack_summary, extra_context]
    )
    lines = _context_lines(all_context)
    lane_keywords = {
        "visual": ("画面", "场景", "空间", "人物", "外观", "产品", "参考", "使用"),
        "text": ("文案", "字幕", "话题", "痛点", "卖点", "结果", "人群", "表达"),
        "sound": ("声音", "音乐", "BGM", "环境音", "对白", "音效", "白噪音"),
        "product_action": ("动作", "使用", "接触", "产品", "参考", "说明", "结果"),
    }
    candidates: list[dict[str, str]] = []
    for lane, defaults in _DEFAULT_CANDIDATES.items():
        lane_items = list(defaults)
        lane_items.extend(_pick_lines(lines, lane_keywords[lane], 12))
        seen: set[str] = set()
        for idx, text in enumerate(lane_items, start=1):
            clean = _clip(text, 220)
            if not clean or clean in seen:
                continue
            seen.add(clean)
            candidates.append(
                {
                    "id": f"{lane}_{idx}",
                    "lane": lane,
                    "text": clean,
                    "source": "default+context" if idx <= len(defaults) else "context",
                }
            )
    return candidates


def _score_candidate(
    vec: np.ndarray,
    anchors: dict[str, np.ndarray],
    lane: str,
    *,
    formal_profile: bool = False,
) -> dict[str, float]:
    parts = {name: _cosine(vec, anchor_vec) for name, anchor_vec in anchors.items()}
    if formal_profile:
        composite = sum(parts.values()) / len(parts) if parts else 0.0
    else:
        weights = _LANE_ANCHOR_WEIGHTS[lane]
        composite = sum(parts[name] * weights[name] for name in weights)
    parts["composite"] = composite
    return {k: round(float(v), 4) for k, v in parts.items()}


def _render_markdown(preset: dict[str, Any]) -> str:
    lines = [
        "## 投前向量预设库",
        "",
        f"- kind：`{preset['kind']}`；intent：`{preset['intent']}`",
        f"- 预设加权分：{preset['score_100']:.1f}/100（生成前冷启动排序分，不等于投后 winner）",
        "- 生成要求：脚本必须优先承接下面 baseline 元素；如果创意要改，只能替换同一路候选，不能跨变量乱改。",
        "",
    ]
    lane_names = {
        "visual": "画面",
        "text": "文案",
        "sound": "声音",
        "product_action": "产品动作",
    }
    for lane in ("visual", "text", "product_action", "sound"):
        lines.append(f"### {lane_names[lane]}候选（{lane}）")
        for item in preset["lanes"].get(lane, [])[:6]:
            lines.append(
                f"- [{item['id']}] {item['text']}（分：{item['score_100']:.1f}）"
            )
        lines.append("")
    baseline = preset["state_machine_seed"]["baseline"]
    reality = preset.get("reality_constraints") or {}
    lines.extend(
        [
            "### 单变量测试种子",
            f"- baseline.visual_vector：{baseline.get('visual')}",
            f"- baseline.text_vector：{baseline.get('text')}",
            f"- baseline.product_action：{baseline.get('product_action')}",
            f"- baseline.sound_vector：{baseline.get('sound')}",
            "- allowed_sweeps：visual_vector / text_vector / product_action / sound_vector，每轮只改一个。",
            "",
            "### 现实物理约束（出片前硬闸）",
            "- 入画白名单：" + "；".join((reality.get("visual_allowlist") or [])[:6]),
            "- 禁用漂移：" + "；".join((reality.get("visual_blocklist") or [])[:6]),
            "- 动作连续链：" + " → ".join(reality.get("action_chain") or []),
            "- 镜头复杂度："
            + "；".join((reality.get("shot_complexity_rules") or [])[:4]),
        ]
    )
    return "\n".join(lines).strip()


async def build_creative_vector_preset(
    *,
    kind: str,
    sku_md: str,
    matrix_md: str,
    audience_md: str,
    audience_pack_summary: str,
    extra_context: str | None = None,
    intent: str = "generic",
    profile: object | None = None,
    lineage_anchors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build candidate lanes from explicit facts for cold-start ordering."""
    extra = extra_context or ""
    formal_profile = profile is not None
    if formal_profile:
        profile_version = _profile_value(profile, "version")
        profile_kind = _profile_value(profile, "kind")
        profile_intent = _profile_value(profile, "intent")
        if profile_kind != kind or profile_intent != intent:
            return {
                "ok": False,
                "error": "vector_profile_mismatch",
                "profile_version": profile_version,
                "expected_kind": profile_kind,
                "expected_intent": profile_intent,
                "actual_kind": kind,
                "actual_intent": intent,
            }
        key_dimensions = tuple(_profile_value(profile, "key_vector_dimensions", ()))
        supplied_anchors = (
            lineage_anchors if isinstance(lineage_anchors, Mapping) else {}
        )
        missing = [
            name
            for name in key_dimensions
            if not isinstance(supplied_anchors.get(name), str)
            or not supplied_anchors[name].strip()
        ]
        if missing:
            return {
                "ok": False,
                "error": "missing_vector_anchors",
                "missing": missing,
                "profile_version": profile_version,
            }
        anchors_text = {name: supplied_anchors[name] for name in key_dimensions}
        vector_threshold_100 = _profile_value(profile, "vector_threshold_100")
        legacy_warning = None
    else:
        profile_version = None
        anchors_text = _build_anchors(
            sku_md=sku_md,
            matrix_md=matrix_md,
            audience_md=audience_md,
            audience_pack_summary=audience_pack_summary,
            extra_context=extra,
        )
        key_dimensions = tuple(anchors_text)
        vector_threshold_100 = None
        legacy_warning = (
            "Legacy inferred anchors are readable for compatibility but do not "
            "satisfy the versioned vector contract."
        )
    reality_constraints = _build_reality_constraints(
        sku_md=sku_md,
        matrix_md=matrix_md,
        audience_md=audience_md,
        audience_pack_summary=audience_pack_summary,
        extra_context=extra,
    )
    candidates = _build_candidates(
        sku_md=sku_md,
        matrix_md=matrix_md,
        audience_md=audience_md,
        audience_pack_summary=audience_pack_summary,
        extra_context=extra,
    )
    if not candidates:
        return {"ok": False, "error": "no_candidates"}

    anchor_keys = list(anchors_text)
    texts = [anchors_text[k] for k in anchor_keys] + [c["text"] for c in candidates]
    vecs = await embed_texts(texts, model=_emb_model(), provider=_emb_provider())
    anchor_vecs = {
        k: np.array(v, dtype=np.float32)
        for k, v in zip(anchor_keys, vecs[: len(anchor_keys)])
    }
    candidate_vecs = vecs[len(anchor_keys) :]

    lanes: dict[str, list[dict[str, Any]]] = {lane: [] for lane in _LANE_OUTPUT_WEIGHTS}
    for c, vec in zip(candidates, candidate_vecs):
        scores = _score_candidate(
            np.array(vec, dtype=np.float32),
            anchor_vecs,
            c["lane"],
            formal_profile=formal_profile,
        )
        item = {
            **c,
            "score": scores["composite"],
            "score_100": round(scores["composite"] * 100, 1),
            "scores": scores,
        }
        lanes[c["lane"]].append(item)
    for lane in lanes:
        lanes[lane].sort(key=lambda x: x["score"], reverse=True)
        lanes[lane] = lanes[lane][:8]

    lane_scores: dict[str, float] = {}
    for lane, items in lanes.items():
        top = items[:3]
        lane_scores[lane] = (
            round(sum(i["score"] for i in top) / len(top), 4) if top else 0.0
        )
    overall = sum(
        lane_scores[lane] * _LANE_OUTPUT_WEIGHTS[lane] for lane in _LANE_OUTPUT_WEIGHTS
    )

    baseline = {
        lane: (lanes[lane][0]["text"] if lanes.get(lane) else None)
        for lane in ("visual", "text", "product_action", "sound")
    }
    sweeps = []
    variable_name = {
        "visual": "visual_vector",
        "text": "text_vector",
        "product_action": "product_action",
        "sound": "sound_vector",
    }
    for lane in ("visual", "text", "product_action", "sound"):
        sweeps.append(
            {
                "variable": variable_name[lane],
                "candidate_values": [
                    {"id": item["id"], "value": item["text"], "score": item["score"]}
                    for item in lanes.get(lane, [])[:5]
                ],
            }
        )

    preset: dict[str, Any] = {
        "ok": True,
        "kind": kind,
        "intent": intent,
        "profile_version": profile_version,
        "vector_threshold_100": vector_threshold_100,
        "key_vector_dimensions": list(key_dimensions),
        "legacy_warning": legacy_warning,
        "lanes": lanes,
        "lane_scores": lane_scores,
        "overall_score": round(overall, 4),
        "score_100": round(overall * 100, 1),
        "anchors": anchors_text,
        "state_machine_seed": {
            "baseline": baseline,
            "allowed_sweeps": sweeps,
            "reality_constraints": reality_constraints,
            "single_variable_rule": "每轮只改 allowed_sweeps 中一个 variable，其余 baseline 不动。",
        },
        "reality_constraints": reality_constraints,
        "disclaimer": "投前向量预设分只用于生成前排序和 A/B 起点；winner 仍只认投后北极星。",
    }
    preset["markdown"] = _render_markdown(preset)
    return preset
