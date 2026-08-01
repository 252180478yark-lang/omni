from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.system_graph import EvidenceClassification, PlanDecision
from app.services.system_graph.integration_plans import (
    FilePlanStore,
    PlanConflict,
    PlanItem,
    PlanStale,
    PlanStore,
    UnresolvedCriticalUnknown,
    project_confirmed_plan,
)


SNAPSHOT = "sha256:" + "a" * 64
NEXT_SNAPSHOT = "sha256:" + "b" * 64


def _item(*, item_id: str = "bff", decision: PlanDecision = PlanDecision.ADD, critical: bool = False) -> PlanItem:
    return PlanItem(
        item_id=item_id,
        layer="bff",
        target_ref="api:POST:/api/v1/fixture",
        decision=decision,
        evidence_class=EvidenceClassification.OBSERVED_FACT if decision is PlanDecision.REUSE else EvidenceClassification.RECOMMENDATION,
        evidence_refs=["snapshot:" + SNAPSHOT],
        recommendation="add an explicit BFF" if decision is PlanDecision.ADD else "reuse fact",
        verification="python -m pytest tests/test_fixture.py",
        risk="R2",
        critical=critical,
    )


def test_same_feature_snapshot_and_intent_reuse_active_draft() -> None:
    store = PlanStore()
    first = store.create_or_reuse(feature_id="fixture", base_snapshot_id=SNAPSHOT, intent="add BFF", items=[_item()])
    second = store.create_or_reuse(feature_id="fixture", base_snapshot_id=SNAPSHOT, intent="add BFF", items=[_item()])
    assert first.plan_id == second.plan_id
    assert first.revision == second.revision == 1


def test_patch_uses_cas_and_rejects_stale_snapshot() -> None:
    store = PlanStore()
    plan = store.create_or_reuse(feature_id="fixture", base_snapshot_id=SNAPSHOT, intent="add BFF", items=[_item()])
    updated = store.patch(plan_id=plan.plan_id, expected_revision=1, items=[_item(item_id="writer")], current_snapshot_id=SNAPSHOT)
    assert updated.revision == 2
    with pytest.raises(PlanConflict):
        store.patch(plan_id=plan.plan_id, expected_revision=1, items=[_item()], current_snapshot_id=SNAPSHOT)
    with pytest.raises(PlanStale):
        store.patch(plan_id=plan.plan_id, expected_revision=2, items=[_item()], current_snapshot_id=NEXT_SNAPSHOT)


def test_critical_unknown_cannot_lock_and_confirmation_projects_no_product_write() -> None:
    store = PlanStore()
    plan = store.create_or_reuse(
        feature_id="fixture",
        base_snapshot_id=SNAPSHOT,
        intent="add BFF",
        items=[_item(decision=PlanDecision.UNKNOWN, critical=True)],
    )
    with pytest.raises(UnresolvedCriticalUnknown):
        store.confirm(plan_id=plan.plan_id, expected_revision=1, request_id="req-1", current_snapshot_id=SNAPSHOT, confirmed=True)

    ready = store.patch(plan_id=plan.plan_id, expected_revision=1, items=[_item()], current_snapshot_id=SNAPSHOT)
    frozen = store.confirm(plan_id=plan.plan_id, expected_revision=2, request_id="req-2", current_snapshot_id=SNAPSHOT, confirmed=True)
    duplicate = store.confirm(plan_id=plan.plan_id, expected_revision=2, request_id="req-2", current_snapshot_id=SNAPSHOT, confirmed=True)
    projection = project_confirmed_plan(frozen)
    assert ready.revision == 2
    assert frozen.state.value == "frozen"
    assert duplicate.revision == frozen.revision
    assert projection["product_write_performed"] is False
    assert projection["before_snapshot"]["ref"] == SNAPSHOT


def test_file_artifact_adapter_writes_only_the_selected_plan_directory(tmp_path: Path) -> None:
    store = FilePlanStore(tmp_path)
    draft = store.create_or_reuse(feature_id="fixture", base_snapshot_id=SNAPSHOT, intent="add BFF", items=[_item()])
    artifact = store.persist(draft)
    assert artifact.parent == tmp_path / draft.plan_id
    assert artifact.name == "revision-1.json"
    assert artifact.exists()
