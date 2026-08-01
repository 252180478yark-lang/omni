from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.approval_operations import get_approval_principal
from app.routers.system_graph import get_integration_plan_service, router
from app.schemas.system_graph import GraphSnapshot, GraphSnapshotContent
from app.services.approval_operations import ApprovalPrincipal
from app.services.system_graph.canonical import sha256_value
from app.services.system_graph.integration_plans import FilePlanStore, IntegrationPlanService
from app.services.system_graph.snapshots import write_snapshot


SNAPSHOT_HASH = "sha256:" + "a" * 64


def _snapshot() -> GraphSnapshot:
    content = GraphSnapshotContent(
        commit="a" * 40,
        definition_revision="sha256:" + "b" * 64,
        collector_versions={},
        feature_ids=["fixture"],
        source_results=[],
        nodes=[],
        edges=[],
    )
    digest = sha256_value(content.model_dump(mode="json"))
    return GraphSnapshot(
        snapshot_id=digest,
        content_hash=digest,
        generated_at_utc=datetime.now(timezone.utc),
        content=content,
    )


def _item() -> dict[str, object]:
    return {
        "item_id": "bff",
        "layer": "bff",
        "target_ref": "api:POST:/api/v1/fixture",
        "decision": "add",
        "evidence_class": "recommendation",
        "evidence_refs": [],
        "recommendation": "add explicit boundary",
        "verification": "python -m pytest tests/test_fixture.py",
        "risk": "R2",
        "critical": False,
    }


def _app(tmp_path: Path, *, owner: bool = True) -> tuple[FastAPI, str, Path]:
    snapshot_path = write_snapshot(_snapshot(), tmp_path / "snapshots")
    snapshot_id = GraphSnapshot.model_validate_json(snapshot_path.read_text(encoding="utf-8")).snapshot_id
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_integration_plan_service] = lambda: IntegrationPlanService(
        store=FilePlanStore(tmp_path / "plans"), snapshot_root=tmp_path / "snapshots"
    )
    principal = ApprovalPrincipal(
        "owner" if owner else "reader",
        roles=frozenset({"owner"}) if owner else frozenset(),
    )
    app.dependency_overrides[get_approval_principal] = lambda: principal
    return app, snapshot_id, tmp_path / "plans"


@pytest.mark.asyncio
async def test_rest_plan_requires_owner_and_returns_only_candidate_artifacts(tmp_path: Path) -> None:
    app, snapshot_id, plan_root = _app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/system-graph/integration-plans",
            json={"feature_id": "fixture", "base_snapshot_id": snapshot_id, "intent": "add bff", "items": [_item()]},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["product_write_performed"] is False
        assert body["side_effects"] == ["candidate_plan_revision_artifact"]
        plan_id = body["plan"]["plan_id"]
        assert list(plan_root.glob(f"{plan_id}/revision-1.json"))

        confirmed = await client.post(
            f"/api/v1/system-graph/integration-plans/{plan_id}/confirm",
            json={
                "expected_revision": 1,
                "current_snapshot_id": snapshot_id,
                "request_id": "owner-confirmation-1",
                "confirmed": True,
            },
        )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["plan"]["state"] == "frozen"
    assert confirmed_body["impact_draft"]["product_write_performed"] is False
    assert list(plan_root.glob(f"{plan_id}/revision-2.json"))


@pytest.mark.asyncio
async def test_rest_plan_rejects_non_owner_and_stale_snapshot(tmp_path: Path) -> None:
    non_owner_app, snapshot_id, _ = _app(tmp_path / "non-owner", owner=False)
    transport = httpx.ASGITransport(app=non_owner_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.post(
            "/api/v1/system-graph/integration-plans",
            json={"feature_id": "fixture", "base_snapshot_id": snapshot_id, "intent": "add bff", "items": [_item()]},
        )
    assert rejected.status_code == 403

    app, snapshot_id, _ = _app(tmp_path / "stale")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/system-graph/integration-plans",
            json={"feature_id": "fixture", "base_snapshot_id": snapshot_id, "intent": "add bff", "items": [_item()]},
        )
        plan_id = created.json()["plan"]["plan_id"]
        stale = await client.patch(
            f"/api/v1/system-graph/integration-plans/{plan_id}",
            json={"expected_revision": 1, "current_snapshot_id": SNAPSHOT_HASH, "items": [_item()]},
        )
    assert stale.status_code == 409
    assert stale.json()["code"] == "plan_not_impact_locked"
