from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.approval_operations import get_approval_principal
from app.routers.system_graph import get_graph_repository, router
from app.services.approval_operations import ApprovalPrincipal
from app.services.system_graph.repository import MemoryGraphRepository
from test_system_graph_persistence import snapshot


def app_with(repository: MemoryGraphRepository) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_graph_repository] = lambda: repository
    app.dependency_overrides[get_approval_principal] = lambda: ApprovalPrincipal("owner", roles=frozenset({"owner"}))
    return app


@pytest.mark.asyncio
async def test_refresh_is_idempotent_persists_partial_truth_and_serves_graph(monkeypatch) -> None:
    repository = MemoryGraphRepository()
    graph = snapshot()
    monkeypatch.setattr("app.routers.system_graph.scan_repository", lambda request: graph)
    transport = httpx.ASGITransport(app=app_with(repository))
    payload = {"feature_ids": [], "include_runtime": False, "idempotency_key": "refresh-fixture-1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/v1/system-graph/refresh", json=payload)
        assert created.status_code == 202
        refresh_id = created.json()["refresh"]["refresh_id"]
        status = await client.get(f"/api/v1/system-graph/refreshes/{refresh_id}")
        assert status.json()["state"] == "completed"
        repeated = await client.post("/api/v1/system-graph/refresh", json=payload)
        assert repeated.json()["reused"] is True
        page = await client.get(f"/api/v1/system-graph/snapshots/{graph.snapshot_id}/graph?limit=1")
        assert page.status_code == 200
        assert page.json()["page_info"]["has_more"] is True
        search = await client.get("/api/v1/system-graph/search", params={"q": "workspace"})
        assert search.json()["results"][0]["node"]["id"] == "ui_route:/workspace"
        latest = await client.get("/api/v1/system-graph/snapshot")
        assert latest.json()["snapshot_id"] == graph.snapshot_id


@pytest.mark.asyncio
async def test_graph_routes_reject_non_owner_invalid_cursor_and_missing_snapshot() -> None:
    repository = MemoryGraphRepository()
    graph = snapshot()
    await repository.save_snapshot(graph)
    app = app_with(repository)
    app.dependency_overrides[get_approval_principal] = lambda: ApprovalPrincipal("reader", roles=frozenset())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        forbidden = await client.get(f"/api/v1/system-graph/snapshots/{graph.snapshot_id}/graph")
        assert forbidden.status_code == 403

    transport = httpx.ASGITransport(app=app_with(repository))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.get(f"/api/v1/system-graph/snapshots/{graph.snapshot_id}/graph?cursor=nope")
        assert invalid.status_code == 422
        missing = await client.get("/api/v1/system-graph/snapshots/sha256:missing/graph")
        assert missing.status_code == 404
