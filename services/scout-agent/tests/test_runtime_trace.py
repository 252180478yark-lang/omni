from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app import runtime_trace
from app.runtime_trace import ScoutTraceMiddleware, current_context, outbound_trace_headers


@pytest.mark.asyncio
async def test_scout_propagates_trace_to_source_adapter_and_response():
    app = FastAPI()
    app.add_middleware(ScoutTraceMiddleware)

    @app.get("/probe")
    async def probe():
        context = current_context()
        return {"trace_id": context.trace_id if context else None, "outbound": outbound_trace_headers()}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe", headers={
            "X-Omni-Trace-Id": "trace:one", "X-Omni-Execution-Id": "execution:one",
            "X-Omni-Parent-Span-Id": "http:one", "X-Omni-Session-Id": "session:one",
        })

    assert response.json()["trace_id"] == "trace:one"
    assert response.json()["outbound"] == {
        "X-Omni-Trace-Id": "trace:one", "X-Omni-Execution-Id": "execution:one",
        "X-Omni-Parent-Span-Id": response.headers["X-Omni-Span-Id"], "X-Omni-Session-Id": "session:one",
    }
    assert response.headers["X-Omni-Trace-Id"] == "trace:one"
    assert response.headers["X-Omni-Trace-Gap"] == "runtime_trace_append_failed"
    assert current_context() is None


@pytest.mark.asyncio
async def test_scout_records_its_own_http_span_when_trace_publisher_is_available(monkeypatch):
    captured = []

    async def publish(context, **kwargs):
        captured.append((context, kwargs))
        return True

    monkeypatch.setattr(runtime_trace, "publish_trace_events", publish)
    app = FastAPI()
    app.add_middleware(ScoutTraceMiddleware)

    @app.get("/probe/{item_id}")
    async def probe(item_id: str):
        return {"item_id": item_id}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe/private-value", headers={
            "X-Omni-Trace-Id": "trace:one", "X-Omni-Execution-Id": "execution:one",
            "X-Omni-Parent-Span-Id": "http:one",
        })

    assert response.status_code == 200 and "X-Omni-Trace-Gap" not in response.headers
    assert captured[0][1]["route"] == "/probe/{item_id}"
    assert captured[0][0].parent_span_id == "http:one"


def test_real_scout_outbound_adapters_attach_the_shared_context():
    services = SERVICE_ROOT / "app" / "services"
    for name in ("anomaly_engine.py", "llm_vision.py"):
        source = (services / name).read_text(encoding="utf-8")
        assert "headers=outbound_trace_headers()" in source
