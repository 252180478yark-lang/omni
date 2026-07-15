"""投前向量预设库：先选画面/文案/声音/产品动作候选，再交给 creative_pack 生成。"""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.mcp import prompts
from app.services import vector_presets
from app.services.video_intent_profiles import get_video_intent_profile


def _vec(text: str) -> list[float]:
    score_family = (
        1.0 if any(k in text for k in ("家庭", "父亲", "孩子", "家人")) else 0.2
    )
    score_product = (
        1.0 if any(k in text for k in ("小瓶", "酱油", "味碟", "蘸")) else 0.2
    )
    score_scene = (
        1.0 if any(k in text for k in ("餐桌", "厨房", "下班", "饺子")) else 0.2
    )
    return [score_family, score_product, score_scene]


@pytest.mark.asyncio
async def test_build_creative_vector_preset_outputs_lanes_and_state_machine_seed(
    monkeypatch,
):
    async def fake_embed(texts, model=None, provider=None):
        return [_vec(t) for t in texts]

    monkeypatch.setattr(vector_presets, "embed_texts", fake_embed)

    preset = await vector_presets.build_creative_vector_preset(
        kind="video_soft_ad",
        sku_md="- 品名：和田宽有机本酿造特级酱油\n- 老板自填卖点：小瓶方便，有机本酿造，蘸饺子合适",
        matrix_md="1.1 小瓶方便：餐桌味碟顺手倒。1.2 老牌子踏实：家人吃着放心。",
        audience_md="- 人群名：舒适休闲男性\n- KB 原文画像：31-35岁父亲，下班回家，家庭餐桌，孩子，速冻饺子。",
        audience_pack_summary="圈包摘要：家庭生活、下班晚餐、调味品兴趣。",
        extra_context="软广，不要硬卖。",
        intent="soft_ad",
    )

    assert preset["ok"] is True
    assert set(preset["lanes"]) == {"visual", "text", "sound", "product_action"}
    assert preset["overall_score"] > 0
    assert preset["state_machine_seed"]["baseline"]["visual"]
    assert preset["state_machine_seed"]["baseline"]["text"]
    assert "reality_constraints" in preset
    assert "动作连续链" in preset["markdown"]
    assert any(
        "倒入" in x or "接触" in x
        for x in preset["reality_constraints"]["action_chain"]
    )
    assert any("竞品" in x for x in preset["reality_constraints"]["visual_blocklist"])
    assert preset["state_machine_seed"]["allowed_sweeps"][0]["variable"] in {
        "visual_vector",
        "text_vector",
        "sound_vector",
        "product_action",
    }
    assert "投前向量预设库" in preset["markdown"]
    assert "单变量测试种子" in preset["markdown"]
    assert preset["legacy_warning"]


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["planting", "soft_ad"])
async def test_formal_profile_requires_every_explicit_anchor_before_embedding(
    monkeypatch, intent
):
    profile = get_video_intent_profile(intent)
    calls = 0

    async def forbidden_embed(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("missing anchors must fail before embedding")

    monkeypatch.setattr(vector_presets, "embed_texts", forbidden_embed)
    complete = {name: f"explicit {name}" for name in profile.key_vector_dimensions}

    for missing_name in profile.key_vector_dimensions:
        anchors = {**complete, missing_name: "   "}
        result = await vector_presets.build_creative_vector_preset(
            kind=profile.kind,
            intent=profile.intent,
            profile=profile,
            lineage_anchors=anchors,
            sku_md="neutral product",
            matrix_md="verified benefit",
            audience_md="selected audience",
            audience_pack_summary="",
        )
        assert result == {
            "ok": False,
            "error": "missing_vector_anchors",
            "missing": [missing_name],
            "profile_version": profile.version,
        }

    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "kind"),
    [("soft_ad", "video_planting"), ("planting", "video_soft_ad")],
)
async def test_formal_profile_rejects_kind_or_intent_mismatch(
    monkeypatch, intent, kind
):
    profile = get_video_intent_profile("planting")

    async def forbidden_embed(*_args, **_kwargs):
        raise AssertionError("profile mismatch must fail before embedding")

    monkeypatch.setattr(vector_presets, "embed_texts", forbidden_embed)
    result = await vector_presets.build_creative_vector_preset(
        kind=kind,
        intent=intent,
        profile=profile,
        lineage_anchors={name: name for name in profile.key_vector_dimensions},
        sku_md="neutral product",
        matrix_md="verified benefit",
        audience_md="selected audience",
        audience_pack_summary="",
    )

    assert result["ok"] is False
    assert result["error"] == "vector_profile_mismatch"
    assert result["profile_version"] == profile.version


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["planting", "soft_ad"])
async def test_formal_profile_uses_exact_dimensions_and_neutral_candidates(
    monkeypatch, intent
):
    profile = get_video_intent_profile(intent)
    anchors = {
        name: f"{name}：都市租住人群使用无香清洁凝胶后的可见整洁结果"
        for name in profile.key_vector_dimensions
    }
    original = deepcopy(anchors)
    embedded_batches = []

    async def fake_embed(texts, model=None, provider=None):
        embedded_batches.append(list(texts))
        return [[1.0, 0.5, 0.25] for _ in texts]

    monkeypatch.setattr(vector_presets, "embed_texts", fake_embed)
    preset = await vector_presets.build_creative_vector_preset(
        kind=profile.kind,
        intent=profile.intent,
        profile=profile,
        lineage_anchors=anchors,
        sku_md="品名：无香多用途清洁凝胶；规格：300克",
        matrix_md="卖点：擦拭后表面不黏手；证据：产品使用说明",
        audience_md="人群：租房独居、在意收纳效率的上班族",
        audience_pack_summary="生活空间较小，日常整理时间有限",
        extra_context="场景为浴室台面，严格使用所给产品参考事实",
    )

    assert preset["ok"] is True
    assert anchors == original
    assert preset["anchors"] == original
    assert preset["profile_version"] == profile.version
    assert preset["vector_threshold_100"] == profile.vector_threshold_100
    assert preset["key_vector_dimensions"] == list(profile.key_vector_dimensions)
    assert preset.get("legacy_warning") is None
    assert embedded_batches[0][: len(anchors)] == list(anchors.values())
    first_item = next(iter(preset["lanes"]["visual"]))
    assert set(first_item["scores"]) == {*profile.key_vector_dimensions, "composite"}
    rendered = json.dumps(preset, ensure_ascii=False)
    for leaked in ("酱油", "小瓶", "饺子", "舒适休闲", "调味品", "味碟"):
        assert leaked not in rendered


@pytest.mark.asyncio
async def test_planting_and_soft_ad_formal_dimension_sets_remain_distinct(monkeypatch):
    async def fake_embed(texts, model=None, provider=None):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(vector_presets, "embed_texts", fake_embed)
    results = {}
    for intent in ("planting", "soft_ad"):
        profile = get_video_intent_profile(intent)
        results[intent] = await vector_presets.build_creative_vector_preset(
            kind=profile.kind,
            intent=profile.intent,
            profile=profile,
            lineage_anchors={
                name: f"explicit {name}" for name in profile.key_vector_dimensions
            },
            sku_md="skin cleanser",
            matrix_md="verified gentle cleansing",
            audience_md="sensitive-skin audience",
            audience_pack_summary="",
        )

    assert results["planting"]["key_vector_dimensions"] == [
        "audience_scene",
        "pain_conflict",
        "product_action",
        "result_relief",
        "justification_evidence",
    ]
    assert results["soft_ad"]["key_vector_dimensions"] == [
        "audience_scene",
        "product_action",
        "watchability",
    ]


def test_creative_pack_user_prompt_includes_vector_preset_md():
    prompts.invalidate("creative_pack.user")
    rendered = prompts.render(
        "creative_pack.user",
        experiment_constraint="",
        kind="video_soft_ad",
        kind_label="视频软广",
        sku_md="- SKU id：SKU-X",
        matrix_md="1.1 小瓶方便",
        audience_md="- 人群名：测试人群",
        audience_pack_summary="圈包摘要",
        vector_preset_md="## 投前向量预设库\n- visual: 家庭餐桌，小瓶酱油",
        extra_context="（无）",
        target_model_profile="Seedance 档案",
    )

    assert "## 投前向量预设库" in rendered
    assert "家庭餐桌，小瓶酱油" in rendered
    assert "现实物理约束" in rendered
