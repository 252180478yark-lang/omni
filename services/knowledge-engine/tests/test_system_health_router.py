from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.system_health import get_health_registry, router
from app.schemas.system_health import FeatureHealth, HealthState, SystemHealthResponse
from app.schemas.system_health import BuildIdentity


class FakeRegistry:
    def __init__(self, state: HealthState = HealthState.UNKNOWN):
        self.state = state

    async def collect(self):
        feature = FeatureHealth(feature_id="example", title="Example", state=self.state)
        return SystemHealthResponse(
            state=self.state,
            healthy_percentage=100 if self.state is HealthState.HEALTHY else 0,
            partial=self.state is HealthState.UNKNOWN,
            generated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            features=[feature],
        )


def make_app(registry: FakeRegistry) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_health_registry] = lambda: registry
    return app


@pytest.mark.asyncio
async def test_aggregate_route_preserves_unknown_partial_state():
    transport = httpx.ASGITransport(app=make_app(FakeRegistry()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/health")
    assert response.status_code == 200
    assert response.json()["state"] == "unknown"
    assert response.json()["partial"] is True


@pytest.mark.asyncio
async def test_single_feature_uses_typed_503_instead_of_empty_success():
    transport = httpx.ASGITransport(app=make_app(FakeRegistry()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/health/features/example")
    assert response.status_code == 503
    assert response.json()["code"] == "feature_unknown"
    assert response.json()["source"] == "example"


@pytest.mark.asyncio
async def test_unknown_feature_is_typed_404():
    transport = httpx.ASGITransport(app=make_app(FakeRegistry(HealthState.HEALTHY)))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/health/features/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_feature"


def test_service_startup_never_runs_schema_migration_and_gates_schedulers():
    source = (SERVICE_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    lifespan_source = source.split("async def lifespan", 1)[1].split("app = FastAPI", 1)[0]
    assert "_migrate_tsv_column(" not in lifespan_source
    assert 'os.getenv("OMNI_SCHEDULER_ENABLED", "false")' in lifespan_source
    assert "if scheduler_enabled:" in lifespan_source
    assert "asyncio.create_task(weekly_self_review_loop())" in lifespan_source
    assert "approval_worker_enabled(allocation)" in lifespan_source


@pytest.mark.asyncio
async def test_existing_health_endpoint_returns_typed_503_when_readiness_unavailable(monkeypatch):
    import json
    import app.services.health_registry as health_registry
    from app.main import health

    async def unavailable():
        return (
            HealthState.UNAVAILABLE,
            "database_read_failed",
            BuildIdentity(
                expected_commit="new",
                observed_commit="new",
                source_fingerprint="sha256:abc",
                worktree_id="wt-1",
                allocation_id="alloc-1",
                runtime_id="runtime-1",
            ),
        )

    monkeypatch.setattr(health_registry, "service_readiness", unavailable)
    response = await health()
    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["status"] == "unavailable"
    assert body["error"]["code"] == "database_read_failed"
    assert body["build_identity"]["allocation_id"] == "alloc-1"
