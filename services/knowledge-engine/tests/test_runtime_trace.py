from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.runtime_trace import EventType, RuntimeEventInput, RuntimeStatus, SpanKind
from app.services.runtime_trace import MemoryTraceLedger, RuntimeTraceContext, activate_context, context_from_headers, current_context, emit_audit_event, redact_payload, reset_context


def payload(**overrides):
    values = {
        "source": "agent.websocket", "event_id": "event:one", "trace_id": "trace:one", "execution_id": "execution:one",
        "span_id": "span:one", "event_type": EventType.COMPLETED, "status": RuntimeStatus.COMPLETED,
        "span_kind": SpanKind.WEBSOCKET, "sequence": 2, "node_id": "page:/workspace", "payload": {"label": "safe", "token": "must-not-leak"},
        "observed_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return RuntimeEventInput(**values)


@pytest.mark.asyncio
async def test_append_only_dedupes_redacts_and_replays_deterministically():
    ledger = MemoryTraceLedger()
    first = await ledger.append(payload())
    duplicate = await ledger.append(payload())
    gap = await ledger.append(payload(
        event_id="event:two", sequence=None, span_id="span:gap", node_id=None,
        event_type=EventType.GAP, status=RuntimeStatus.PARTIAL, span_kind=SpanKind.GAP,
    ))
    page = await ledger.events("trace:one")
    assert first.duplicate is False and duplicate.duplicate is True
    assert len(page.events) == 2 and page.partial is True
    assert page.events[-1].ordering == "ordering_unknown"
    assert page.events[0].payload_summary["token"] == "[REDACTED]"
    assert "must-not-leak" not in str(page.model_dump())
    assert page.replay_hash.startswith("sha256:") and gap.event.node_id is None
    assert page.redacted_count == 2 and page.has_more is False
    runs = await ledger.active_runs()
    assert runs.runs[0].trace_id == "trace:one" and runs.runs[0].event_count == 2


@pytest.mark.asyncio
async def test_conflicting_duplicate_is_rejected_instead_of_hiding_data_loss():
    ledger = MemoryTraceLedger()
    await ledger.append(payload())
    with pytest.raises(ValueError, match="runtime_event_id_conflict"):
        await ledger.append(payload(trace_id="trace:other"))


@pytest.mark.asyncio
async def test_trace_and_span_identity_cannot_be_rewritten_by_later_events():
    ledger = MemoryTraceLedger()
    await ledger.append(payload(event_id="event:started", sequence=1, event_type=EventType.STARTED, status=RuntimeStatus.RUNNING))
    with pytest.raises(ValueError, match="runtime_trace_identity_conflict"):
        await ledger.append(payload(event_id="event:other-execution", execution_id="execution:other", sequence=2))
    with pytest.raises(ValueError, match="runtime_span_identity_conflict"):
        await ledger.append(payload(event_id="event:other-node", node_id="service:other", sequence=2))
    await ledger.append(payload(event_id="event:completed", sequence=2))
    with pytest.raises(ValueError, match="runtime_span_identity_conflict"):
        await ledger.append(payload(event_id="event:late-running", sequence=3, event_type=EventType.STARTED, status=RuntimeStatus.RUNNING))


@pytest.mark.asyncio
async def test_cursor_paging_and_retention_purge_are_explicit():
    ledger = MemoryTraceLedger()
    await ledger.append(payload(event_id="event:one", sequence=1))
    await ledger.append(payload(event_id="event:two", sequence=2))
    first = await ledger.events("trace:one", limit=1)
    second = await ledger.events("trace:one", cursor=first.next_cursor or 0, limit=1)
    assert [event.event_id for event in first.events] == ["event:one"]
    assert first.has_more is True
    assert [event.event_id for event in second.events] == ["event:two"]
    assert second.has_more is False

    expired = payload(
        event_id="event:expired",
        trace_id="trace:expired",
        observed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        retention_days=1,
    )
    await ledger.append(expired)
    assert await ledger.purge_expired(now=datetime(2026, 8, 1, tzinfo=timezone.utc)) == 1
    assert (await ledger.events("trace:expired")).events == []


@pytest.mark.asyncio
async def test_audit_event_inherits_context_and_never_requires_approximate_matching():
    ledger = MemoryTraceLedger()
    token = activate_context(RuntimeTraceContext(trace_id="trace:request", execution_id="execution:request", session_id="session:one", gate_id="gate:one"))
    try:
        await emit_audit_event(ledger, tool_call_id="call:one", tool_name="list_skus", status=RuntimeStatus.RUNNING, event_type=EventType.STARTED)
    finally:
        reset_context(token)
    page = await ledger.events("trace:request")
    assert current_context() is None
    assert page.events[0].span_id == "tool:call:one"
    assert page.events[0].session_id == "session:one"
    assert page.events[0].node_id == "mcp_tool:list_skus"


def test_redaction_blocks_nested_secret_and_prompt_values():
    redacted = redact_payload({"prompt": "do not store", "nested": {"authorization": "Bearer secret"}, "ok": "value"})
    assert redacted == {"prompt": "[REDACTED]", "nested": {"authorization": "[REDACTED]"}, "ok": "value"}


def test_http_context_accepts_explicit_omni_and_w3c_identity_without_guessing():
    omni = context_from_headers({"x-omni-trace-id": "trace:http", "x-omni-execution-id": "execution:http", "x-omni-span-id": "span:parent"})
    w3c = context_from_headers({"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"})
    assert (omni.trace_id, omni.execution_id, omni.span_id) == ("trace:http", "execution:http", "span:parent")
    assert w3c.trace_id == "otel:4bf92f3577b34da6a3ce929d0e0e4736"
    assert w3c.parent_span_id == "otel:00f067aa0ba902b7"


def test_event_contract_rejects_false_terminal_status_and_naive_time():
    with pytest.raises(ValueError, match="completed event requires completed status"):
        payload(event_type=EventType.COMPLETED, status=RuntimeStatus.RUNNING)
    with pytest.raises(ValueError, match="observed_at must include a timezone"):
        payload(observed_at=datetime(2026, 8, 1))
