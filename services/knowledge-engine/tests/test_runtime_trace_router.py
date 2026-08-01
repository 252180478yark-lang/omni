from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.runtime_traces import get_trace_ledger, require_trace_access, router
from app.services.runtime_trace import MemoryTraceLedger


def make_app(ledger: MemoryTraceLedger) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_trace_ledger] = lambda: ledger
    app.dependency_overrides[require_trace_access] = lambda: None
    return app


def request_payload(trace_id="trace:router", event_id="event:router", sequence=None):
    return {
        "source": "mcp.audit", "event_id": event_id, "trace_id": trace_id, "execution_id": "execution:router",
        "span_id": "span:router", "event_type": "started", "status": "running", "span_kind": "tool", "node_id": "mcp:list_skus",
        "payload": {"tool_name": "list_skus"}, "sequence": sequence,
    }


@pytest.mark.asyncio
async def test_append_and_cursor_reconnect_are_idempotent():
    transport = httpx.ASGITransport(app=make_app(MemoryTraceLedger()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/runtime-traces/trace:router/events", json=request_payload())
        duplicate = await client.post("/api/v1/runtime-traces/trace:router/events", json=request_payload())
        page = await client.get("/api/v1/runtime-traces/trace:router/events?cursor=0")
        after_cursor = await client.get("/api/v1/runtime-traces/trace:router/events?cursor=1")
        active = await client.get("/api/v1/runtime-traces/active")
    assert first.status_code == 200 and duplicate.json()["duplicate"] is True
    assert len(page.json()["events"]) == 1 and after_cursor.json()["events"] == []
    assert active.json()["runs"][0]["trace_id"] == "trace:router"


@pytest.mark.asyncio
async def test_rejects_path_body_trace_mismatch():
    transport = httpx.ASGITransport(app=make_app(MemoryTraceLedger()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/runtime-traces/trace:other/events", json=request_payload())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "trace_id_path_body_mismatch"


@pytest.mark.asyncio
async def test_rejects_conflicting_source_event_identity():
    transport = httpx.ASGITransport(app=make_app(MemoryTraceLedger()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/runtime-traces/trace:router/events", json=request_payload())
        conflict_payload = request_payload(trace_id="trace:other")
        conflict = await client.post("/api/v1/runtime-traces/trace:other/events", json=conflict_payload)
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "runtime_event_id_conflict"


@pytest.mark.asyncio
async def test_rejects_conflicting_trace_identity_with_distinct_event_id():
    transport = httpx.ASGITransport(app=make_app(MemoryTraceLedger()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/runtime-traces/trace:router/events", json=request_payload())
        conflict = await client.post("/api/v1/runtime-traces/trace:router/events", json={
            **request_payload(event_id="event:other"), "execution_id": "execution:other",
        })
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "runtime_trace_identity_conflict"


@pytest.mark.asyncio
async def test_replay_supports_cursor_paging_without_reexecuting_events():
    transport = httpx.ASGITransport(app=make_app(MemoryTraceLedger()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/runtime-traces/trace:router/events", json=request_payload(event_id="event:first", sequence=1))
        await client.post("/api/v1/runtime-traces/trace:router/events", json=request_payload(event_id="event:second", sequence=2))
        first = await client.get("/api/v1/runtime-traces/trace:router/replay?cursor=0&limit=1")
        second = await client.get(f"/api/v1/runtime-traces/trace:router/replay?cursor={first.json()['next_cursor']}&limit=1")
    assert first.json()["has_more"] is True
    assert [item["event_id"] for item in first.json()["events"]] == ["event:first"]
    assert [item["event_id"] for item in second.json()["events"]] == ["event:second"]
    assert second.json()["has_more"] is False
