from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.system_graph import EvidenceClassification
from app.services.system_graph.pilot import (
    PilotManifest,
    eligible_block_codes,
    r3_pending_fixture,
    run_r1_r2_pilot,
    validate_repository_paths,
)
from app.services.system_graph.planned import PlannedFactReport, RepairCard


def _issue(*, code: str = "required_edge_missing", classification: EvidenceClassification = EvidenceClassification.OBSERVED_FACT) -> RepairCard:
    return RepairCard(
        fingerprint="sha256:" + "a" * 64,
        code=code,
        severity="warning",
        classification=classification,
        observed="fixture",
        expected="fixture edge",
        impact_paths=["services/fixture.py"],
        verification_command="python -m pytest fixture",
    )


def _report(*issues: RepairCard) -> PlannedFactReport:
    return PlannedFactReport(
        change_id="fixture-s6",
        snapshot_id="sha256:" + "b" * 64,
        planned_nodes=[],
        required_edges=[],
        issues=list(issues),
    )


def test_r1_and_r2_pilots_close_automatically_when_no_selected_failure_exists() -> None:
    assert run_r1_r2_pilot(_report(), risk_level="R1").state == "graph_diff_ready"
    assert run_r1_r2_pilot(_report(), risk_level="R2").state == "graph_diff_ready"


def test_only_deterministic_observed_issue_code_can_be_selected_to_block() -> None:
    missing = _issue()
    hypothesis = _issue(code="required_edge_unknown", classification=EvidenceClassification.HYPOTHESIS)
    report = _report(missing, hypothesis)
    assert eligible_block_codes(report.issues) == ("required_edge_missing",)
    result = run_r1_r2_pilot(report, risk_level="R2", selected_block_codes=["required_edge_missing"])
    assert result.state == "blocked"
    with pytest.raises(ValueError):
        run_r1_r2_pilot(report, risk_level="R2", selected_block_codes=["required_edge_unknown"])


def test_r3_fixture_is_pending_and_has_no_effect_surface() -> None:
    result = r3_pending_fixture(request_id="request-1", target="external:fixture", payload_hash="sha256:fixture")
    assert result.risk_level == "R3"
    assert result.state == "waiting_approval"
    assert result.effect_executed is False


def test_repository_manifest_requires_exact_r1_r2_r3_and_existing_paths(tmp_path: Path) -> None:
    candidate = tmp_path / "services" / "candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("VALUE = 1\n", encoding="utf-8")
    manifest = PilotManifest.model_validate(
        {
            "schema_version": 1,
            "pilots": [
                {
                    "pilot_id": "r1-pilot",
                    "risk_level": "R1",
                    "purpose": "fixture",
                    "candidate_paths": ["services/candidate.py"],
                    "allocation_paths": ["services/**"],
                    "commands": [{"argv": ["python", "-V"]}],
                },
                {
                    "pilot_id": "r2-pilot",
                    "risk_level": "R2",
                    "purpose": "fixture",
                    "candidate_paths": ["services/candidate.py"],
                    "allocation_paths": ["services/**"],
                    "commands": [{"argv": ["python", "-V"]}],
                },
                {
                    "pilot_id": "r3-pilot",
                    "risk_level": "R3",
                    "purpose": "fixture",
                    "candidate_paths": ["services/candidate.py"],
                    "approval_handler": "system.noop-audit",
                    "approval_target": "external:fixture",
                },
            ],
        }
    )
    assert validate_repository_paths(tmp_path, manifest.pilots[0]) == ("services/candidate.py",)

    candidate.unlink()
    with pytest.raises(ValueError, match="does not exist"):
        validate_repository_paths(tmp_path, manifest.pilots[0])
