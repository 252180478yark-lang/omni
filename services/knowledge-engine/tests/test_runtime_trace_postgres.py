"""Real PostgreSQL proof for S8/S9. The test refuses canonical databases."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys

import asyncpg
import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app import database
from app.schemas.runtime_trace import AgentAttachmentInput, EventType, ProviderSessionContract, RuntimeEventInput, RuntimePlanDraftCreate, RuntimeStatus, SpanKind
from app.services.agent_contracts import DatabaseAgentContractStore
from app.services.runtime_plan_drafts import DatabaseRuntimePlanDraftStore
from app.services.runtime_trace import DatabaseTraceLedger


@pytest.mark.asyncio
async def test_runtime_ledger_and_plan_draft_on_disposable_postgres():
    dsn = os.getenv("OMNI_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("OMNI_TEST_DATABASE_URL is required")
    if os.getenv("OMNI_DATABASE_DISPOSABLE", "").lower() != "true":
        pytest.fail("real runtime trace verification refuses a non-disposable database")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    database._pool = pool
    trace_id = "trace:postgres:s8s10"
    try:
        database_name = await pool.fetchval("SELECT current_database()")
        assert database_name.startswith("omni_verify_")
        column = await pool.fetchval(
            "SELECT data_type FROM information_schema.columns WHERE table_schema='mcp' AND table_name='runtime_events' AND column_name='span_kind'"
        )
        assert column == "text"
        ledger = DatabaseTraceLedger()
        item = RuntimeEventInput(
            source="verification.postgres", event_id="event:postgres:s8s10", trace_id=trace_id,
            execution_id="execution:postgres:s8s10", span_id="span:postgres:s8s10",
            event_type=EventType.STARTED, status=RuntimeStatus.RUNNING, span_kind=SpanKind.DATABASE,
            node_id="table:mcp.runtime_events", payload={"token": "never-store-this", "schema": ["span_kind"]},
            observed_at=datetime.now(timezone.utc),
        )
        first = await ledger.append(item)
        duplicate = await ledger.append(item)
        with pytest.raises(ValueError, match="runtime_event_id_conflict"):
            await ledger.append(item.model_copy(update={"trace_id": "trace:postgres:conflict"}))
        with pytest.raises(ValueError, match="runtime_trace_identity_conflict"):
            await ledger.append(item.model_copy(update={"event_id": "event:postgres:other-execution", "execution_id": "execution:postgres:other"}))
        with pytest.raises(ValueError, match="runtime_span_identity_conflict"):
            await ledger.append(item.model_copy(update={"event_id": "event:postgres:other-span-fact", "node_id": "service:other"}))
        page = await ledger.events(trace_id, limit=1)
        assert first.duplicate is False and duplicate.duplicate is True
        assert page.events[0].span_kind is SpanKind.DATABASE
        assert page.events[0].payload_summary["token"] == "[REDACTED]"
        assert "never-store-this" not in str(page.model_dump())

        expired = item.model_copy(update={
            "source": "verification.retention", "event_id": "event:postgres:expired",
            "observed_at": datetime(2020, 1, 1, tzinfo=timezone.utc), "retention_days": 1,
        })
        await ledger.append(expired)
        assert await ledger.purge_expired(now=datetime.now(timezone.utc)) >= 1

        store = DatabaseRuntimePlanDraftStore()
        draft_payload = RuntimePlanDraftCreate(
            finding_fingerprint="sha256:" + "a" * 64, trace_id=trace_id,
            base_snapshot_id="sha256:" + "b" * 64,
        )
        draft = await store.create(draft_payload)
        reused = await store.create(draft_payload.model_copy(update={"expected_version": 1}))
        assert draft.status == "active" and reused.reused is True and reused.draft_id == draft.draft_id

        contracts = DatabaseAgentContractStore()
        fresh = ProviderSessionContract(
            session_id="session:postgres:s8s10", runner_provider="codex", project_dir="E:/agent/omni",
            trace_id=trace_id,
        )
        await contracts.upsert_session(fresh)
        captured = await contracts.upsert_session(fresh.model_copy(update={"runner_session_id": "runner:postgres:s8s10"}))
        attachment = await contracts.record_attachment(AgentAttachmentInput(
            session_id=fresh.session_id, attachment_id="attachment:" + "c" * 32,
            sha256="d" * 64, size_bytes=10, content_type="text/plain", storage_key="sha256/" + "d" * 64 + ".txt",
        ))
        second_session = ProviderSessionContract(
            session_id="session:postgres:s8s10:two", runner_provider="claude", project_dir="E:/agent/omni",
        )
        await contracts.upsert_session(second_session)
        same_blob = await contracts.record_attachment(AgentAttachmentInput(
            session_id=second_session.session_id, attachment_id="attachment:" + "e" * 32,
            sha256="d" * 64, size_bytes=10, content_type="text/plain", storage_key="sha256/" + "d" * 64 + ".txt",
        ))
        assert captured.runner_session_id == "runner:postgres:s8s10" and attachment.size_bytes == 10
        assert same_blob.storage_key == attachment.storage_key and same_blob.attachment_id != attachment.attachment_id
    finally:
        await pool.execute("DELETE FROM mcp.agent_attachments WHERE session_id LIKE 'session:postgres:s8s10%'")
        await pool.execute("DELETE FROM mcp.agent_session_contracts WHERE session_id LIKE 'session:postgres:s8s10%'")
        await pool.execute("DELETE FROM mcp.runtime_plan_drafts WHERE trace_id=$1", trace_id)
        await pool.execute("DELETE FROM mcp.runtime_events WHERE trace_id=$1", trace_id)
        await pool.execute("DELETE FROM mcp.runtime_spans WHERE trace_id=$1", trace_id)
        await pool.execute("DELETE FROM mcp.runtime_executions WHERE trace_id=$1", trace_id)
        database._pool = None
        await pool.close()
