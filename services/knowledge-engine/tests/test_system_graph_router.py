from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers import system_graph


@pytest.mark.asyncio
async def test_snapshot_adapter_uses_static_scanner_only(monkeypatch):
    observed = {}
    original = system_graph.scan_repository

    def scan(request):
        observed["dynamic"] = request.dynamic
        return original(request)

    monkeypatch.setattr(system_graph, "scan_repository", scan)
    app = FastAPI()
    app.include_router(system_graph.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system-graph/snapshot")
    assert response.status_code == 200
    assert observed["dynamic"] is False
    assert response.json()["snapshot_id"].startswith("sha256:")
