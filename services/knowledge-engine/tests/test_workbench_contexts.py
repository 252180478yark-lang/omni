from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.runtime_traces import require_trace_access
from app.routers.workbench_contexts import get_workbench_context_store, router
from app.services.workbench_contexts import MemoryWorkbenchContextStore


def context(surface: str, *, sku_ref: str | None = None) -> dict:
    return {
        "context_ref": "context:workspace:active",
        "workspace_ref": "workspace:omni",
        "shop_ref": None,
        "sku_ref": sku_ref,
        "project_ref": "project:omni",
        "environment_ref": "environment:local",
        "task_ref": None,
        "evidence_refs": ["evidence:system-graph"],
        "origin_surface_ref": surface,
        "availability": "available",
        "rebind_reason": None,
    }


@pytest.mark.asyncio
async def test_context_api_creates_reuses_and_cas_rebinds_append_only_snapshots():
    store = MemoryWorkbenchContextStore()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workbench_context_store] = lambda: store
    app.dependency_overrides[require_trace_access] = lambda: None
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/workbench-contexts",
            json={"context": context("ui_route:/workspace")},
        )
        repeated = await client.post(
            "/api/v1/workbench-contexts",
            json={"context": context("ui_route:/workspace")},
        )
        first_value = first.json()["snapshot"]
        rebind_payload = {
            "context": {
                **context("ui_route:/sku", sku_ref="sku:soy-sauce"),
                "rebind_reason": "business_object_changed",
            },
            "expected_snapshot_id": first_value["snapshot_id"],
            "expected_revision": first_value["revision"],
        }
        rebound = await client.post("/api/v1/workbench-contexts/rebind", json=rebind_payload)
        retry = await client.post("/api/v1/workbench-contexts/rebind", json=rebind_payload)
        conflict = await client.post(
            "/api/v1/workbench-contexts/rebind",
            json={
                **rebind_payload,
                "context": context("ui_route:/content"),
            },
        )

    assert first.status_code == repeated.status_code == rebound.status_code == retry.status_code == 200
    assert first.json()["reused"] is False
    assert repeated.json()["reused"] is True
    assert repeated.json()["snapshot"] == first_value
    assert rebound.json()["snapshot"]["revision"] == 2
    assert rebound.json()["snapshot"]["snapshot_id"] != first_value["snapshot_id"]
    assert retry.json() == {**rebound.json(), "reused": True}
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "context_rebind_conflict"
    assert len(store.snapshots["context:workspace:active"]) == 2


@pytest.mark.asyncio
async def test_context_api_owns_permission_hash_and_rejects_raw_paths_or_partial_cas():
    store = MemoryWorkbenchContextStore()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workbench_context_store] = lambda: store
    app.dependency_overrides[require_trace_access] = lambda: None
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/workbench-contexts",
            json={"context": context("ui_route:/workspace")},
        )
        injected = await client.post(
            "/api/v1/workbench-contexts",
            json={
                "context": {
                    **context("ui_route:/workspace"),
                    "permission_scope_hash": "sha256:" + "0" * 64,
                }
            },
        )
        raw_path = await client.post(
            "/api/v1/workbench-contexts",
            json={
                "context": {
                    **context("ui_route:/workspace"),
                    "project_ref": "E:/agent/omni",
                }
            },
        )
        partial = await client.post(
            "/api/v1/workbench-contexts/rebind",
            json={
                "context": context("ui_route:/sku", sku_ref="sku:one"),
                "expected_snapshot_id": created.json()["snapshot"]["snapshot_id"],
            },
        )

    assert created.status_code == 200
    assert created.json()["snapshot"]["permission_scope_hash"].startswith("sha256:")
    assert created.json()["snapshot"]["permission_scope_hash"] != "sha256:" + "0" * 64
    assert injected.status_code == raw_path.status_code == partial.status_code == 422


def test_main_registers_the_workbench_context_router():
    source = (SERVICE_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.routers.workbench_contexts import router as workbench_contexts_router" in source
    assert "app.include_router(workbench_contexts_router)" in source
