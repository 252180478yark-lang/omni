from __future__ import annotations

from copy import deepcopy

import pytest

from app.services import video_production_vector_match as p0vm


def _truth(*, with_portrait: bool = True) -> dict:
    return {
        "sku": {"id": "SKU-1", "name": "Kitchen soy sauce"},
        "audience_record": {
            "name": "Practical home cook",
            "raw_md_segment": "A practical home cook wants a reliable weekday dinner in a family kitchen.",
            "match_reasons": ["weekday dinner", "family kitchen", "practical value"],
            "layer_tags": ["food", "home"],
        },
        "audience_portrait": (
            {"portrait_md": "After work, this family-oriented cook wants a dependable home dinner with practical value."}
            if with_portrait
            else None
        ),
        "product_reference_manifest": {"assets": [{"id": "ref-1"}]},
    }


def _spec() -> dict:
    return {
        "duration_seconds": 12,
        "visual_constraints": ["9:16", "one person", "one kitchen"],
        "audio_constraints": ["clear spoken copy", "natural kitchen sound"],
    }


def _candidate() -> dict:
    return {
        "opening_hook_3s": "After work, dinner still deserves care.",
        "body": "In a familiar home kitchen, the cook finishes a warm dish with one clear seasoning action.",
        "spoken_copy": "For a weekday dinner, I keep the last step simple and make the family meal feel reliable.",
        "beat_plan": [
            {
                "start_seconds": 0,
                "end_seconds": 3,
                "visual": "The cook enters the familiar kitchen.",
                "action": "Start the stove.",
                "spoken_copy": "",
                "sound": "Natural kitchen ambience.",
            },
            {
                "start_seconds": 3,
                "end_seconds": 6,
                "visual": "Ingredients are stirred in a hand close-up.",
                "action": "Stir the dinner.",
                "spoken_copy": "For a weekday dinner, I keep the",
                "sound": "Pan and spatula sound.",
            },
            {
                "start_seconds": 6,
                "end_seconds": 9,
                "visual": "The product, hand and dish stay in one frame.",
                "action": "Add the soy sauce before plating.",
                "spoken_copy": "last step simple and make the family",
                "sound": "Cooking sound.",
            },
            {
                "start_seconds": 9,
                "end_seconds": 12,
                "visual": "The warm finished dinner is placed on the table.",
                "action": "Serve the dinner.",
                "spoken_copy": "meal feel reliable.",
                "sound": "Light tableware sound.",
            },
        ],
        "product_action": "Add the soy sauce before plating.",
        "duration_seconds": 12,
    }


def _pain_solution_bridge() -> dict:
    """A structured P0 bridge used only to exercise the formal gate."""

    return {
        "audience_segment": "family dinner cooks",
        "trigger_scene": "weekday dinner before plating",
        "pain_point": "the meal is nearly done but still tastes unfinished",
        "pain_consequence": "the family dinner feels rushed and flat",
        "product_action": "add soy sauce before plating",
        "visible_result": "the hot dish is glazed and ready for the table",
        "belief_shift": "a careful finish does not need a complicated recipe",
        "relevance_module": "M1",
        "justification_module": "M3",
        "portrait_evidence": [],
        "pack_calibration_evidence": [],
        "product_evidence": [
            {"source": "sku", "field": "name", "value": "Kitchen soy sauce"}
        ],
    }


def _vector(text: str) -> list[float]:
    lowered = text.lower()
    return [
        1.0 if "family" in lowered or "home" in lowered else 0.2,
        1.0 if "kitchen" in lowered or "dinner" in lowered else 0.2,
        1.0 if "sound" in lowered or "spoken" in lowered else 0.2,
    ]


@pytest.mark.asyncio
async def test_p0_vector_match_reads_actual_prompt_source_not_algorithm_notes(monkeypatch):
    async def fake_embed(texts, model=None, provider=None):
        return [_vector(text) for text in texts]

    monkeypatch.setattr(p0vm, "embed_texts", fake_embed)
    candidate = _candidate()
    preview = p0vm.candidate_prompt_preview(
        candidate=candidate,
        spec=_spec(),
        truth_snapshot=_truth(),
    )
    changed_metadata = deepcopy(candidate)
    changed_metadata["algorithm_signal_notes"] = "unrelated extra metadata must not affect the executable source"
    same_preview = p0vm.candidate_prompt_preview(
        candidate=changed_metadata,
        spec=_spec(),
        truth_snapshot=_truth(),
    )

    first = await p0vm.assess_execution_vector_match(
        execution=preview,
        truth_snapshot=_truth(),
    )
    second = await p0vm.assess_execution_vector_match(
        execution=same_preview,
        truth_snapshot=_truth(),
    )

    assert preview["execution_source_hash"] == same_preview["execution_source_hash"]
    assert first["report"]["status"] == "scored"
    assert first["report"]["scores"] == second["report"]["scores"]
    assert first["report"]["overall_score"] == second["report"]["overall_score"]
    assert set(first["report"]["scores"]) == {"text", "visual", "music"}
    # audience identity is not injected into the visual execution track merely
    # to make a semantic score look higher.
    assert "Practical home cook" not in first["report"]["execution_evidence"]["visual"]["excerpt"]


def test_p0_vector_match_uses_frozen_record_when_portrait_is_absent():
    source = p0vm.audience_source_from_truth(_truth(with_portrait=False))

    assert source["ok"] is True
    assert source["kind"] == "record_fallback"
    assert "Practical home cook" in source["text"]


def test_p0_v4_vector_match_refuses_record_fallback_when_portrait_is_absent():
    source = p0vm.audience_source_from_truth(
        _truth(with_portrait=False),
        require_frozen_portrait=True,
    )

    assert source == {
        "ok": False,
        "error": "frozen_audience_portrait_required",
        "kind": "portrait_required",
    }


@pytest.mark.asyncio
async def test_p0_v4_vector_match_attaches_formal_five_dimension_gate(monkeypatch):
    async def fake_embed(texts, model=None, provider=None):
        return [_vector(text) for text in texts]

    monkeypatch.setattr(p0vm, "embed_texts", fake_embed)
    preview = p0vm.candidate_prompt_preview(
        candidate=_candidate(),
        spec=_spec(),
        truth_snapshot=_truth(),
    )
    result = await p0vm.assess_execution_vector_match(
        execution=preview,
        truth_snapshot=_truth(),
        require_frozen_portrait=True,
        pain_solution_bridge=_pain_solution_bridge(),
        duration_seconds=12,
    )

    assert result["ok"] is True
    report = result["report"]
    assert report["status"] == "scored"
    assert report["audience_source_kind"] == "portrait"
    formal_gate = report["formal_pre_video_vector_gate"]
    assert formal_gate is not None
    assert formal_gate["stage"] == "pre_video"
    assert formal_gate["key_vector_dimensions"] == [
        "audience_scene",
        "pain_conflict",
        "product_action",
        "result_relief",
        "justification_evidence",
    ]
    assert formal_gate["segment_results"][0]["segment_id"] == "p0_raw"


def test_p0_v4_vector_facts_bind_frozen_pack_and_selected_pack_evidence():
    truth = _truth()
    truth["planting_bridge_context"] = {
        "facts": {
            "pack_calibration": {
                "id": "pack-1",
                "pack_md": "下班后认真做饭的家庭烹饪偏好",
            }
        }
    }
    bridge = _pain_solution_bridge()
    bridge["pack_calibration_evidence"] = [
        {"field": "pack_md", "value": "家庭晚餐优先看见锅气和上色"}
    ]

    dimensions = p0vm.formal_planting_dimension_facts(
        truth_snapshot=truth,
        pain_solution_bridge=bridge,
    )

    assert "下班后认真做饭的家庭烹饪偏好" in dimensions["audience_scene"]
    assert "家庭晚餐优先看见锅气和上色" in dimensions["audience_scene"]
    assert "家庭晚餐优先看见锅气和上色" in dimensions["justification_evidence"]


@pytest.mark.asyncio
async def test_p0_vector_match_records_unscored_when_embedding_is_unavailable(monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("embedding service unavailable")

    monkeypatch.setattr(p0vm, "embed_texts", unavailable)
    preview = p0vm.candidate_prompt_preview(
        candidate=_candidate(),
        spec=_spec(),
        truth_snapshot=_truth(),
    )
    result = await p0vm.assess_execution_vector_match(
        execution=preview,
        truth_snapshot=_truth(),
    )

    assert result["ok"] is True
    assert result["report"]["status"] == "unscored"
    assert result["report"]["error"] == "embedding_unavailable"
    assert result["report"]["scores"] == {}
