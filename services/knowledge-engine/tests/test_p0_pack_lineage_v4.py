from __future__ import annotations

import pytest

from app.services import video_production_orders as orders
from app.services.pain_solution_bridge import canonical_upstream_fact_hash
from app.services.video_production_contract import (
    P0_CONTRACT_VERSION,
    P0_V3_CONTRACT_VERSION,
    validate_content_spec,
    validate_truth_snapshot,
)


SKU_ID = "SKU-PACK-1"
RECORD_ID = "00000000-0000-0000-0000-000000000101"
PORTRAIT_ID = "00000000-0000-0000-0000-000000000102"
PACK_ID = "00000000-0000-0000-0000-000000000103"


def _facts(*, pack_id: str | None = PACK_ID) -> dict:
    pack = (
        {"id": pack_id, "pack_md": "下班后认真做饭", "dmp_tags": "家庭烹饪"}
        if pack_id
        else None
    )
    pack_catalog = (
        {"pack_md": "下班后认真做饭", "dmp_tags": "家庭烹饪"}
        if pack_id
        else {}
    )
    return {
        "lineage": {
            "sku_id": SKU_ID,
            "matrix_run_id": "00000000-0000-0000-0000-000000000104",
            "audience_run_id": "00000000-0000-0000-0000-000000000105",
            "audience_record_id": RECORD_ID,
            "portrait_id": PORTRAIT_ID,
            "audience_pack_id": pack_id,
        },
        "sku_facts": {"id": SKU_ID, "owner_selling_points": ["有机酿造"]},
        "matrix_evidence": {"id": "00000000-0000-0000-0000-000000000104", "matrix_md": "酿造事实"},
        "portrait_record_evidence": {
            "record": {"id": RECORD_ID, "name": "烟火寻味家"},
            "portrait": {
                "id": PORTRAIT_ID,
                "portrait_md": "下班也愿意认真做一顿饭 [KB: test]",
            },
        },
        "pack_calibration": pack,
        "eligible_evidence_catalog": {
            "sku": {"owner_selling_points": "有机酿造"},
            "matrix": {"matrix_md": "酿造事实"},
            "record": {"name": "烟火寻味家"},
            "portrait": {"portrait_md": "下班也愿意认真做一顿饭 [KB: test]"},
        },
        "pack_calibration_catalog": pack_catalog,
    }


def _snapshot(*, version: str = P0_CONTRACT_VERSION, pack_id: str | None = PACK_ID) -> dict:
    facts = _facts(pack_id=pack_id)
    catalog = dict(facts["eligible_evidence_catalog"])
    if facts["pack_calibration_catalog"]:
        catalog["pack"] = facts["pack_calibration_catalog"]
    return {
        "contract_version": version,
        "sku": {"id": SKU_ID, "name": "酱油"},
        "audience_record": {"id": RECORD_ID},
        "audience_portrait": {
            "id": PORTRAIT_ID,
            "sku_id": SKU_ID,
            "audience_record_id": RECORD_ID,
            "portrait_md": "下班也愿意认真做一顿饭 [KB: test]",
            "status": "adopted",
        },
        "product_reference_manifest": {"assets": [{"id": "ref-1", "file_url": "/ref.png"}]},
        "facts": {"whitelist": ["有机酿造"]},
        "planting_bridge_context": {
            "facts": facts,
            "eligible_evidence_catalog": catalog,
            "require_pack_evidence": bool(pack_id),
            "upstream_fact_hash": canonical_upstream_fact_hash(facts),
        },
    }


def _bridge(*, pack_evidence: list[dict] | None = None) -> dict:
    return {
        "audience_segment": "下班认真做饭的人",
        "trigger_scene": "工作日晚上起锅前",
        "pain_point": "下班也愿意认真做一顿饭时，担心调味选择没有明确依据",
        "pain_consequence": "下班也愿意认真做一顿饭时会反复查看配料表、迟迟不下锅",
        "product_action": "把“有机酿造”的酱油沿锅边倒入",
        "visible_result": "镜头特写“有机酿造”的瓶身，随后拍到沿锅边倒入",
        "belief_shift": "从下班也愿意认真做一顿饭时的担心，到先确认“有机酿造”再决定下锅",
        "relevance_module": "M1",
        "justification_module": "M3",
        "portrait_evidence": [
            {"source": "portrait", "field": "portrait_md", "value": "下班也愿意认真做一顿饭"}
        ],
        "pack_calibration_evidence": pack_evidence
        if pack_evidence is not None
        else [{"field": "pack_md", "value": "下班后认真做饭"}],
        "product_evidence": [
            {"source": "sku", "field": "owner_selling_points", "value": "有机酿造"}
        ],
    }


def _spec(snapshot: dict, *, pack_evidence: list[dict] | None = None) -> dict:
    return {
        "intent": "planting",
        "target_audience_signal": "下班仍想把饭做好",
        "planting_function": "让人看到酱油如何参与一顿饭",
        "duration_seconds": 12,
        "cast_count": 1,
        "scene_count": 1,
        "product_actions": ["把“有机酿造”的酱油沿锅边倒入"],
        "spoken_copy_goal": "完整自然口播",
        "pain_solution_bridge": _bridge(pack_evidence=pack_evidence),
        "upstream_fact_hash": snapshot["planting_bridge_context"]["upstream_fact_hash"],
        "factual_whitelist": ["有机酿造"],
        "forbidden_claims": ["无依据销量"],
        "visual_constraints": ["单人厨房"],
        "audio_constraints": ["口播清晰"],
        "experiment_variable": "opening_hook_3s",
    }


def test_v4_truth_rejects_missing_or_mismatched_pack_lineage() -> None:
    missing_pack = _snapshot(pack_id=None)
    rejected_missing = validate_truth_snapshot(missing_pack)
    assert rejected_missing["ok"] is False
    assert rejected_missing["error"] == "truth_snapshot_incomplete"
    assert "planting_bridge_context.facts.lineage.audience_pack_id" in rejected_missing["missing"]

    mismatched = _snapshot()
    facts = mismatched["planting_bridge_context"]["facts"]
    facts["pack_calibration"]["id"] = "00000000-0000-0000-0000-000000000199"
    mismatched["planting_bridge_context"]["upstream_fact_hash"] = canonical_upstream_fact_hash(facts)
    rejected_mismatch = validate_truth_snapshot(mismatched)
    assert rejected_mismatch["ok"] is False
    assert rejected_mismatch["error"] == "truth_snapshot_invalid"
    assert "planting_bridge_context.facts.pack_calibration.id" in rejected_mismatch["invalid"]


def test_v4_content_spec_requires_selected_pack_evidence() -> None:
    snapshot = _snapshot()
    truth = validate_truth_snapshot(snapshot)
    assert truth["ok"] is True

    rejected = validate_content_spec(
        _spec(snapshot, pack_evidence=[]),
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )
    assert rejected["ok"] is False
    assert rejected["error"] == "content_spec_pain_solution_bridge_invalid"
    assert "pack_calibration_evidence" in rejected["missing_or_invalid"]


def test_v4_content_spec_rejects_bridge_that_bypasses_review_with_food_result() -> None:
    snapshot = _snapshot()
    truth = validate_truth_snapshot(snapshot)
    assert truth["ok"] is True
    spec = _spec(snapshot)
    spec["pain_solution_bridge"]["visible_result"] = (
        "镜头可见“有机酿造”，汤汁清透不发黑"
    )

    rejected = validate_content_spec(
        spec,
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )

    assert rejected["ok"] is False
    assert rejected["error"] == "content_spec_pain_solution_bridge_invalid"
    assert "visible_result" in rejected["missing_or_invalid"]
    assert any(
        "bridge_unsupported_claim" in error
        for error in rejected["bridge_errors"]
    )


def test_v3_stays_readable_without_a_pack_but_new_v4_does_not() -> None:
    legacy = _snapshot(version=P0_V3_CONTRACT_VERSION, pack_id=None)
    legacy_truth = validate_truth_snapshot(legacy)
    assert legacy_truth["ok"] is True
    legacy_spec = validate_content_spec(
        _spec(legacy, pack_evidence=[]),
        truth_snapshot_hash=legacy_truth["snapshot_hash"],
        truth_snapshot=legacy,
    )
    assert legacy_spec["ok"] is True


@pytest.mark.asyncio
async def test_v4_order_creation_rejects_missing_or_mismatched_pack_before_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = {"status": "ready"}
    missing = await orders.create_or_reuse_production_order(
        sku_id=SKU_ID,
        audience_record_id=RECORD_ID,
        audience_portrait_id=PORTRAIT_ID,
        audience_pack_id=None,
        product_reference_asset_ids=["00000000-0000-0000-0000-000000000301"],
        baseline_manifest=baseline,
    )
    assert missing == {
        "ok": False,
        "error": "audience_pack_required",
        "missing": ["audience_pack_id"],
    }

    wrong_facts = _facts(pack_id="00000000-0000-0000-0000-000000000399")
    captured: list[object] = []

    async def fake_bridge_context(*_args: object) -> dict:
        captured.extend(_args)
        return {
            "ok": True,
            "facts": wrong_facts,
            "upstream_fact_hash": canonical_upstream_fact_hash(wrong_facts),
        }

    monkeypatch.setattr(orders, "load_planting_bridge_context", fake_bridge_context)
    mismatch = await orders.create_or_reuse_production_order(
        sku_id=SKU_ID,
        audience_record_id=RECORD_ID,
        audience_portrait_id=PORTRAIT_ID,
        audience_pack_id=PACK_ID,
        product_reference_asset_ids=["00000000-0000-0000-0000-000000000301"],
        baseline_manifest=baseline,
    )
    assert mismatch["ok"] is False
    assert mismatch["error"] == "audience_pack_lineage_mismatch"
    assert mismatch["expected_audience_pack_id"] == PACK_ID
    assert captured == [SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID]
