from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType


def _load_contract_module() -> ModuleType:
    script_path = Path(__file__).parents[1] / "scripts" / "dev_contract.py"
    spec = importlib.util.spec_from_file_location("omni_dev_contract", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dc = _load_contract_module()


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "impact.yaml", tmp_path / "completion.yaml"


def _populated_impact(state: str = "DISCOVERED") -> dict:
    impact = dc.impact_template("feature-test", "Feature contract test")
    impact["state"] = state
    impact["feature_refs"] = [
        {
            "feature_id": "feature-test",
            "feature_ref": "prd:feature-test#FR-001",
        }
    ]
    impact["before_snapshot"] = {"ref": "snapshot-before"}
    impact["delivery"] = {
        "authority": "ci_attestation",
        "base_commit": "a" * 40,
    }
    impact["risk"] = {
        "level": "R1",
        "reasons": ["Single-service behavior changes."],
        "external_effects": [],
        "approval": {"required": False, "gate_ref": ""},
    }
    impact["intent"] = {
        "problem": "Prevent disconnected feature changes.",
        "expected_outcome": "Every changed boundary has deterministic evidence.",
        "user_visible_behavior": ["Reject incomplete feature chains."],
    }
    impact["current_chain"] = {
        "nodes": ["page:/example", "service:example.run"],
        "edges": [],
        "evidence": ["services/example.py:run"],
    }
    impact["scope"]["services"] = ["service:example.run"]
    impact["planned_changes"] = [
        {
            "id": "CHG-001",
            "action": "modify",
            "kind": "service",
            "node_id": "service:example.run",
            "paths": ["services/example.py"],
            "upstream": ["page:/example"],
            "downstream": [],
            "contract_change": "compatible",
            "verification_ids": ["VER-001"],
        }
    ]
    impact["compatibility"] = {
        "api": {"status": "not_applicable", "strategy": "No API change."},
        "database": {"status": "not_applicable", "strategy": "No database change."},
        "workflow": {"status": "compatible", "strategy": "Existing states remain valid."},
        "data_source": {"status": "not_applicable", "strategy": "No source change."},
    }
    impact["graph_acceptance"] = {
        "required_edges": [
            {"from": "page:/example", "to": "service:example.run", "relation": "calls"}
        ],
        "allowed_unknowns": [],
        "forbidden_orphans": ["service:example.run"],
    }
    impact["out_of_scope"] = ["Database schema changes."]
    impact["rollback"] = {
        "strategy": "Revert services/example.py.",
        "data_recovery": "No persistent data changes.",
    }
    impact["verification_plan"] = [
        {
            "id": "VER-001",
            "layer": "service",
            "command": "python -m pytest tests/test_example.py",
            "proves": "The changed service boundary works.",
            "required": True,
        }
    ]
    return impact


def _valid_completion(state: str) -> dict:
    completion = dc.completion_template("feature-test")
    completion["state"] = state
    if dc.state_at_least(state, "GRAPH_DIFF_READY"):
        completion["delivery"] = {"status": "ready_for_ci"}
    completion["actual_changes"] = [
        {
            "id": "ACT-001",
            "planned_change_id": "CHG-001",
            "paths": ["services/example.py"],
            "summary": "Updated the declared service.",
        }
    ]
    completion["verification_results"] = [
        {
            "id": "VER-001",
            "command": "python -m pytest tests/test_example.py",
            "status": "passed",
            "exit_code": 0,
            "evidence": "1 passed",
        }
    ]
    completion["graph_diff"].update(
        {
            "status": "clean",
            "snapshot_before": "snapshot-before",
            "snapshot_after": "snapshot-after",
            "required_edges": [
                {
                    "from": "page:/example",
                    "to": "service:example.run",
                    "relation": "calls",
                    "status": "present",
                    "evidence": "graph snapshot snapshot-after",
                }
            ],
        }
    )
    completion["rollback"] = {"verified": True, "evidence": "Revert command dry-run passed."}
    if state == "COMPLETE":
        completion["final"] = {
            "status": "complete",
            "completed_at": "2026-07-28T00:00:00Z",
            "completed_by": "codex",
            "summary": "Feature chain verified.",
        }
    return completion


def _write_pair(tmp_path: Path, impact: dict, completion: dict) -> tuple[Path, Path]:
    impact_path, completion_path = _paths(tmp_path)
    dc.write_yaml(impact_path, impact)
    dc.write_yaml(completion_path, completion)
    return impact_path, completion_path


def _transition(impact_path: Path, completion_path: Path, target: str) -> int:
    return dc.command_transition(
        argparse.Namespace(
            impact=str(impact_path),
            completion=str(completion_path),
            to=target,
            actor="codex",
            rationale="Impact reviewed against current code and consumers.",
        )
    )


def _lock(impact: dict) -> None:
    impact["lock"] = {
        "locked_at": "2026-07-28T00:00:00Z",
        "locked_by": "codex",
        "rationale": "Impact reviewed against current code and consumers.",
    }


def test_unlocked_impact_cannot_enter_implementing(tmp_path: Path) -> None:
    impact = _populated_impact("IMPACT_LOCKED")
    completion = dc.completion_template("feature-test")
    completion["state"] = "IMPACT_LOCKED"
    impact_path, completion_path = _write_pair(tmp_path, impact, completion)

    assert _transition(impact_path, completion_path, "IMPLEMENTING") == 1
    assert dc.read_yaml(impact_path)["state"] == "IMPACT_LOCKED"
    assert dc.read_yaml(impact_path)["lock"]["locked_at"] is None


def test_state_cannot_skip_or_move_backward(tmp_path: Path) -> None:
    impact = _populated_impact("DISCOVERED")
    completion = dc.completion_template("feature-test")
    impact_path, completion_path = _write_pair(tmp_path, impact, completion)

    assert _transition(impact_path, completion_path, "VERIFYING") == 1
    assert dc.read_yaml(impact_path)["state"] == "DISCOVERED"

    impact["state"] = "VERIFYING"
    completion["state"] = "VERIFYING"
    dc.write_yaml(impact_path, impact)
    dc.write_yaml(completion_path, completion)
    assert _transition(impact_path, completion_path, "IMPLEMENTING") == 1
    assert dc.read_yaml(impact_path)["state"] == "VERIFYING"


def test_changed_files_outside_locked_scope_fail(tmp_path: Path) -> None:
    impact = _populated_impact("IMPACT_LOCKED")
    _lock(impact)
    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text(
        "services/example.py\nfrontend/src/app/undeclared/page.tsx\n",
        encoding="utf-8",
    )

    errors = dc.validate_changed_files(impact, changed_files)

    assert errors == [
        "changed file is outside locked impact scope: frontend/src/app/undeclared/page.tsx"
    ]


def test_failed_required_verification_cannot_complete(tmp_path: Path) -> None:
    impact = _populated_impact("GRAPH_DIFF_READY")
    _lock(impact)
    completion = _valid_completion("GRAPH_DIFF_READY")
    completion["verification_results"][0].update(
        {"status": "failed", "exit_code": 1, "evidence": "1 failed"}
    )
    impact_path, completion_path = _write_pair(tmp_path, impact, completion)

    assert _transition(impact_path, completion_path, "COMPLETE") == 1
    assert dc.read_yaml(impact_path)["state"] == "GRAPH_DIFF_READY"


def test_v3_repository_flow_stops_at_graph_diff_ready(tmp_path: Path) -> None:
    impact = _populated_impact("DISCOVERED")
    completion = dc.completion_template("feature-test")
    impact_path, completion_path = _write_pair(tmp_path, impact, completion)

    assert _transition(impact_path, completion_path, "IMPACT_LOCKED") == 0
    assert _transition(impact_path, completion_path, "IMPLEMENTING") == 0

    completion = dc.read_yaml(completion_path)
    completion["actual_changes"] = _valid_completion("VERIFYING")["actual_changes"]
    dc.write_yaml(completion_path, completion)
    assert _transition(impact_path, completion_path, "VERIFYING") == 0

    completion = dc.read_yaml(completion_path)
    valid = _valid_completion("VERIFYING")
    completion["verification_results"] = valid["verification_results"]
    completion["graph_diff"] = valid["graph_diff"]
    completion["delivery"] = {"status": "ready_for_ci"}
    completion["rollback"] = valid["rollback"]
    completion["final"] = valid["final"]
    dc.write_yaml(completion_path, completion)
    assert _transition(impact_path, completion_path, "GRAPH_DIFF_READY") == 0
    assert _transition(impact_path, completion_path, "COMPLETE") == 1

    final_impact = dc.read_yaml(impact_path)
    final_completion = dc.read_yaml(completion_path)
    assert dc.run_validation(
        final_impact,
        final_completion,
        expect_state="GRAPH_DIFF_READY",
        strict=True,
        changed_files_file=None,
    ) == []


def test_collector_unknown_requires_owner_expiry_and_acceptance() -> None:
    impact = _populated_impact("GRAPH_DIFF_READY")
    _lock(impact)
    completion = _valid_completion("GRAPH_DIFF_READY")
    completion["graph_diff"]["status"] = "accepted"
    completion["graph_diff"]["unknowns"] = [
        {
            "node_or_edge": "source:platform.endpoint",
            "reason": "Collector timed out.",
            "owner": "",
            "expires_at": "",
            "accepted": False,
        }
    ]

    errors = dc.validate_completion(impact, completion)

    assert "completion.graph_diff.unknowns[0].owner must be non-empty text" in errors
    assert "completion.graph_diff.unknowns[0].expires_at must be non-empty text" in errors
    assert "completion.graph_diff.unknowns[0].accepted must be true" in errors

    completion["graph_diff"]["unknowns"][0].update(
        {"owner": "data-platform", "expires_at": "2026-08-04T00:00:00Z", "accepted": True}
    )
    assert dc.validate_completion(impact, completion) == []


def test_actual_paths_and_verification_commands_must_match_the_plan() -> None:
    impact = _populated_impact("GRAPH_DIFF_READY")
    _lock(impact)
    completion = _valid_completion("GRAPH_DIFF_READY")
    completion["actual_changes"][0]["paths"] = ["frontend/src/unrelated.tsx"]
    completion["verification_results"][0]["command"] = "echo passed"

    errors = dc.validate_completion(impact, completion)

    assert any("outside planned change CHG-001" in error for error in errors)
    assert any("must exactly match verification_plan VER-001" in error for error in errors)


def test_required_edges_and_snapshots_cannot_be_replaced_by_placeholders() -> None:
    impact = _populated_impact("GRAPH_DIFF_READY")
    _lock(impact)
    completion = _valid_completion("GRAPH_DIFF_READY")
    completion["graph_diff"]["snapshot_before"] = ""
    completion["graph_diff"]["required_edges"] = [
        {
            "from": "page:/other",
            "to": "service:other.run",
            "relation": "calls",
            "status": "present",
            "evidence": "unrelated edge",
        }
    ]

    errors = dc.validate_completion(impact, completion)

    assert "completion.graph_diff.snapshot_before must be non-empty text" in errors
    assert any("missing required impact edge" in error for error in errors)


def test_contract_globs_are_segment_safe() -> None:
    assert dc.path_matches("services/example.py", "services/*") is True
    assert dc.path_matches("services/example/app.py", "services/*") is False
    assert dc.path_matches("services/example/app.py", "services/**") is True
    assert dc.path_matches("services/app.py", "services/**/*.py") is True


def test_single_star_cannot_cover_a_deep_changed_file(tmp_path: Path) -> None:
    impact = _populated_impact("IMPACT_LOCKED")
    _lock(impact)
    impact["planned_changes"][0]["paths"] = ["services/*"]
    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text("services/example/app.py\n", encoding="utf-8")

    assert dc.validate_changed_files(impact, changed_files) == [
        "changed file is outside locked impact scope: services/example/app.py"
    ]


def test_impact_rejects_repository_wide_globs_and_optional_only_checks() -> None:
    impact = _populated_impact("IMPACT_LOCKED")
    _lock(impact)
    impact["planned_changes"][0]["paths"] = ["**"]
    impact["planned_changes"][0]["verification_ids"] = []
    impact["verification_plan"][0]["required"] = False

    errors = dc.validate_impact(impact)

    assert any("cannot cover the entire repository" in error for error in errors)
    assert "impact.verification_plan must contain at least one required check" in errors
    assert any("verification_ids must contain at least one check" in error for error in errors)


def test_actual_changes_require_exact_paths_not_globs() -> None:
    impact = _populated_impact("GRAPH_DIFF_READY")
    _lock(impact)
    completion = _valid_completion("GRAPH_DIFF_READY")
    completion["actual_changes"][0]["paths"] = ["services/**"]

    errors = dc.validate_completion(impact, completion)

    assert any("must be an exact path, not a glob" in error for error in errors)


def test_legacy_v1_complete_contract_remains_strict_valid() -> None:
    impact = _populated_impact("COMPLETE")
    _lock(impact)
    impact["schema_version"] = 1
    impact.pop("feature_refs")
    impact.pop("before_snapshot")
    completion = _valid_completion("COMPLETE")
    completion["schema_version"] = 1

    assert dc.run_validation(
        impact,
        completion,
        expect_state="COMPLETE",
        strict=True,
        changed_files_file=None,
    ) == []


def test_new_templates_are_v3_and_allow_empty_delivery_only_while_discovered() -> None:
    impact = dc.impact_template("feature-test", "Feature contract test")
    completion = dc.completion_template("feature-test")

    assert impact["schema_version"] == 3
    assert completion["schema_version"] == 3
    assert impact["feature_refs"] == []
    assert impact["before_snapshot"] == {"ref": ""}
    assert impact["delivery"] == {"authority": "ci_attestation", "base_commit": ""}
    assert impact["risk"]["level"] == "R1"
    assert completion["delivery"] == {"status": "pending"}
    assert dc.run_validation(
        impact,
        completion,
        expect_state="DISCOVERED",
        strict=False,
        changed_files_file=None,
    ) == []


def test_v3_cannot_lock_without_risk_reason_or_full_base_commit(tmp_path: Path) -> None:
    impact = _populated_impact("DISCOVERED")
    impact["risk"]["reasons"] = []
    impact["delivery"]["base_commit"] = "HEAD"
    completion = dc.completion_template("feature-test")
    impact_path, completion_path = _write_pair(tmp_path, impact, completion)

    assert _transition(impact_path, completion_path, "IMPACT_LOCKED") == 1
    assert dc.read_yaml(impact_path)["state"] == "DISCOVERED"


def test_v3_forbids_repository_delivered_commit_and_self_declared_complete() -> None:
    impact = _populated_impact("GRAPH_DIFF_READY")
    _lock(impact)
    completion = _valid_completion("GRAPH_DIFF_READY")
    completion["delivery"]["delivered_commit"] = "b" * 40

    completion_errors = dc.validate_completion(impact, completion)
    assert any("delivered_commit is forbidden" in error for error in completion_errors)

    impact["state"] = "COMPLETE"
    completion["state"] = "COMPLETE"
    completion["final"]["status"] = "complete"
    impact_errors = dc.validate_impact(impact)
    assert any("cannot self-declare COMPLETE" in error for error in impact_errors)
    completion_errors = dc.validate_completion(impact, completion)
    assert any("only the CI attestation can declare completion" in error for error in completion_errors)


def test_v3_r3_requires_external_effect_description() -> None:
    impact = _populated_impact("IMPACT_LOCKED")
    _lock(impact)
    impact["risk"] = {
        "level": "R3",
        "reasons": ["The change can publish externally."],
        "external_effects": [],
        "approval": {"required": False, "gate_ref": ""},
    }

    assert (
        "impact.risk.external_effects must describe the R3 external effect"
        in dc.validate_impact(impact)
    )
    assert "impact.risk.approval.required must be true for R3" in dc.validate_impact(impact)
    assert "impact.risk.approval.gate_ref must be non-empty text" in dc.validate_impact(impact)


def test_v2_cannot_lock_without_feature_reference_and_before_snapshot(tmp_path: Path) -> None:
    impact = _populated_impact("DISCOVERED")
    impact["schema_version"] = 2
    impact["feature_refs"] = []
    impact["before_snapshot"] = {"ref": ""}
    completion = dc.completion_template("feature-test")
    completion["schema_version"] = 2
    impact_path, completion_path = _write_pair(tmp_path, impact, completion)

    assert _transition(impact_path, completion_path, "IMPACT_LOCKED") == 1
    assert dc.read_yaml(impact_path)["state"] == "DISCOVERED"


def test_v2_rejects_invalid_feature_identity() -> None:
    impact = _populated_impact("IMPACT_LOCKED")
    impact["schema_version"] = 2
    _lock(impact)
    impact["feature_refs"] = [
        {"feature_id": "", "feature_ref": ""},
        {"feature_id": "duplicate", "feature_ref": "ref:first"},
        {"feature_id": "duplicate", "feature_ref": "ref:second"},
    ]
    impact["before_snapshot"] = {"ref": ""}

    errors = dc.validate_impact(impact)

    assert "impact.feature_refs[0].feature_id must be non-empty text" in errors
    assert "impact.feature_refs[0].feature_ref must be non-empty text" in errors
    assert "duplicate feature_id: duplicate" in errors
    assert "impact.before_snapshot.ref must be non-empty text" in errors


def test_v2_rejects_schema_mixing_and_snapshot_mismatch() -> None:
    impact = _populated_impact("GRAPH_DIFF_READY")
    impact["schema_version"] = 2
    _lock(impact)
    completion = _valid_completion("GRAPH_DIFF_READY")
    completion["schema_version"] = 1

    mixed_errors = dc.validate_completion(impact, completion)
    assert "completion.schema_version must match impact.schema_version" in mixed_errors

    completion["schema_version"] = 2
    completion["graph_diff"]["snapshot_before"] = "another-before"
    snapshot_errors = dc.validate_completion(impact, completion)
    assert (
        "completion.graph_diff.snapshot_before must match impact.before_snapshot.ref"
        in snapshot_errors
    )


def test_unknown_schema_version_is_rejected_for_impact_and_completion() -> None:
    impact = _populated_impact("DISCOVERED")
    completion = dc.completion_template("feature-test")
    impact["schema_version"] = 4
    completion["schema_version"] = 4

    assert "impact.schema_version must equal 1, 2, or 3" in dc.validate_impact(impact)
    assert "completion.schema_version must equal 1, 2, or 3" in dc.validate_completion(
        impact,
        completion,
    )


def test_read_yaml_text_parses_a_named_evaluation_source() -> None:
    parsed = dc.read_yaml_text("change_id: feature-test\nstate: COMPLETE\n", "index:impact.yaml")

    assert parsed == {"change_id": "feature-test", "state": "COMPLETE"}
