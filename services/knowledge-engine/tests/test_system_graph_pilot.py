from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.system_graph import EvidenceClassification
from app.services.system_graph.pilot import eligible_block_codes, r3_pending_fixture, run_r1_r2_pilot
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
