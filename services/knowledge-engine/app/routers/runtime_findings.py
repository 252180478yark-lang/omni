"""Read-only S9 deterministic runtime radar endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.schemas.runtime_trace import RuntimeFindingPage
from app.routers.system_graph import repository_root
from app.services.runtime_radar import detect_runtime_findings
from app.services.runtime_trace import TraceLedger
from app.routers.runtime_traces import get_trace_ledger, require_trace_access
from app.services.system_graph.scanner import ScanRequest, scan_repository

router = APIRouter(prefix="/api/v1/runtime-findings", tags=["runtime-radar"])


@router.get("", response_model=RuntimeFindingPage, dependencies=[Depends(require_trace_access)])
async def list_runtime_findings(
    trace_id: str,
    source_status: str = Query(default="success", pattern="^(success|partial|unknown)$"),
    delivery_state: str = Query(default="verified_not_delivered", pattern="^(delivered|verified_not_delivered|stale|blocked)$"),
    ledger: TraceLedger = Depends(get_trace_ledger),
) -> RuntimeFindingPage:
    events = []
    cursor = 0
    while True:
        page = await ledger.events(trace_id, cursor=cursor, limit=2000)
        events.extend(page.events)
        if not page.has_more:
            break
        if page.next_cursor is None or page.next_cursor <= cursor:
            source_status = "partial" if source_status == "success" else source_status
            break
        cursor = page.next_cursor
    # S9 consumes facts from the only available S3 scanner projection. A scan
    # failure is a partial source, never evidence that a runtime node vanished.
    known_node_ids: set[str] | None = None
    graph_unknown_nodes: list[str] = []
    graph_diagnostics: list[str] = []
    try:
        snapshot = scan_repository(ScanRequest(repo=repository_root(), dynamic=False))
        known_node_ids = {node.id for node in snapshot.content.nodes}
        graph_unknown_nodes = [node.id for node in snapshot.content.nodes if node.state.existence.value == "unknown"]
        graph_diagnostics = [diagnostic.fingerprint for diagnostic in snapshot.content.diagnostics]
    except Exception:
        source_status = "partial" if source_status == "success" else source_status
    return RuntimeFindingPage(
        trace_id=trace_id,
        findings=detect_runtime_findings(
            trace_id, events, known_node_ids=known_node_ids, source_status=source_status,
            delivery_state=delivery_state, graph_unknown_nodes=graph_unknown_nodes,
            graph_diagnostics=graph_diagnostics,
        ),
        source_status=source_status,
    )
