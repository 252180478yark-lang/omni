from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.system_graph import EvidenceClassification
from app.services.system_graph.issues import IssueConflict, IssueStatus, IssueStore
from app.services.system_graph.planned import PlannedFactReport, RepairCard


def _report(snapshot: str, *, observed: str = "missing") -> PlannedFactReport:
    return PlannedFactReport(
        change_id="fixture-s4",
        snapshot_id=snapshot,
        planned_nodes=[],
        required_edges=[],
        issues=[
            RepairCard(
                fingerprint="sha256:" + "a" * 64,
                code="required_edge_missing",
                severity="warning",
                classification=EvidenceClassification.OBSERVED_FACT,
                observed=observed,
                expected="page calls api",
                impact_paths=["frontend/src/app/fixture/page.tsx"],
                evidence_refs=[],
                suggested_locations=["frontend/src/app/fixture/page.tsx"],
                verification_command="verify fixture",
            )
        ],
    )


def test_issue_store_is_searchable_idempotent_and_keeps_status_history(tmp_path: Path) -> None:
    store = IssueStore(tmp_path)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    created = store.upsert_report(_report("sha256:" + "1" * 64), now=now)[0]
    assert created.status is IssueStatus.OPEN
    assert store.list(code="required_edge_missing", query="page") == [created]

    acknowledged = store.transition(
        created.fingerprint,
        expected_revision=1,
        status=IssueStatus.ACKNOWLEDGED,
        actor="owner",
        reason="accepted for repair",
        now=now,
    )
    repeated = store.upsert_report(_report("sha256:" + "2" * 64), now=now)[0]
    assert repeated.status is IssueStatus.ACKNOWLEDGED
    assert repeated.occurrences == 2
    assert repeated.first_seen_snapshot.endswith("1" * 64)
    assert repeated.last_seen_snapshot.endswith("2" * 64)
    assert len(repeated.history) == len(acknowledged.history) == 2


def test_issue_transition_uses_revision_cas_and_resolved_issue_reopens(tmp_path: Path) -> None:
    store = IssueStore(tmp_path)
    issue = store.upsert_report(_report("sha256:" + "1" * 64))[0]
    resolved = store.transition(
        issue.fingerprint,
        expected_revision=1,
        status=IssueStatus.RESOLVED,
        actor="owner",
        reason="fixed",
    )
    with pytest.raises(IssueConflict):
        store.transition(
            issue.fingerprint,
            expected_revision=1,
            status=IssueStatus.SNOOZED,
            actor="owner",
            reason="stale write",
        )
    reopened = store.upsert_report(_report("sha256:" + "2" * 64))[0]
    assert reopened.status is IssueStatus.OPEN
    assert reopened.revision == resolved.revision + 1
    assert reopened.history[-1].reason == "reopened_after_recurrence"
