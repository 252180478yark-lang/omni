from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.runtime_plan_drafts import get_plan_draft_store, router
from app.routers.runtime_traces import require_trace_access
from app.services.runtime_plan_drafts import MemoryRuntimePlanDraftStore


def payload(expected_version=None):
    return {
        "finding_fingerprint": "sha256:" + "a" * 64,
        "trace_id": "trace:plan",
        "base_snapshot_id": "sha256:" + "b" * 64,
        "expected_version": expected_version,
    }


@pytest.mark.asyncio
async def test_plan_entry_is_idempotent_draft_only_and_optimistically_locked():
    store = MemoryRuntimePlanDraftStore()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_plan_draft_store] = lambda: store
    app.dependency_overrides[require_trace_access] = lambda: None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/runtime-plan-drafts", json=payload())
        duplicate = await client.post("/api/v1/runtime-plan-drafts", json=payload(expected_version=1))
        conflict = await client.post("/api/v1/runtime-plan-drafts", json=payload(expected_version=2))
    assert first.status_code == 200 and first.json()["status"] == "active"
    assert duplicate.json()["draft_id"] == first.json()["draft_id"] and duplicate.json()["reused"] is True
    assert conflict.status_code == 409
