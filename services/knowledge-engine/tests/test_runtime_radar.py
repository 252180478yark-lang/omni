from datetime import datetime, timezone
from pathlib import Path
import sys

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.runtime_trace import EventType, ReadWrite, RuntimeEvent, RuntimeStatus, SpanKind
from app.services.runtime_radar import detect_runtime_findings


def event(**overrides):
    return RuntimeEvent(
        cursor=1, source="agent.websocket", event_id="event:gap", trace_id="trace:radar", execution_id="execution:radar",
        span_id=None, parent_span_id=None, correlation_id=None, session_id=None, gate_id=None, sequence=None,
        event_type=EventType.GAP, status=RuntimeStatus.PARTIAL, span_kind=SpanKind.GAP, node_id=None, read_write=ReadWrite.NONE,
        payload_schema=[], payload_summary={}, observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 8, 1, tzinfo=timezone.utc), retention_until=datetime(2026, 9, 1, tzinfo=timezone.utc), ordering="ordering_unknown", **overrides,
    )


def test_radar_keeps_unknown_source_open_and_never_promotes_suggestions_to_facts():
    findings = detect_runtime_findings(
        "trace:radar", [event()], source_status="partial", delivery_state="verified_not_delivered",
        graph_unknown_nodes=["service:unknown"], graph_diagnostics=["sha256:" + "a" * 64],
    )
    codes = {item.code for item in findings}
    assert {"runtime_event_unmapped", "runtime_event_ordering_unknown", "runtime_collector_partial", "delivery_not_attested"} <= codes
    assert {"planned_fact_unknown", "fact_collector_diagnostic"} <= codes
    assert all(item.classification.value == "observed_fact" for item in findings)
    assert next(item for item in findings if item.code == "runtime_collector_partial").state.value == "stale"
