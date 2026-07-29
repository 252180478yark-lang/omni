from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from app.services.video_production_contract import (
    P0_CONTRACT_VERSION,
    P0_V2_CONTRACT_VERSION,
    P0_V3_CONTRACT_VERSION,
    build_generation_approval_payload,
    build_p0_prompt_source,
    build_subtitle_timeline,
    can_transition,
    deterministic_script_gate,
    p0_beat_windows,
    p0_idempotency_key,
    validate_candidate_pair,
    validate_content_spec,
    validate_media_probe,
    validate_p0_beat_plan,
    validate_prompt_preview,
    validate_subtitle_timeline,
    validate_truth_snapshot,
)
from app.services.pain_solution_bridge import canonical_upstream_fact_hash
from app.services.video_prompt_compiler import compile_final_prompt_segment
from app.services import video_production_workflow as workflow
from app.services import video_production_orders as orders


def _bridge_facts() -> dict:
    return {
        "lineage": {
            "sku_id": "SKU-1",
            "matrix_run_id": "00000000-0000-0000-0000-000000000010",
            "audience_run_id": "00000000-0000-0000-0000-000000000011",
            "audience_record_id": "00000000-0000-0000-0000-000000000001",
            "portrait_id": "00000000-0000-0000-0000-000000000002",
            "audience_pack_id": "00000000-0000-0000-0000-000000000003",
        },
        "sku_facts": {"id": "SKU-1", "owner_selling_points": ["organic soy sauce"]},
        "matrix_evidence": {"id": "00000000-0000-0000-0000-000000000010", "matrix_md": "brew facts"},
        "portrait_record_evidence": {
            "record": {"id": "00000000-0000-0000-0000-000000000001", "name": "family dinner"},
            "portrait": {
                "id": "00000000-0000-0000-0000-000000000002",
                "portrait_md": "family dinner is a practical nightly ritual [KB: test]",
            },
        },
        "pack_calibration": {
            "id": "00000000-0000-0000-0000-000000000003",
            "pack_md": "weeknight home cooks",
            "dmp_tags": "home meal",
        },
        "eligible_evidence_catalog": {
            "sku": {"owner_selling_points": "organic soy sauce"},
            "matrix": {"matrix_md": "brew facts"},
            "record": {"name": "family dinner"},
            "portrait": {
                "portrait_md": "family dinner is a practical nightly ritual [KB: test]"
            },
        },
        "pack_calibration_catalog": {
            "pack_md": "weeknight home cooks",
            "dmp_tags": "home meal",
        },
    }


def _bridge_context() -> dict:
    facts = _bridge_facts()
    return {
        "facts": facts,
        "eligible_evidence_catalog": {
            **facts["eligible_evidence_catalog"],
            "pack": facts["pack_calibration_catalog"],
        },
        "require_pack_evidence": True,
        "upstream_fact_hash": canonical_upstream_fact_hash(facts),
    }


def _pain_solution_bridge() -> dict:
    return {
        "audience_segment": "family dinner cooks",
        "trigger_scene": "weekday dinner before plating",
        "pain_point": "for a family dinner, I am worried about choosing seasoning without a clear fact",
        "pain_consequence": "the family dinner becomes a moment of repeated label checking before cooking",
        "product_action": "add organic soy sauce before plating",
        "visible_result": "camera close-up of the organic soy sauce bottle while pouring it",
        "belief_shift": "from a family dinner concern to choosing organic soy sauce by its stated fact",
        "relevance_module": "M1",
        "justification_module": "M3",
        "portrait_evidence": [
            {"source": "portrait", "field": "portrait_md", "value": "family dinner"}
        ],
        "pack_calibration_evidence": [
            {"field": "pack_md", "value": "weeknight home cooks"}
        ],
        "product_evidence": [
            {
                "source": "sku",
                "field": "owner_selling_points",
                "value": "organic soy sauce",
            }
        ],
    }


def _truth_snapshot() -> dict:
    context = _bridge_context()
    return {
        "contract_version": P0_CONTRACT_VERSION,
        "sku": {"id": "SKU-1", "name": "soy sauce"},
        "audience_record": {"id": "00000000-0000-0000-0000-000000000001"},
        "audience_portrait": {
            "id": "00000000-0000-0000-0000-000000000002",
            "sku_id": "SKU-1",
            "audience_record_id": "00000000-0000-0000-0000-000000000001",
            "portrait_md": "family dinner is a practical nightly ritual [KB: test]",
            "status": "adopted",
        },
        "product_reference_manifest": {"assets": [{"id": "ref-1", "file_url": "/a.png"}]},
        "facts": {"whitelist": ["organic soy sauce"]},
        "planting_bridge_context": context,
    }


def _content_spec() -> dict:
    context = _bridge_context()
    return {
        "intent": "planting",
        "target_audience_signal": "下班后想认真做饭",
        "planting_function": "让用户理解一瓶酱油如何参与一顿饭",
        "duration_seconds": 12,
        "cast_count": 1,
        "scene_count": 1,
        "product_actions": ["add organic soy sauce before plating"],
        "spoken_copy_goal": "完整口播",
        "pain_solution_bridge": _pain_solution_bridge(),
        "upstream_fact_hash": context["upstream_fact_hash"],
        "factual_whitelist": ["organic soy sauce"],
        "forbidden_claims": ["无依据销量"],
        "visual_constraints": ["单人厨房"],
        "audio_constraints": ["口播清晰"],
        "experiment_variable": "opening_hook_3s",
    }


def _beat_plan(spoken_copy: str) -> list[dict]:
    chunks = [spoken_copy[:12], spoken_copy[12:24], spoken_copy[24:]]
    return [
        {
            "start_seconds": 0,
            "end_seconds": 3,
            "visual": "Return to the kitchen and start cooking.",
            "action": "Turn on the stove.",
            "spoken_copy": "",
            "sound": "Natural kitchen ambience.",
        },
        {
            "start_seconds": 3,
            "end_seconds": 6,
            "visual": "Ingredients enter the pan in a hand close-up.",
            "action": "Stir the food.",
            "spoken_copy": chunks[0],
            "sound": "Spatula and pan sound.",
        },
        {
            "start_seconds": 6,
            "end_seconds": 9,
            "visual": "The seasoning action stays in the same kitchen frame.",
            "action": "起锅前加入酱油",
            "spoken_copy": chunks[1],
            "sound": "Cooking sound.",
        },
        {
            "start_seconds": 9,
            "end_seconds": 12,
            "visual": "The finished hot meal is placed on the table.",
            "action": "Place the hot meal on the table.",
            "spoken_copy": chunks[2],
            "sound": "Light tableware sound.",
        },
    ]


def _candidate(hook: str) -> dict:
    spoken_copy = "今天不糊弄这一顿。"
    return {
        "opening_hook_3s": hook,
        "body": "下班后先把锅烧热。",
        "spoken_copy": spoken_copy,
        "beat_plan": _beat_plan(spoken_copy),
        "product_action": "起锅前加入酱油",
        "duration_seconds": 12,
        "factual_claims": ["有机酿造"],
        "content_spec_hash": "spec-hash",
        "truth_snapshot_hash": "truth-hash",
    }


def test_truth_and_spec_are_immutable_hash_inputs() -> None:
    snapshot = _truth_snapshot()
    truth = validate_truth_snapshot(snapshot)
    assert truth["ok"] is True
    spec = validate_content_spec(
        _content_spec(),
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )
    assert spec["ok"] is True
    assert spec["spec"]["intent"] == "planting"
    assert P0_CONTRACT_VERSION not in p0_idempotency_key(
        sku_id="SKU-1",
        audience_record_id="aud-1",
        audience_portrait_id="portrait-1",
        product_reference_asset_ids=["ref-1"],
    )


def test_v4_truth_requires_matching_adopted_portrait_but_v2_stays_readable() -> None:
    v4 = _truth_snapshot()
    v4.pop("audience_portrait")
    rejected = validate_truth_snapshot(v4)
    assert rejected["ok"] is False
    assert rejected["error"] == "truth_snapshot_incomplete"
    assert "audience_portrait" in rejected["missing"]

    legacy = _truth_snapshot()
    legacy.pop("contract_version")
    legacy.pop("audience_portrait")
    legacy.pop("planting_bridge_context")
    legacy_truth = validate_truth_snapshot(
        legacy,
        contract_version=P0_V2_CONTRACT_VERSION,
    )
    assert legacy_truth["ok"] is True
    assert legacy_truth["contract_version"] == P0_V2_CONTRACT_VERSION


def test_v4_content_spec_binds_structured_bridge_hash_and_frozen_evidence() -> None:
    snapshot = _truth_snapshot()
    truth = validate_truth_snapshot(snapshot)
    assert truth["ok"] is True

    valid = validate_content_spec(
        _content_spec(),
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )
    assert valid["ok"] is True

    free_text = _content_spec()
    free_text["pain_solution_bridge"] = "a loose slogan"
    rejected_text = validate_content_spec(
        free_text,
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )
    assert rejected_text["error"] == "content_spec_pain_solution_bridge_invalid"

    wrong_hash = _content_spec()
    wrong_hash["upstream_fact_hash"] = "0" * 64
    rejected_hash = validate_content_spec(
        wrong_hash,
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )
    assert rejected_hash["error"] == "content_spec_upstream_fact_hash_mismatch"

    unsupported_evidence = _content_spec()
    unsupported_evidence["pain_solution_bridge"]["product_evidence"][0]["value"] = "invented"
    rejected_evidence = validate_content_spec(
        unsupported_evidence,
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )
    assert rejected_evidence["error"] == "content_spec_pain_solution_bridge_invalid"


def test_v4_pack_catalog_is_frozen_under_canonical_pack_source() -> None:
    snapshot = _truth_snapshot()
    facts = snapshot["planting_bridge_context"]["facts"]
    facts["lineage"]["audience_pack_id"] = "pack-1"
    facts["pack_calibration"] = {"id": "pack-1", "pack_md": "premium cooking"}
    facts["pack_calibration_catalog"] = {"pack_md": "premium cooking", "dmp_tags": "home meal"}
    snapshot["planting_bridge_context"]["eligible_evidence_catalog"] = {
        **facts["eligible_evidence_catalog"],
        "pack": facts["pack_calibration_catalog"],
    }
    snapshot["planting_bridge_context"]["require_pack_evidence"] = True
    snapshot["planting_bridge_context"]["upstream_fact_hash"] = canonical_upstream_fact_hash(facts)
    truth = validate_truth_snapshot(snapshot)
    assert truth["ok"] is True

    spec = _content_spec()
    spec["upstream_fact_hash"] = snapshot["planting_bridge_context"]["upstream_fact_hash"]
    spec["pain_solution_bridge"]["pack_calibration_evidence"] = [
        {"field": "pack_md", "value": "premium cooking"}
    ]
    validated = validate_content_spec(
        spec,
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )
    assert validated["ok"] is True


def test_order_freeze_merges_canonical_pack_catalog_for_v4_validation() -> None:
    facts = _bridge_facts()
    facts["pack_calibration"] = {"id": "pack-1"}
    facts["pack_calibration_catalog"] = {"pack_md": "premium cooking"}
    frozen = orders._freeze_bridge_context(
        {
            "facts": facts,
            "upstream_fact_hash": canonical_upstream_fact_hash(facts),
        }
    )
    assert frozen is not None
    assert frozen["require_pack_evidence"] is True
    assert frozen["eligible_evidence_catalog"]["pack"] == {"pack_md": "premium cooking"}


def test_v4_idempotency_distinguishes_adopted_portraits_and_packs() -> None:
    common = {
        "sku_id": "SKU-1",
        "audience_record_id": "record-1",
        "product_reference_asset_ids": ["ref-1"],
    }
    assert p0_idempotency_key(
        **common,
        audience_portrait_id="portrait-1",
        audience_pack_id="pack-1",
    ) != p0_idempotency_key(
        **common,
        audience_portrait_id="portrait-2",
        audience_pack_id="pack-1",
    )
    assert p0_idempotency_key(
        **common,
        audience_portrait_id="portrait-1",
        audience_pack_id="pack-1",
    ) != p0_idempotency_key(
        **common,
        audience_portrait_id="portrait-1",
        audience_pack_id="pack-2",
    )
    assert p0_idempotency_key(
        **common,
        audience_portrait_id="portrait-1",
        audience_pack_id="pack-1",
        contract_version=P0_V3_CONTRACT_VERSION,
    ) == p0_idempotency_key(
        **common,
        audience_portrait_id="portrait-1",
        audience_pack_id="pack-2",
        contract_version=P0_V3_CONTRACT_VERSION,
    )
    assert p0_idempotency_key(
        **common,
        audience_portrait_id="portrait-1",
        audience_pack_id="pack-1",
        contract_version=P0_V2_CONTRACT_VERSION,
    ) == p0_idempotency_key(
        **common,
        audience_portrait_id="portrait-2",
        audience_pack_id="pack-2",
        contract_version=P0_V2_CONTRACT_VERSION,
    )


def test_p0_rejects_cross_drift_beyond_opening_hook() -> None:
    valid = validate_candidate_pair([_candidate("钩子 A"), _candidate("钩子 B")])
    assert valid["ok"] is True
    drifting = _candidate("钩子 B")
    drifting["product_action"] = "桌上蘸食"
    rejected = validate_candidate_pair([_candidate("钩子 A"), drifting])
    assert rejected == {
        "ok": False,
        "error": "script_candidate_cross_drift",
        "changed": ["product_action"],
    }


def test_p0_short_beat_plan_is_continuous_and_rejects_long_shots() -> None:
    for duration, expected_count in ((12, 4), (14, 4), (15, 5)):
        windows = p0_beat_windows(duration)
        assert len(windows) == expected_count
        assert windows[0]["start_seconds"] == 0
        assert windows[-1]["end_seconds"] == duration
        assert all(
            window["end_seconds"] - window["start_seconds"] <= 4
            for window in windows
        )

    plan = _beat_plan("起锅前加入酱油")
    assert validate_p0_beat_plan(
        plan,
        duration_seconds=12,
        spoken_copy="起锅前加入酱油",
        expected_product_action="起锅前加入酱油",
    )["ok"] is True
    plan[1]["end_seconds"] = 8
    rejected = validate_p0_beat_plan(plan, duration_seconds=12, spoken_copy="起锅前加入酱油")
    assert rejected["error"] == "beat_plan_timing_invalid"


def test_p0_rejects_overlong_beat_voiceover_and_a_b_beat_drift() -> None:
    plan = _beat_plan("")
    plan[1]["spoken_copy"] = "一二三四五六七八九十一二三"
    rejected = validate_p0_beat_plan(
        plan,
        duration_seconds=12,
        spoken_copy="一二三四五六七八九十一二三",
    )
    assert rejected["error"] == "beat_plan_spoken_too_long"

    drifting = _candidate("Hook B")
    drifting["beat_plan"][1]["visual"] = "A different second beat."
    pair = validate_candidate_pair([_candidate("Hook A"), drifting])
    assert pair == {
        "ok": False,
        "error": "script_candidate_cross_drift",
        "changed": ["beat_plan"],
    }


def test_writer_stamps_frozen_fields_before_the_deterministic_gate() -> None:
    raw = _candidate("Hook A")
    raw.update(
        {
            "product_action": "writer paraphrase",
            "duration_seconds": 15,
            "content_spec_hash": "writer-hash",
            "truth_snapshot_hash": "writer-truth",
        }
    )
    stamped = workflow._stamp_frozen_candidate_fields(
        [raw],
        spec={"product_actions": ["add soy sauce before cooking"], "duration_seconds": 12},
        content_spec_hash="spec-hash",
        truth_snapshot_hash="truth-hash",
    )

    assert stamped is not None
    assert stamped[0]["product_action"] == "add soy sauce before cooking"
    assert stamped[0]["duration_seconds"] == 12.0
    assert stamped[0]["content_spec_hash"] == "spec-hash"
    assert stamped[0]["truth_snapshot_hash"] == "truth-hash"
    assert stamped[0]["body"] == raw["body"]


def test_prompt_preview_and_state_machine_fail_closed() -> None:
    source = {
        "identity_product_anchor": "一位下班回家的女性和酱油瓶",
        "reference_instruction": "产品参考图必须保持包装一致",
        "product_solution_action": "起锅前加入酱油",
        "timeline": "0-3 秒钩子，3-12 秒做饭",
        "scene_detail": "单人厨房",
        "sound_detail": "清晰口播",
        "decorative_detail": "暖色夜晚",
        "negative": "不出现价格和虚假促销",
        "required_anchors": {
            "character": "下班女性",
            "product": "酱油瓶",
            "action": "起锅前加入",
            "result": "一顿热饭",
        },
    }
    preview = validate_prompt_preview(
        source,
        duration_seconds=12,
        requested_provider="seedance",
        requested_model="doubao-seedance-2-0-260128",
    )
    assert preview["ok"] is True
    assert can_transition(current_status="spec_ready", next_status="awaiting_script_selection")
    assert can_transition(current_status="raw_rejected", next_status="raw_passed")
    assert can_transition(current_status="raw_passed", next_status="raw_rejected")
    assert not can_transition(current_status="spec_ready", next_status="released")


def test_p0_candidate_gate_and_prompt_approval_bind_facts_and_refs() -> None:
    snapshot = _truth_snapshot()
    truth = validate_truth_snapshot(snapshot)
    spec = validate_content_spec(
        _content_spec(),
        truth_snapshot_hash=truth["snapshot_hash"],
        truth_snapshot=snapshot,
    )
    candidate = _candidate("Hook A")
    action = spec["spec"]["product_actions"][0]
    candidate.update(
        {
                "body": "Add organic soy sauce before plating, then put the hot meal on the table.",
                "spoken_copy": "Add organic soy sauce before plating.",
            "product_action": action,
            "factual_claims": ["organic soy sauce"],
            "content_spec_hash": spec["spec_hash"],
            "truth_snapshot_hash": truth["snapshot_hash"],
        }
    )
    candidate["beat_plan"] = _beat_plan(str(candidate["spoken_copy"]))
    candidate["beat_plan"][2]["action"] = action
    gate = deterministic_script_gate(
        candidate,
        spec=spec["spec"],
        truth_snapshot=truth["snapshot"],
        content_spec_hash=spec["spec_hash"],
        truth_snapshot_hash=truth["snapshot_hash"],
    )
    assert gate["status"] == "passed"
    source = build_p0_prompt_source(
        candidate=candidate,
        spec=spec["spec"],
        truth_snapshot=truth["snapshot"],
    )
    compiled = compile_final_prompt_segment(source, duration_seconds=12, intent="planting")
    assert compiled["ok"] is True
    approved = build_generation_approval_payload(
        production_order_id="00000000-0000-0000-0000-000000000099",
        prompt_source_hash="a" * 64,
        prompt_source=source,
        reference_manifest={"items": [{"id": "ref-1", "type": "product", "sha256": "b" * 64}]},
        requested_provider="seedance",
        requested_model="doubao-seedance-2-0-260128",
        duration_seconds=12,
        final_prompt=compiled["final_prompt"],
    )
    assert approved["ok"] is True
    assert len(approved["approval_hash"]) == 64


def test_media_and_subtitle_final_gates_fail_closed() -> None:
    probe = {
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920},
            {"codec_type": "audio"},
        ],
        "format": {"duration": "12.1"},
    }
    assert validate_media_probe(probe, require_audio=True, expected_duration_seconds=12)["ok"] is True
    missing_audio = validate_media_probe(
        {"streams": [{"codec_type": "video", "width": 1080, "height": 1920}], "format": {"duration": "12"}},
        require_audio=True,
        expected_duration_seconds=12,
    )
    assert missing_audio["ok"] is False
    spoken_copy = "起锅前加入酱油"
    beat_plan = _beat_plan(spoken_copy)
    timeline = build_subtitle_timeline(
        spoken_copy=spoken_copy,
        duration_seconds=12,
        beat_plan=beat_plan,
    )
    assert timeline["ok"] is True
    assert len(timeline["entries"]) == 1
    assert timeline["entries"][0]["start"] == 3
    assert timeline["entries"][0]["end"] == 6
    assert validate_subtitle_timeline(
        timeline["entries"], duration_seconds=12, spoken_copy=spoken_copy, beat_plan=beat_plan
    )["ok"] is True
    assert validate_subtitle_timeline(
        timeline["entries"], duration_seconds=12, spoken_copy="被替换的口播", beat_plan=_beat_plan("被替换的口播")
    )["error"] == "subtitle_beat_alignment_invalid"


def test_product_reference_qa_requires_an_explicit_multimodal_pass(
    tmp_path: Path, monkeypatch
) -> None:
    """A video frame must be compared to the frozen product reference separately."""

    raw_path = tmp_path / "raw.mp4"
    raw_path.write_bytes(b"raw-video")
    reference_path = tmp_path / "reference.jpg"
    reference_path.write_bytes(b"reference-image")
    paths = {"raw": raw_path, "reference": reference_path}

    def fake_resolve_reference_path(value: str) -> Path:
        return paths[value]

    def fake_run_process(args: list[str]) -> subprocess.CompletedProcess[str]:
        frame_path = Path(args[-1])
        frame_path.write_bytes(b"sampled-frame")
        return subprocess.CompletedProcess(args, 0, "", "")

    async def fake_chat(self, **kwargs):
        assert kwargs["provider"] == "gemini"
        assert len(kwargs["messages"][1]["content"]) == 3
        return {
            "content": '{"decision":"passed","reason_codes":[],"evidence":["reference_match"]}',
            "provider": "gemini",
            "model": "gemini-2.5-flash",
        }

    monkeypatch.setattr(workflow, "resolve_reference_path", fake_resolve_reference_path)
    monkeypatch.setattr(workflow, "_run_process", fake_run_process)
    monkeypatch.setattr(workflow.AIHubClient, "chat", fake_chat)
    result = asyncio.run(
        workflow._run_product_reference_qa(
            path=raw_path,
            truth_snapshot={
                "sku": {"name": "product"},
                "product_reference_manifest": {"assets": [{"id": "ref-1", "file_url": "reference"}]},
            },
        )
    )
    assert result["status"] == "passed"
    assert result["reference_asset_id"] == "ref-1"


def test_product_reference_qa_passes_when_match_and_nonidentifiable_frames(
    tmp_path: Path, monkeypatch
) -> None:
    raw_path = tmp_path / "raw.mp4"
    raw_path.write_bytes(b"raw-video")
    reference_path = tmp_path / "reference.jpg"
    reference_path.write_bytes(b"reference-image")

    monkeypatch.setattr(
        workflow,
        "resolve_reference_path",
        lambda value: {"raw": raw_path, "reference": reference_path}[value],
    )

    def fake_run_process(args: list[str]) -> subprocess.CompletedProcess[str]:
        Path(args[-1]).write_bytes(b"sampled-frame")
        return subprocess.CompletedProcess(args, 0, "", "")

    responses = iter(
        [
            {"decision": "failed", "reason_codes": ["product_label_unclear"], "evidence": ["blurred"]},
            {"decision": "passed", "reason_codes": [], "evidence": ["clear reference match"]},
            {"decision": "failed", "reason_codes": ["product_not_visible"], "evidence": ["not visible"]},
            {"decision": "failed", "reason_codes": ["product_label_unclear"], "evidence": ["covered"]},
        ]
    )

    async def fake_chat(self, **kwargs):
        assert len(kwargs["messages"][1]["content"]) == 3
        return {"content": json.dumps(next(responses)), "provider": "gemini", "model": "judge"}

    monkeypatch.setattr(workflow, "_run_process", fake_run_process)
    monkeypatch.setattr(workflow.AIHubClient, "chat", fake_chat)

    result = asyncio.run(
        workflow._run_product_reference_qa(
            path=raw_path,
            truth_snapshot={
                "sku": {"name": "product"},
                "product_reference_manifest": {"assets": [{"id": "ref-1", "file_url": "reference"}]},
            },
            content_spec={"duration_seconds": 12},
        )
    )

    assert result["status"] == "passed"
    assert result["matched_frame_index"] == 2
    assert result["matched_frame_timestamp_seconds"] == 5.04
    assert [item["timestamp_seconds"] for item in result["frame_checks"]] == [3.6, 5.04, 6.48, 7.92]
    assert [item["status"] for item in result["frame_checks"]] == ["failed", "passed", "failed", "failed"]


def test_product_reference_qa_fails_when_clear_mismatch_coexists_with_matches(
    tmp_path: Path, monkeypatch
) -> None:
    """A clear wrong package/label is blocking even if another frame matches."""

    raw_path = tmp_path / "raw.mp4"
    raw_path.write_bytes(b"raw-video")
    reference_path = tmp_path / "reference.jpg"
    reference_path.write_bytes(b"reference-image")
    monkeypatch.setattr(
        workflow,
        "resolve_reference_path",
        lambda value: {"raw": raw_path, "reference": reference_path}[value],
    )

    def fake_run_process(args: list[str]) -> subprocess.CompletedProcess[str]:
        Path(args[-1]).write_bytes(b"sampled-frame")
        return subprocess.CompletedProcess(args, 0, "", "")

    responses = iter(
        [
            {"decision": "passed", "reason_codes": [], "evidence": ["clear reference match"]},
            {
                "decision": "failed",
                "reason_codes": ["packaging_different"],
                "evidence": ["visible package does not match reference"],
            },
            {
                "decision": "failed",
                "reason_codes": ["label_text_different"],
                "evidence": ["visible label text differs from reference"],
            },
            {"decision": "passed", "reason_codes": [], "evidence": ["second clear reference match"]},
        ]
    )

    async def fake_chat(self, **kwargs):
        return {"content": json.dumps(next(responses)), "provider": "gemini", "model": "judge"}

    monkeypatch.setattr(workflow, "_run_process", fake_run_process)
    monkeypatch.setattr(workflow.AIHubClient, "chat", fake_chat)

    result = asyncio.run(
        workflow._run_product_reference_qa(
            path=raw_path,
            truth_snapshot={
                "sku": {"name": "product"},
                "product_reference_manifest": {"assets": [{"id": "ref-1", "file_url": "reference"}]},
            },
            content_spec={"duration_seconds": 12},
        )
    )

    assert result["status"] == "failed"
    assert result["reason_codes"] == ["packaging_different", "label_text_different"]
    assert result["blocking_frame_indices"] == [2, 3]
    assert result["blocking_frame_timestamps_seconds"] == [5.04, 6.48]


def test_product_reference_qa_fails_closed_when_no_frame_clearly_matches(
    tmp_path: Path, monkeypatch
) -> None:
    raw_path = tmp_path / "raw.mp4"
    raw_path.write_bytes(b"raw-video")
    reference_path = tmp_path / "reference.jpg"
    reference_path.write_bytes(b"reference-image")
    monkeypatch.setattr(
        workflow,
        "resolve_reference_path",
        lambda value: {"raw": raw_path, "reference": reference_path}[value],
    )

    def fake_run_process(args: list[str]) -> subprocess.CompletedProcess[str]:
        Path(args[-1]).write_bytes(b"sampled-frame")
        return subprocess.CompletedProcess(args, 0, "", "")

    async def fake_chat(self, **kwargs):
        return {
            "content": '{"decision":"failed","reason_codes":["product_label_unclear"],"evidence":["not readable"]}',
            "provider": "gemini",
            "model": "judge",
        }

    monkeypatch.setattr(workflow, "_run_process", fake_run_process)
    monkeypatch.setattr(workflow.AIHubClient, "chat", fake_chat)

    result = asyncio.run(
        workflow._run_product_reference_qa(
            path=raw_path,
            truth_snapshot={
                "sku": {"name": "product"},
                "product_reference_manifest": {"assets": [{"id": "ref-1", "file_url": "reference"}]},
            },
            content_spec={"duration_seconds": 12},
        )
    )

    assert result["status"] == "failed"
    assert result["reason_codes"] == ["product_label_unclear"]
    assert len(result["frame_checks"]) == 4
    assert all(item["status"] == "failed" for item in result["frame_checks"])
    assert not result.get("matched_frame_timestamp_seconds")


def test_product_reference_qa_never_passes_when_all_frames_are_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    raw_path = tmp_path / "raw.mp4"
    raw_path.write_bytes(b"raw-video")
    reference_path = tmp_path / "reference.jpg"
    reference_path.write_bytes(b"reference-image")
    monkeypatch.setattr(
        workflow,
        "resolve_reference_path",
        lambda value: {"raw": raw_path, "reference": reference_path}[value],
    )
    monkeypatch.setattr(
        workflow,
        "_run_process",
        lambda args: subprocess.CompletedProcess(args, 1, "", "frame extraction failed"),
    )

    result = asyncio.run(
        workflow._run_product_reference_qa(
            path=raw_path,
            truth_snapshot={
                "sku": {"name": "product"},
                "product_reference_manifest": {"assets": [{"id": "ref-1", "file_url": "reference"}]},
            },
            content_spec={"duration_seconds": 12},
        )
    )

    assert result["status"] == "unavailable"
    assert result["reason_codes"] == ["qa_frame_extract_failed"]
    assert all(item["status"] == "unavailable" for item in result["frame_checks"])


class _IdentityLatchAcquire:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args) -> None:
        return None


class _IdentityLatchTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None


class _IdentityLatchPool:
    def __init__(self, conn) -> None:
        self.conn = conn

    def acquire(self):
        return _IdentityLatchAcquire(self.conn)

    async def execute(self, query: str, *args):
        return await self.conn.execute(query, *args)


class _IdentityLatchConn:
    def __init__(self, qa_reports: list[dict] | None = None, *, order_status: str = "raw_qa") -> None:
        self.qa_asset_ids: list[str] = []
        self.order_status = order_status
        self.qa_reports = qa_reports if qa_reports is not None else [
            {
                "passed": False,
                "report": {
                    "product_reference": {
                        "reason_codes": ["label_text_different"],
                    }
                },
            },
            {"passed": True, "report": {"reason_codes": []}},
        ]

    def transaction(self):
        return _IdentityLatchTransaction()

    async def fetch(self, query: str, *args):
        assert "FROM pipeline.production_qa_reports" in query
        self.qa_asset_ids.append(str(args[1]))
        return list(self.qa_reports)

    async def execute(self, query: str, *args):
        assert "INSERT INTO pipeline.production_qa_reports" in query
        self.qa_reports.append({"report": json.loads(args[3]), "passed": args[4]})

    async def fetchrow(self, query: str, *_args):
        if "source.prompt_source" in query:
            return {
                "attempt_id": "attempt-1",
                "raw_asset_id": "raw-locked",
                "file_url": "must-not-be-read",
                "prompt_source": {},
                "snapshot": {},
                "content_spec": {},
                "order_status": self.order_status,
            }
        if "FROM pipeline.production_generation_attempts attempt" in query:
            return {
                "attempt_id": "attempt-1",
                "raw_asset_id": "raw-locked",
                "file_url": "must-not-be-read",
                "script_id": "script-1",
                "content_contract": {},
            }
        if "FROM pipeline.production_timelines timeline" in query:
            return {
                "timeline_id": "timeline-1",
                "timeline_spec": {"raw_asset_id": "raw-locked"},
                "timeline_hash": "timeline-hash",
                "final_asset_id": "final-1",
                "file_url": "must-not-be-read",
                "script_id": "script-1",
                "content_contract": {},
            }
        raise AssertionError(query)


def test_raw_identity_latch_detects_nested_and_legacy_reason_codes() -> None:
    assert workflow._product_identity_hard_failure_codes(
        {"product_reference": {"reason_codes": ["label_text_different"]}}
    ) == ["label_text_different"]
    assert workflow._product_identity_hard_failure_codes(
        {"reason_codes": ["packaging_different", "non_blocking"]}
    ) == ["packaging_different"]


def test_raw_identity_latch_blocks_same_asset_before_reqa(monkeypatch) -> None:
    conn = _IdentityLatchConn()
    monkeypatch.setattr(workflow, "get_pool", lambda: _IdentityLatchPool(conn))
    monkeypatch.setattr(
        workflow,
        "resolve_reference_path",
        lambda _value: (_ for _ in ()).throw(AssertionError("latched asset must not be re-QAed")),
    )

    result = asyncio.run(
        workflow.run_raw_qa(production_order_id="order-1", attempt_id="attempt-1")
    )

    assert result == {
        "ok": False,
        "error": "raw_asset_rejected_replacement_required",
        "raw_asset_id": "raw-locked",
        "reason_codes": ["label_text_different"],
    }
    assert conn.qa_asset_ids == ["raw-locked"]


def test_raw_identity_latch_blocks_compose_and_final_qa_for_same_asset(monkeypatch) -> None:
    conn = _IdentityLatchConn()
    monkeypatch.setattr(workflow, "get_pool", lambda: _IdentityLatchPool(conn))

    async def compose_context(_conn, _order_id: str, *, lock: bool = False):
        return {
            "order": {"status": "raw_passed", "contract_version": P0_CONTRACT_VERSION},
            "truth": {"snapshot": {}},
            "spec": {"spec": {}},
        }

    monkeypatch.setattr(workflow, "_load_context", compose_context)
    compose = asyncio.run(
        workflow.compose_final_video(production_order_id="order-1", attempt_id="attempt-1")
    )
    assert compose["error"] == "raw_asset_rejected_replacement_required"
    assert compose["raw_asset_id"] == "raw-locked"

    async def final_context(_conn, _order_id: str, *, lock: bool = False):
        return {
            "order": {"status": "final_qa", "contract_version": P0_CONTRACT_VERSION},
            "truth": {"snapshot": {}},
            "spec": {"spec": {}},
        }

    monkeypatch.setattr(workflow, "_load_context", final_context)
    final = asyncio.run(workflow.run_final_qa(production_order_id="order-1"))
    assert final["error"] == "raw_asset_rejected_replacement_required"
    assert final["raw_asset_id"] == "raw-locked"
    assert conn.qa_asset_ids == ["raw-locked", "raw-locked"]


def test_raw_identity_latch_wins_when_semantic_qa_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    conn = _IdentityLatchConn(qa_reports=[])
    monkeypatch.setattr(workflow, "get_pool", lambda: _IdentityLatchPool(conn))
    monkeypatch.setattr(workflow, "resolve_reference_path", lambda _value: tmp_path / "raw.mp4")
    (tmp_path / "raw.mp4").write_bytes(b"raw")
    monkeypatch.setattr(workflow, "_ffprobe", lambda _path: {})
    monkeypatch.setattr(workflow, "validate_media_probe", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(workflow, "_black_freeze_scan", lambda _path: {"black_detected": False, "freeze_detected": False})
    monkeypatch.setattr(workflow, "_sha256_file", lambda _path: "raw-sha")

    async def unavailable_semantic(**_kwargs):
        return {"status": "unavailable", "reason_codes": ["semantic_qa_unavailable"]}

    async def wrong_label(**_kwargs):
        return {"status": "failed", "reason_codes": ["label_text_different"]}

    async def raw_qa_context(_conn, _order_id: str, *, lock: bool = False):
        return {"order": {"status": "raw_qa"}}

    async def no_op_transition(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workflow, "_run_raw_semantic_qa", unavailable_semantic)
    monkeypatch.setattr(workflow, "_run_product_reference_qa", wrong_label)
    monkeypatch.setattr(workflow, "_load_context", raw_qa_context)
    monkeypatch.setattr(workflow, "_transition_locked", no_op_transition)

    result = asyncio.run(
        workflow.run_raw_qa(production_order_id="order-1", attempt_id="attempt-1")
    )

    assert result["error"] == "raw_asset_rejected_replacement_required"
    assert result["reason_codes"] == ["label_text_different"]
    assert result["report"]["status"] == "failed"
    assert result["report"]["semantic"]["status"] == "unavailable"
    assert conn.qa_reports[-1]["passed"] is False


def test_raw_qa_rejects_calls_outside_raw_states(monkeypatch) -> None:
    conn = _IdentityLatchConn(order_status="ready_to_release")
    monkeypatch.setattr(workflow, "get_pool", lambda: _IdentityLatchPool(conn))
    monkeypatch.setattr(
        workflow,
        "resolve_reference_path",
        lambda _value: (_ for _ in ()).throw(AssertionError("wrong state must not read asset")),
    )

    result = asyncio.run(
        workflow.run_raw_qa(production_order_id="order-1", attempt_id="attempt-1")
    )

    assert result == {
        "ok": False,
        "error": "production_order_wrong_state",
        "status": "ready_to_release",
    }
    assert conn.qa_asset_ids == []
