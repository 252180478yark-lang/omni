from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.system_graph import EvidenceClassification, IntegrationPlanState, PlanDecision, PlanReviewStatus
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


def _item(
    *,
    item_id: str = "bff",
    decision: PlanDecision = PlanDecision.ADD,
    critical: bool = False,
    review_status: PlanReviewStatus = PlanReviewStatus.ACCEPTED,
) -> PlanItem:
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
        review_status=review_status,
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
    assert store.latest(plan.plan_id).state is IntegrationPlanState.STALE


def test_critical_unknown_cannot_lock_and_confirmation_projects_no_product_write() -> None:
    store = PlanStore()
    plan = store.create_or_reuse(
        feature_id="fixture",
        base_snapshot_id=SNAPSHOT,
        intent="add BFF",
        items=[_item(decision=PlanDecision.UNKNOWN, critical=True)],
    )
    reviewing = store.patch(
        plan_id=plan.plan_id,
        expected_revision=1,
        items=[_item(decision=PlanDecision.UNKNOWN, critical=True, review_status=PlanReviewStatus.PENDING)],
        current_snapshot_id=SNAPSHOT,
    )
    with pytest.raises(UnresolvedCriticalUnknown):
        store.confirm(plan_id=plan.plan_id, expected_revision=2, request_id="req-1", current_snapshot_id=SNAPSHOT, confirmed=True)

    ready = store.patch(plan_id=plan.plan_id, expected_revision=2, items=[_item()], current_snapshot_id=SNAPSHOT)
    frozen = store.confirm(plan_id=plan.plan_id, expected_revision=3, request_id="req-2", current_snapshot_id=SNAPSHOT, confirmed=True)
    duplicate = store.confirm(plan_id=plan.plan_id, expected_revision=3, request_id="req-2", current_snapshot_id=SNAPSHOT, confirmed=True)
    projection = project_confirmed_plan(frozen)
    assert reviewing.revision == 2
    assert ready.revision == 3
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


def test_file_store_cross_process_cas_has_exactly_one_winner(tmp_path: Path) -> None:
    seed = FilePlanStore(tmp_path)
    plan = seed.create_or_reuse(
        feature_id="fixture", base_snapshot_id=SNAPSHOT, intent="race", items=[_item()]
    )
    first = FilePlanStore(tmp_path)
    second = FilePlanStore(tmp_path)
    winner = first.patch(
        plan_id=plan.plan_id,
        expected_revision=1,
        items=[_item(item_id="winner")],
        current_snapshot_id=SNAPSHOT,
    )
    with pytest.raises(PlanConflict):
        second.patch(
            plan_id=plan.plan_id,
            expected_revision=1,
            items=[_item(item_id="loser")],
            current_snapshot_id=SNAPSHOT,
        )
    disk = FilePlanStore(tmp_path).latest(plan.plan_id)
    assert disk.items[0].item_id == winner.items[0].item_id == "winner"


def test_evidence_classification_and_owner_review_are_enforced() -> None:
    with pytest.raises(ValueError, match="observed_fact"):
        PlanItem(item_id="fact", layer="api", target_ref="api:x", decision="reuse", evidence_class="observed_fact", evidence_refs=[], verification="verify", risk="R1")
    with pytest.raises(ValueError, match="rationale"):
        PlanItem(item_id="recommendation", layer="api", target_ref="api:x", decision="add", evidence_class="recommendation", verification="verify", risk="R1")
    with pytest.raises(ValueError, match="missing evidence"):
        PlanItem(item_id="hypothesis", layer="api", target_ref="api:x", decision="unknown", evidence_class="hypothesis", verification="verify", risk="R1")


def test_rebase_resets_reviews_and_archive_preserves_history() -> None:
    store = PlanStore()
    plan = store.create_or_reuse(
        feature_id="fixture", base_snapshot_id=SNAPSHOT, intent="rebase", items=[_item()]
    )
    reviewing = store.patch(
        plan_id=plan.plan_id, expected_revision=1, items=[_item()], current_snapshot_id=SNAPSHOT
    )
    rebased = store.rebase(
        plan_id=plan.plan_id,
        expected_revision=reviewing.revision,
        base_snapshot_id=NEXT_SNAPSHOT,
        snapshot_status="partial",
        missing_sources=["catalog.openapi"],
        actor_id="owner",
    )
    assert rebased.items[0].review_status is PlanReviewStatus.PENDING
    assert rebased.missing_sources == ["catalog.openapi"]
    archived = store.archive(
        plan_id=plan.plan_id,
        expected_revision=rebased.revision,
        actor_id="owner",
        reason="superseded",
    )
    assert archived.state is IntegrationPlanState.ARCHIVED
    assert len(store.revisions[plan.plan_id]) == 4
