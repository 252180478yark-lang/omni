from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.system_graph import GraphSnapshot, GraphSnapshotContent, PlanDecision, PlanReviewStatus, SourceResult, SourceStatus
from app.services.system_graph.canonical import sha256_value
from app.services.system_graph.integration_plans import FilePlanStore, IntegrationPlanService, default_plan_items, plan_summary
from app.services.system_graph.snapshots import write_snapshot


def _partial_snapshot() -> GraphSnapshot:
    content = GraphSnapshotContent(
        commit="a" * 40,
        definition_revision="sha256:" + "b" * 64,
        collector_versions={"python.static": "1", "catalog.openapi": "1"},
        feature_ids=["fixture"],
        source_results=[
            SourceResult(collector_id="python.static", version="1", status=SourceStatus.SUCCESS),
            SourceResult(collector_id="catalog.openapi", version="1", status=SourceStatus.UNKNOWN, reason_code="collector_timeout", retryable=True),
        ],
        nodes=[],
        edges=[],
    )
    digest = sha256_value(content.model_dump(mode="json"))
    return GraphSnapshot(snapshot_id=digest, content_hash=digest, generated_at_utc=datetime.now(timezone.utc), content=content)


def test_partial_snapshot_builds_full_impact_table_and_confirmed_artifact(tmp_path: Path) -> None:
    snapshot_path = write_snapshot(_partial_snapshot(), tmp_path / "snapshots")
    snapshot = GraphSnapshot.model_validate_json(snapshot_path.read_text(encoding="utf-8"))
    store = FilePlanStore(tmp_path / "plans")
    service = IntegrationPlanService(store=store, snapshot_root=tmp_path / "snapshots")
    draft = service.create(feature_id="fixture", base_snapshot_id=snapshot.snapshot_id, intent="co-design every layer", items=[], actor_id="owner")
    assert [item.layer for item in draft.items] == [item.layer for item in default_plan_items("fixture")]
    assert draft.snapshot_status == "partial"
    assert draft.missing_sources == ["catalog.openapi"]
    assert plan_summary(draft)["critical_unknowns"] == len(draft.items)

    resolved = [
        item.model_copy(update={"decision": PlanDecision.NOT_DO, "review_status": PlanReviewStatus.ACCEPTED, "review_note": "owner decided this layer is out of scope"})
        for item in draft.items
    ]
    reviewing = service.patch(plan_id=draft.plan_id, expected_revision=draft.revision, current_snapshot_id=draft.base_snapshot_id, items=resolved, actor_id="owner")
    frozen, impact = service.confirm(plan_id=draft.plan_id, expected_revision=reviewing.revision, current_snapshot_id=reviewing.base_snapshot_id, request_id="owner-confirm-1", confirmed=True, actor_id="owner")
    assert frozen.state.value == "frozen"
    assert impact["state"] == "DISCOVERED"
    assert impact["product_write_performed"] is False
    assert Path(str(impact["artifact_path"])).is_file()
    assert service.list()[0].plan_id == frozen.plan_id
