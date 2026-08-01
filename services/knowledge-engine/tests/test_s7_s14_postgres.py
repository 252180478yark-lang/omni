"""Disposable PostgreSQL proof for graph persistence, metric ownership and S13 stores."""

from datetime import date, datetime, timezone
from decimal import Decimal
import os
import json

import asyncpg
import pytest

from app import database
from app.schemas.system_graph import GraphEdge, GraphNode, GraphSnapshot, GraphSnapshotContent, SourceResult, SourceStatus
from app.services.compatibility import CompatibilityEvent, append_compatibility_event
from app.services.metric_ownership import MetricObservation, submit_metric_observation
from app.services.system_graph.canonical import sha256_value
from app.services.system_graph.repository import DatabaseGraphRepository, refresh_fingerprint


def graph_snapshot() -> GraphSnapshot:
    nodes = [
        GraphNode(id="ui_route:/workspace", kind="ui_route", key="/workspace", label="Workspace"),
        GraphNode(id="service:graph", kind="service", key="graph", label="Graph repository"),
    ]
    content = GraphSnapshotContent(
        commit="a" * 40,
        definition_revision="sha256:" + "b" * 64,
        collector_versions={"fixture": "1"},
        feature_ids=["system-command-center"],
        source_results=[SourceResult(collector_id="fixture", version="1", status=SourceStatus.SUCCESS)],
        nodes=nodes,
        edges=[GraphEdge(id="edge:workspace-graph", relation="reads", source=nodes[0].id, target=nodes[1].id)],
    )
    digest = sha256_value(content.model_dump(mode="json"))
    return GraphSnapshot(snapshot_id=digest, content_hash=digest, generated_at_utc=datetime.now(timezone.utc), content=content)


@pytest.mark.asyncio
async def test_s7_s14_stores_on_disposable_postgres() -> None:
    dsn = os.getenv("OMNI_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("OMNI_TEST_DATABASE_URL is required")
    if os.getenv("OMNI_DATABASE_DISPOSABLE", "").lower() != "true":
        pytest.fail("S7-S14 PostgreSQL verification refuses a non-disposable database")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    database._pool = pool
    try:
        assert (await pool.fetchval("SELECT current_database()" )).startswith("omni_verify_")
        repository = DatabaseGraphRepository()
        fingerprint = refresh_fingerprint({"feature_ids": [], "include_runtime": False, "idempotency_key": "postgres-s7-s14"})
        refresh, created = await repository.begin_refresh(fingerprint=fingerprint, actor_id="verification", request={"idempotency_key": "postgres-s7-s14"})
        duplicate, duplicate_created = await repository.begin_refresh(fingerprint=fingerprint, actor_id="verification", request={"idempotency_key": "postgres-s7-s14"})
        assert created is True and duplicate_created is False and duplicate.refresh_id == refresh.refresh_id
        snapshot = graph_snapshot()
        await repository.save_snapshot(snapshot)
        completed = await repository.complete_refresh(refresh.refresh_id, snapshot)
        assert completed.state == "completed"
        assert (await repository.get_snapshot(snapshot.snapshot_id)).content_hash == snapshot.content_hash

        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO mvp_sku(id,name,douyin_product_id,status,source)
                   VALUES('SKU-VERIFY','verification','verify-product','active','verification')
                   ON CONFLICT(id) DO NOTHING"""
            )
            owner = MetricObservation("SKU-VERIFY", date(2026, 8, 1), "verify_metric", Decimal("10"), "verification", "owner")
            challenger = MetricObservation("SKU-VERIFY", date(2026, 8, 1), "verify_metric", Decimal("20"), "verification", "challenger")
            first = await submit_metric_observation(conn, owner)
            second = await submit_metric_observation(conn, challenger)
            assert first.canonical_updated is True and second.canonical_updated is False
            assert await conn.fetchval("SELECT value FROM mvp_daily_metric WHERE sku_id='SKU-VERIFY' AND metric_name='verify_metric' AND platform='verification'") == Decimal("10")
            assert await conn.fetchval("SELECT COUNT(*) FROM mcp.metric_collisions WHERE collision_id=$1", second.collision_id) == 1

        event_id = await append_compatibility_event(CompatibilityEvent("verification-client", "graph", "host", False, datetime.now(timezone.utc), {"state": "ok", "token": "discard"}))
        metadata = await pool.fetchval("SELECT metadata FROM mcp.compatibility_telemetry WHERE event_id=$1", event_id)
        assert json.loads(metadata) == {"state": "ok"}
    finally:
        database._pool = None
        await pool.close()
