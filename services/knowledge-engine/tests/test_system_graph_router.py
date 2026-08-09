from pathlib import Path
import asyncio
import sys
import time

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers import system_graph
from app.services.system_graph.repository import MemoryGraphRepository
from app.services.system_graph.scanner import ScanRequest


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


@pytest.mark.asyncio
async def test_snapshot_adapter_persists_cold_scan_and_reuses_it(monkeypatch):
    repository = MemoryGraphRepository()
    original = system_graph.scan_repository
    snapshot = original(ScanRequest(repo=system_graph.repository_root(), dynamic=False))
    scans = 0

    def scan(request):
        nonlocal scans
        scans += 1
        assert request.dynamic is False
        return snapshot

    monkeypatch.setattr(system_graph, "scan_repository", scan)
    first = await system_graph.read_system_graph_snapshot(repository)
    second = await system_graph.read_system_graph_snapshot(repository)

    assert scans == 1
    assert first.snapshot_id == snapshot.snapshot_id
    assert second.snapshot_id == snapshot.snapshot_id
    assert (await repository.latest_snapshot()).snapshot_id == snapshot.snapshot_id


@pytest.mark.asyncio
async def test_snapshot_adapter_single_flights_concurrent_cold_reads(monkeypatch):
    repository = MemoryGraphRepository()
    original = system_graph.scan_repository
    snapshot = original(ScanRequest(repo=system_graph.repository_root(), dynamic=False))
    scans = 0

    def slow_scan(_request):
        nonlocal scans
        scans += 1
        time.sleep(0.02)
        return snapshot

    monkeypatch.setattr(system_graph, "scan_repository", slow_scan)
    results = await asyncio.gather(
        system_graph.read_system_graph_snapshot(repository),
        system_graph.read_system_graph_snapshot(repository),
        system_graph.read_system_graph_snapshot(repository),
    )

    assert scans == 1
    assert {item.snapshot_id for item in results} == {snapshot.snapshot_id}
