from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers import runtime_findings
from app.routers.runtime_traces import get_trace_ledger, require_trace_access
from app.schemas.runtime_trace import EventType, RuntimeEventInput, RuntimeStatus, SpanKind
from app.services.runtime_trace import MemoryTraceLedger


@pytest.mark.asyncio
async def test_radar_api_marks_fact_scan_failure_partial_without_resolving_gap(monkeypatch):
    ledger = MemoryTraceLedger()
    await ledger.append(RuntimeEventInput(
        source="agent.websocket", event_id="event:router-gap", trace_id="trace:router", execution_id="execution:router",
        event_type=EventType.GAP, status=RuntimeStatus.PARTIAL, span_kind=SpanKind.GAP, node_id=None,
        observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    ))
    monkeypatch.setattr(runtime_findings, "scan_repository", lambda _request: (_ for _ in ()).throw(RuntimeError("fixture failure")))
    app = FastAPI()
    app.include_router(runtime_findings.router)
    app.dependency_overrides[get_trace_ledger] = lambda: ledger
    app.dependency_overrides[require_trace_access] = lambda: None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/runtime-findings?trace_id=trace:router")
    body = response.json()
    assert response.status_code == 200 and body["source_status"] == "partial"
    assert {item["code"] for item in body["findings"]} >= {"runtime_event_unmapped", "runtime_collector_partial"}
