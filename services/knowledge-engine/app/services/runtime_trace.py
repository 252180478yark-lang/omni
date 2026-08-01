"""Append-only, redacted runtime trace storage and HTTP/MCP context propagation."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.schemas.runtime_trace import (
    EventType,
    ReadWrite,
    RuntimeEvent,
    RuntimeEventAppendResponse,
    RuntimeEventInput,
    RuntimeEventPage,
    RuntimeExecutionPage,
    RuntimeExecutionSummary,
    RuntimeStatus,
    SpanKind,
)

_SENSITIVE_KEY = re.compile(r"(?:secret|token|password|authorization|cookie|prompt|sql|attachment|content)", re.I)
_SENSITIVE_VALUE = re.compile(r"(?:bearer\s+|api[_-]?key|password=|token=|secret=)", re.I)
_context: ContextVar["RuntimeTraceContext | None"] = ContextVar("runtime_trace_context", default=None)


@dataclass(frozen=True)
class RuntimeTraceContext:
    trace_id: str
    execution_id: str
    span_id: str | None = None
    parent_span_id: str | None = None
    correlation_id: str | None = None
    session_id: str | None = None
    gate_id: str | None = None


def _identifier(value: str | None) -> str | None:
    if value and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}", value):
        return value
    return None


def context_from_headers(headers: Any) -> RuntimeTraceContext:
    traceparent = str(headers.get("traceparent", ""))
    parts = traceparent.split("-")
    trace_id = _identifier(headers.get("x-omni-trace-id"))
    parent_span_id = _identifier(headers.get("x-omni-parent-span-id"))
    if len(parts) == 4 and re.fullmatch(r"[0-9a-f]{32}", parts[1], re.I):
        trace_id = trace_id or f"otel:{parts[1].lower()}"
        parent_span_id = parent_span_id or f"otel:{parts[2].lower()}"
    trace_id = trace_id or f"trace:{uuid.uuid4().hex}"
    return RuntimeTraceContext(
        trace_id=trace_id,
        execution_id=_identifier(headers.get("x-omni-execution-id")) or trace_id,
        span_id=_identifier(headers.get("x-omni-span-id")),
        parent_span_id=parent_span_id,
        correlation_id=_identifier(headers.get("x-omni-correlation-id")),
        session_id=_identifier(headers.get("x-omni-session-id")),
        gate_id=_identifier(headers.get("x-omni-gate-id")),
    )


def activate_context(context: RuntimeTraceContext) -> Token[RuntimeTraceContext | None]:
    return _context.set(context)


def reset_context(token: Token[RuntimeTraceContext | None]) -> None:
    _context.reset(token)


def current_context() -> RuntimeTraceContext | None:
    return _context.get()


def redact_payload(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k)[:80]: redact_payload(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_payload(item, key=key) for item in value[:20]]
    if isinstance(value, str):
        if _SENSITIVE_VALUE.search(value):
            return "[REDACTED]"
        return value[:256]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:256]


def _payload_schema(payload: dict[str, Any]) -> list[str]:
    return sorted(str(key)[:80] for key in payload)[:100]


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _json_value(value: Any, expected_type: type, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, expected_type):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return default
        return decoded if isinstance(decoded, expected_type) else default
    return default


def _event_from_row(row: Any, *, ordering: str = "known") -> RuntimeEvent:
    return RuntimeEvent(
        cursor=int(row["cursor"]), source=row["source"], event_id=row["event_id"],
        trace_id=row["trace_id"], execution_id=row["execution_id"], span_id=row["span_id"],
        parent_span_id=row["parent_span_id"], correlation_id=row["correlation_id"],
        session_id=row["session_id"], gate_id=row["gate_id"], sequence=row["sequence"],
        event_type=EventType(row["event_type"]), status=RuntimeStatus(row["status"]),
        span_kind=SpanKind(row["span_kind"]), node_id=row["node_id"],
        read_write=ReadWrite(row["read_write"]), payload_schema=_json_value(row["payload_schema"], list, []),
        payload_summary=_json_value(row["payload_summary"], dict, {}), observed_at=row["observed_at"],
        received_at=row["received_at"], retention_until=row["retention_until"], ordering=ordering,
    )


def _ordered(events: list[RuntimeEvent]) -> list[RuntimeEvent]:
    seen_sequences: set[int] = set()
    result: list[RuntimeEvent] = []
    for event in sorted(events, key=lambda item: (item.sequence is None, item.sequence or 0, item.observed_at, item.cursor)):
        unknown = event.sequence is None or (event.sequence in seen_sequences if event.sequence is not None else False)
        if event.sequence is not None:
            seen_sequences.add(event.sequence)
        result.append(event.model_copy(update={"ordering": "ordering_unknown" if unknown else "known"}))
    return result


class TraceLedger(Protocol):
    async def append(self, event: RuntimeEventInput) -> RuntimeEventAppendResponse: ...
    async def events(self, trace_id: str, cursor: int = 0, limit: int = 500) -> RuntimeEventPage: ...
    async def purge_expired(self, *, now: datetime | None = None) -> int: ...
    async def active_runs(self, limit: int = 50) -> RuntimeExecutionPage: ...


def _redacted_count(events: list[RuntimeEvent]) -> int:
    return sum(str(event.payload_summary).count("[REDACTED]") for event in events)


def _dropped_count(events: list[RuntimeEvent]) -> int:
    return sum(1 for event in events if event.event_type is EventType.GAP)


def _duplicate_matches(row: Any, event: RuntimeEventInput, payload_summary: dict[str, Any]) -> bool:
    return all((
        row["trace_id"] == event.trace_id,
        row["execution_id"] == event.execution_id,
        row["span_id"] == event.span_id,
        row["parent_span_id"] == event.parent_span_id,
        row["correlation_id"] == event.correlation_id,
        row["session_id"] == event.session_id,
        row["gate_id"] == event.gate_id,
        row["sequence"] == event.sequence,
        row["event_type"] == event.event_type.value,
        row["status"] == event.status.value,
        row["span_kind"] == event.span_kind.value,
        row["node_id"] == event.node_id,
        row["read_write"] == event.read_write.value,
        _json_value(row["payload_summary"], dict, {}) == payload_summary,
    ))


class DatabaseTraceLedger:
    """PostgreSQL adapter. INSERT only; duplicate source/event IDs return the original fact."""

    async def append(self, event: RuntimeEventInput) -> RuntimeEventAppendResponse:
        from app.database import get_pool

        payload_summary = redact_payload(event.payload)
        retention = event.observed_at + timedelta(days=event.retention_days)
        pool = get_pool()
        async with pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                "SELECT * FROM mcp.runtime_events WHERE source=$1 AND event_id=$2 FOR UPDATE",
                event.source,
                event.event_id,
            )
            if existing is not None:
                if not _duplicate_matches(existing, event, payload_summary):
                    raise ValueError("runtime_event_id_conflict")
                return RuntimeEventAppendResponse(event=_event_from_row(existing), duplicate=True)
            execution_row = await conn.fetchrow(
                """INSERT INTO mcp.runtime_executions(trace_id, execution_id, correlation_id, session_id, gate_id)
                   VALUES($1,$2,$3,$4,$5)
                   ON CONFLICT(trace_id) DO UPDATE SET
                     correlation_id=COALESCE(mcp.runtime_executions.correlation_id,EXCLUDED.correlation_id),
                     session_id=COALESCE(mcp.runtime_executions.session_id,EXCLUDED.session_id),
                     gate_id=COALESCE(mcp.runtime_executions.gate_id,EXCLUDED.gate_id),updated_at=NOW()
                   WHERE mcp.runtime_executions.execution_id=EXCLUDED.execution_id
                     AND (mcp.runtime_executions.correlation_id IS NULL OR EXCLUDED.correlation_id IS NULL OR mcp.runtime_executions.correlation_id=EXCLUDED.correlation_id)
                     AND (mcp.runtime_executions.session_id IS NULL OR EXCLUDED.session_id IS NULL OR mcp.runtime_executions.session_id=EXCLUDED.session_id)
                     AND (mcp.runtime_executions.gate_id IS NULL OR EXCLUDED.gate_id IS NULL OR mcp.runtime_executions.gate_id=EXCLUDED.gate_id)
                   RETURNING trace_id""",
                event.trace_id, event.execution_id, event.correlation_id, event.session_id, event.gate_id,
            )
            if execution_row is None:
                raise ValueError("runtime_trace_identity_conflict")
            if event.span_id:
                span_row = await conn.fetchrow(
                    """INSERT INTO mcp.runtime_spans(trace_id, span_id, parent_span_id, kind, node_id, status, started_at, ended_at)
                       VALUES($1,$2,$3,$4,$5,$6,
                         CASE WHEN $8::text='started' THEN $7::timestamptz ELSE NULL END,
                         CASE WHEN $8::text IN ('completed','failed','cancelled') THEN $7::timestamptz ELSE NULL END)
                       ON CONFLICT(trace_id, span_id) DO UPDATE SET
                         parent_span_id=COALESCE(mcp.runtime_spans.parent_span_id,EXCLUDED.parent_span_id),
                         node_id=COALESCE(mcp.runtime_spans.node_id,EXCLUDED.node_id),status=EXCLUDED.status,
                         started_at=COALESCE(mcp.runtime_spans.started_at, EXCLUDED.started_at),
                         ended_at=COALESCE(EXCLUDED.ended_at,mcp.runtime_spans.ended_at)
                       WHERE mcp.runtime_spans.kind=EXCLUDED.kind
                         AND (mcp.runtime_spans.parent_span_id IS NULL OR EXCLUDED.parent_span_id IS NULL OR mcp.runtime_spans.parent_span_id=EXCLUDED.parent_span_id)
                         AND (mcp.runtime_spans.node_id IS NULL OR EXCLUDED.node_id IS NULL OR mcp.runtime_spans.node_id=EXCLUDED.node_id)
                         AND NOT (mcp.runtime_spans.ended_at IS NOT NULL AND EXCLUDED.ended_at IS NULL)
                         AND NOT (mcp.runtime_spans.ended_at IS NOT NULL AND EXCLUDED.ended_at IS NOT NULL AND mcp.runtime_spans.status<>EXCLUDED.status)
                       RETURNING span_id""",
                    event.trace_id, event.span_id, event.parent_span_id, event.span_kind.value, event.node_id,
                    event.status.value, event.observed_at, event.event_type.value,
                )
                if span_row is None:
                    raise ValueError("runtime_span_identity_conflict")
            row = await conn.fetchrow(
                """INSERT INTO mcp.runtime_events(source,event_id,trace_id,execution_id,span_id,parent_span_id,correlation_id,session_id,gate_id,sequence,event_type,status,span_kind,node_id,read_write,payload_schema,payload_summary,observed_at,retention_until)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,$17::jsonb,$18,$19)
                   ON CONFLICT(source,event_id) DO NOTHING
                   RETURNING *""",
                event.source, event.event_id, event.trace_id, event.execution_id, event.span_id, event.parent_span_id,
                event.correlation_id, event.session_id, event.gate_id, event.sequence, event.event_type.value,
                event.status.value, event.span_kind.value, event.node_id, event.read_write.value,
                json.dumps(_payload_schema(event.payload)), json.dumps(payload_summary, ensure_ascii=False), event.observed_at, retention,
            )
            if row is None:
                row = await conn.fetchrow("SELECT * FROM mcp.runtime_events WHERE source=$1 AND event_id=$2", event.source, event.event_id)
                if row is None or not _duplicate_matches(row, event, payload_summary):
                    raise ValueError("runtime_event_id_conflict")
                return RuntimeEventAppendResponse(event=_event_from_row(row), duplicate=True)
        return RuntimeEventAppendResponse(event=_event_from_row(row), duplicate=False)

    async def events(self, trace_id: str, cursor: int = 0, limit: int = 500) -> RuntimeEventPage:
        from app.database import get_pool

        rows = await get_pool().fetch(
            "SELECT * FROM mcp.runtime_events WHERE trace_id=$1 AND cursor>$2 AND retention_until>NOW() ORDER BY cursor ASC LIMIT $3",
            trace_id, cursor, limit + 1,
        )
        has_more = len(rows) > limit
        events = _ordered([_event_from_row(row) for row in rows[:limit]])
        return RuntimeEventPage(
            trace_id=trace_id, events=events,
            next_cursor=max((event.cursor for event in events), default=None),
            replay_hash=_hash([item.model_dump(mode="json") for item in events]),
            partial=any(item.status in {RuntimeStatus.PARTIAL, RuntimeStatus.UNKNOWN} or item.event_type is EventType.GAP for item in events),
            has_more=has_more,
            dropped_count=_dropped_count(events),
            redacted_count=_redacted_count(events),
        )

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        from app.database import get_pool

        cutoff = now or datetime.now(timezone.utc)
        result = await get_pool().execute(
            "DELETE FROM mcp.runtime_events WHERE retention_until <= $1",
            cutoff,
        )
        return int(result.rsplit(" ", 1)[-1])

    async def active_runs(self, limit: int = 50) -> RuntimeExecutionPage:
        from app.database import get_pool

        rows = await get_pool().fetch(
            """SELECT x.trace_id,x.execution_id,x.session_id,x.gate_id,
                      latest.status,counts.event_count,latest.cursor AS last_cursor,x.updated_at
                 FROM mcp.runtime_executions x
                 JOIN LATERAL (
                   SELECT status,cursor FROM mcp.runtime_events e
                    WHERE e.trace_id=x.trace_id AND e.retention_until>NOW()
                    ORDER BY cursor DESC LIMIT 1
                 ) latest ON TRUE
                 JOIN LATERAL (
                   SELECT COUNT(*)::BIGINT AS event_count FROM mcp.runtime_events e
                    WHERE e.trace_id=x.trace_id AND e.retention_until>NOW()
                 ) counts ON TRUE
                ORDER BY (latest.status='running') DESC,x.updated_at DESC LIMIT $1""",
            limit,
        )
        return RuntimeExecutionPage(runs=[RuntimeExecutionSummary(**dict(row)) for row in rows])


class MemoryTraceLedger:
    """Fixture adapter with identical dedupe and replay semantics; never a production source."""

    def __init__(self) -> None:
        self._events: list[RuntimeEvent] = []
        self._by_source_event: dict[tuple[str, str], RuntimeEvent] = {}

    async def append(self, event: RuntimeEventInput) -> RuntimeEventAppendResponse:
        key = (event.source, event.event_id)
        if key in self._by_source_event:
            existing = self._by_source_event[key]
            candidate = {
                "trace_id": event.trace_id,
                "execution_id": event.execution_id,
                "span_id": event.span_id,
                "parent_span_id": event.parent_span_id,
                "correlation_id": event.correlation_id,
                "session_id": event.session_id,
                "gate_id": event.gate_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "status": event.status,
                "span_kind": event.span_kind,
                "node_id": event.node_id,
                "read_write": event.read_write,
                "payload_summary": redact_payload(event.payload),
            }
            if any(getattr(existing, field) != value for field, value in candidate.items()):
                raise ValueError("runtime_event_id_conflict")
            return RuntimeEventAppendResponse(event=existing, duplicate=True)
        trace_events = [item for item in self._events if item.trace_id == event.trace_id]
        if trace_events:
            if any(item.execution_id != event.execution_id for item in trace_events):
                raise ValueError("runtime_trace_identity_conflict")
            for field in ("correlation_id", "session_id", "gate_id"):
                observed = {getattr(item, field) for item in trace_events if getattr(item, field) is not None}
                incoming = getattr(event, field)
                if incoming is not None and observed and incoming not in observed:
                    raise ValueError("runtime_trace_identity_conflict")
        span_events = [item for item in trace_events if event.span_id and item.span_id == event.span_id]
        if span_events:
            if any(item.span_kind != event.span_kind for item in span_events):
                raise ValueError("runtime_span_identity_conflict")
            for field in ("parent_span_id", "node_id"):
                observed = {getattr(item, field) for item in span_events if getattr(item, field) is not None}
                incoming = getattr(event, field)
                if incoming is not None and observed and incoming not in observed:
                    raise ValueError("runtime_span_identity_conflict")
            terminal = next((item for item in span_events if item.event_type in {EventType.COMPLETED, EventType.FAILED, EventType.CANCELLED}), None)
            if terminal and (event.event_type not in {EventType.COMPLETED, EventType.FAILED, EventType.CANCELLED} or terminal.status != event.status):
                raise ValueError("runtime_span_identity_conflict")
        runtime_event = RuntimeEvent(
            cursor=len(self._events) + 1, source=event.source, event_id=event.event_id, trace_id=event.trace_id,
            execution_id=event.execution_id, span_id=event.span_id, parent_span_id=event.parent_span_id,
            correlation_id=event.correlation_id, session_id=event.session_id, gate_id=event.gate_id,
            sequence=event.sequence, event_type=event.event_type, status=event.status, span_kind=event.span_kind,
            node_id=event.node_id, read_write=event.read_write, payload_schema=_payload_schema(event.payload),
            payload_summary=redact_payload(event.payload), observed_at=event.observed_at,
            received_at=datetime.now(timezone.utc), retention_until=event.observed_at + timedelta(days=event.retention_days),
        )
        self._events.append(runtime_event)
        self._by_source_event[key] = runtime_event
        return RuntimeEventAppendResponse(event=runtime_event)

    async def events(self, trace_id: str, cursor: int = 0, limit: int = 500) -> RuntimeEventPage:
        active = [event for event in self._events if event.trace_id == trace_id and event.cursor > cursor and event.retention_until > datetime.now(timezone.utc)]
        has_more = len(active) > limit
        events = _ordered(active[:limit])
        return RuntimeEventPage(
            trace_id=trace_id, events=events, next_cursor=max((event.cursor for event in events), default=None),
            replay_hash=_hash([item.model_dump(mode="json") for item in events]),
            partial=any(item.status in {RuntimeStatus.PARTIAL, RuntimeStatus.UNKNOWN} or item.event_type is EventType.GAP for item in events),
            has_more=has_more,
            dropped_count=_dropped_count(events),
            redacted_count=_redacted_count(events),
        )

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        cutoff = now or datetime.now(timezone.utc)
        before = len(self._events)
        self._events = [event for event in self._events if event.retention_until > cutoff]
        self._by_source_event = {(event.source, event.event_id): event for event in self._events}
        return before - len(self._events)

    async def active_runs(self, limit: int = 50) -> RuntimeExecutionPage:
        active = [event for event in self._events if event.retention_until > datetime.now(timezone.utc)]
        by_trace: dict[str, list[RuntimeEvent]] = {}
        for event in active:
            by_trace.setdefault(event.trace_id, []).append(event)
        runs = []
        for trace_events in by_trace.values():
            latest = max(trace_events, key=lambda event: event.cursor)
            runs.append(RuntimeExecutionSummary(
                trace_id=latest.trace_id, execution_id=latest.execution_id,
                session_id=latest.session_id, gate_id=latest.gate_id, status=latest.status,
                event_count=len(trace_events), last_cursor=latest.cursor, updated_at=latest.received_at,
            ))
        runs.sort(key=lambda run: (run.status is RuntimeStatus.RUNNING, run.updated_at), reverse=True)
        return RuntimeExecutionPage(runs=runs[:limit])


async def emit_audit_event(
    ledger: TraceLedger,
    *,
    tool_call_id: str,
    tool_name: str,
    status: RuntimeStatus,
    event_type: EventType,
    duration_ms: int | None = None,
) -> RuntimeEventAppendResponse:
    context = current_context() or RuntimeTraceContext(trace_id=f"audit:{tool_call_id}", execution_id=f"audit:{tool_call_id}")
    return await ledger.append(RuntimeEventInput(
        source="mcp.audit", event_id=f"{tool_call_id}:{event_type.value}", trace_id=context.trace_id,
        execution_id=context.execution_id, span_id=f"tool:{tool_call_id}", parent_span_id=context.span_id,
        correlation_id=context.correlation_id, session_id=context.session_id, gate_id=context.gate_id,
        event_type=event_type, status=status, span_kind=SpanKind.TOOL, node_id=f"mcp_tool:{tool_name}",
        read_write=ReadWrite.NONE, payload={"tool_name": tool_name, "duration_ms": duration_ms},
    ))
