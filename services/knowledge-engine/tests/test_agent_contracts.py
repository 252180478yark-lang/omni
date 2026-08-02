from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.agent_contracts import get_agent_contract_store, router
from app.routers.runtime_traces import require_trace_access
from app.schemas.runtime_trace import ProviderSessionContract
from app.services.agent_contracts import (
    DatabaseAgentContractStore,
    LEGACY_SESSION_COLUMNS,
    LEGACY_SESSION_PROJECTION,
    MemoryAgentContractStore,
)


@pytest.mark.asyncio
async def test_fresh_session_captures_real_runner_and_attachment_metadata_without_raw_path():
    store = MemoryAgentContractStore()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_agent_contract_store] = lambda: store
    app.dependency_overrides[require_trace_access] = lambda: None
    transport = httpx.ASGITransport(app=app)
    fresh = {"session_id": "session:contract", "runner_provider": "codex", "runner_session_id": None, "project_dir": "E:/agent/omni", "trace_id": "trace:contract"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/v1/agent-contracts/sessions", json=fresh)
        captured = await client.post("/api/v1/agent-contracts/sessions", json={**fresh, "runner_session_id": "runner:real"})
        conflict = await client.post("/api/v1/agent-contracts/sessions", json={**fresh, "runner_session_id": "runner:other"})
        attachment = await client.post("/api/v1/agent-contracts/sessions/session:contract/attachments", json={
            "session_id": "session:contract", "attachment_id": "attachment:" + "d" * 32,
            "sha256": "a" * 64, "size_bytes": 12, "content_type": "text/plain", "storage_key": "sha256/" + "a" * 64 + ".txt",
        })
    assert created.json()["runner_session_id"] is None
    assert captured.json()["runner_session_id"] == "runner:real"
    assert conflict.status_code == 409 and attachment.status_code == 200
    assert "E:/agent/omni" not in str(captured.json())


@pytest.mark.asyncio
async def test_database_store_projects_only_legacy_columns_after_migration_104(monkeypatch):
    now = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
    post_104_row = {
        "session_id": "session:contract",
        "runner_provider": "codex",
        "runner_session_id": "runner:real",
        "project_dir_hash": "sha256:" + "a" * 64,
        "model": "gpt-5",
        "effort": "high",
        "status": "active",
        "trace_id": "trace:contract",
        "created_at": now,
        "updated_at": now,
        "contract_version": "workbench.v1",
        "context_snapshot_id": "context:snapshot-one",
        "requested_provider": "codex",
        "resolved_runner_mode": "host",
        "fallback_reason_code": None,
        "provider_accepted_at": now,
        "parent_session_id": None,
        "project_handle": "project:opaque-one",
        "project_display_name": "omni",
    }

    class AsyncContext:
        def __init__(self, value):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeConnection:
        def __init__(self):
            self.queries = []

        def transaction(self):
            return AsyncContext(self)

        async def fetchrow(self, sql, *args):
            self.queries.append(sql)
            normalized = " ".join(sql.split())
            assert "*" not in normalized
            if normalized.startswith("SELECT "):
                projection = normalized.removeprefix("SELECT ").split(" FROM ", 1)[0]
            else:
                projection = normalized.rsplit(" RETURNING ", 1)[1]
            columns = tuple(column.strip() for column in projection.split(","))
            assert columns == LEGACY_SESSION_COLUMNS
            return {column: post_104_row[column] for column in columns}

    class FakePool:
        def __init__(self):
            self.connection = FakeConnection()

        def acquire(self):
            return AsyncContext(self.connection)

        async def fetchrow(self, sql, *args):
            return await self.connection.fetchrow(sql, *args)

    fake_pool = FakePool()
    monkeypatch.setattr("app.database.get_pool", lambda: fake_pool)
    store = DatabaseAgentContractStore()
    payload = ProviderSessionContract(
        session_id="session:contract",
        runner_provider="codex",
        runner_session_id="runner:real",
        project_dir="E:/agent/omni",
        model="gpt-5",
        effort="high",
        trace_id="trace:contract",
    )

    upserted = await store.upsert_session(payload)
    fetched = await store.get_session(payload.session_id)

    assert fetched is not None
    assert upserted.session_id == fetched.session_id == "session:contract"
    assert LEGACY_SESSION_PROJECTION in fake_pool.connection.queries[0]
    assert "FOR UPDATE" in fake_pool.connection.queries[0]
    assert LEGACY_SESSION_PROJECTION in fake_pool.connection.queries[1]
    assert LEGACY_SESSION_PROJECTION in fake_pool.connection.queries[2]
    assert all("*" not in query for query in fake_pool.connection.queries)
    assert all(
        migration_104_column not in query
        for query in fake_pool.connection.queries
        for migration_104_column in (
            "contract_version",
            "context_snapshot_id",
            "requested_provider",
            "resolved_runner_mode",
            "fallback_reason_code",
            "provider_accepted_at",
            "parent_session_id",
            "project_handle",
            "project_display_name",
        )
    )
