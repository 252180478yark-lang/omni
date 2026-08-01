"""Audited MCP surface for S5 planning and S7 factual graph reads.

FastMCP callers do not carry the owner-authenticated principal required by the
REST boundary. These tools are deliberately non-writing so MCP cannot become
an authentication bypass or a pre-confirmation product writer.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services.system_graph.integration_plans import default_plan_items
from app.services.system_graph.diff import diff_snapshots
from app.services.system_graph.issues import default_issue_store
from app.services.system_graph.query import graph_page, search_page
from app.services.system_graph.repository import DatabaseGraphRepository, refresh_fingerprint
from app.services.system_graph.scanner import ScanRequest, scan_repository


def _rest_only(operation: str, plan_id: str = "") -> dict[str, object]:
    return {
        "ok": False,
        "error": "owner_authenticated_rest_required",
        "operation": operation,
        "plan_id": plan_id or None,
        "product_write_performed": False,
        "next": "Use the same-origin BFF and owner-authenticated /api/v1/system-graph/integration-plans API.",
    }


@mcp.tool()
async def system_graph_plan_feature(feature_id: str, base_snapshot_id: str, intent: str = "") -> dict[str, object]:
    """Build a no-write co-design scaffold for the owner-authenticated route."""

    if not feature_id or not base_snapshot_id:
        return {"ok": False, "error": "feature_id_and_base_snapshot_id_required", "product_write_performed": False}
    return {
        "ok": True,
        "feature_id": feature_id,
        "base_snapshot_id": base_snapshot_id,
        "intent": intent,
        "items": [item.model_dump(mode="json") for item in default_plan_items(feature_id)],
        "product_write_performed": False,
        "next": "Review the evidence table, then use the owner-authenticated REST route to persist a candidate revision.",
    }


@mcp.tool()
async def system_graph_update_plan(plan_id: str) -> dict[str, object]:
    """Explain the owner-authenticated route for CAS updating an S5 plan."""

    return _rest_only("patch", plan_id)


@mcp.tool()
async def system_graph_confirm_plan(plan_id: str) -> dict[str, object]:
    """Refuse confirmation without the REST owner identity and explicit body flag."""

    return _rest_only("confirm", plan_id)


def _repo_root() -> Path:
    configured = os.getenv("OMNI_REPO_ROOT", "").strip()
    root = Path(configured).resolve() if configured else Path(__file__).resolve().parents[5]
    if not (root / "AGENTS.md").is_file():
        raise RuntimeError("system_graph_repository_unavailable")
    return root


@tool_with_audit(mcp, require_approval=False)
async def system_graph_refresh(
    idempotency_key: str,
    feature_ids: list[str] | None = None,
    include_runtime: bool = False,
) -> dict[str, object]:
    """Create or reuse a persisted deterministic graph refresh."""

    if len(idempotency_key.strip()) < 8:
        return {"ok": False, "error": "idempotency_key_required"}
    feature_ids = sorted(set(feature_ids or []))
    request = {
        "feature_ids": feature_ids,
        "include_runtime": include_runtime,
        "idempotency_key": idempotency_key,
    }
    repository = DatabaseGraphRepository()
    fingerprint = refresh_fingerprint(request)
    record, created = await repository.begin_refresh(
        fingerprint=fingerprint,
        actor_id="mcp:system_graph_refresh",
        request=request,
    )
    if not created:
        return {"ok": True, "refresh": record.model_dump(mode="json"), "reused": True}
    try:
        await repository.mark_refresh_running(record.refresh_id)
        base = await repository.latest_snapshot()
        snapshot = scan_repository(
            ScanRequest(
                repo=_repo_root(),
                feature_ids=tuple(feature_ids),
                dynamic=include_runtime,
                base_snapshot=base,
            )
        )
        await repository.save_snapshot(snapshot)
        record = await repository.complete_refresh(record.refresh_id, snapshot)
    except Exception as exc:
        record = await repository.fail_refresh(
            record.refresh_id,
            code=f"collector_{type(exc).__name__.lower()}",
            retryable=True,
        )
    return {"ok": record.state in {"completed", "partial"}, "refresh": record.model_dump(mode="json"), "reused": False}


@tool_with_audit(mcp, require_approval=False)
async def system_graph_get(
    snapshot_id: str = "",
    root: str = "",
    direction: str = "both",
    depth: int = 2,
    cursor: str = "",
    limit: int = 200,
) -> dict[str, object]:
    """Read a paginated graph from the immutable repository."""

    repository = DatabaseGraphRepository()
    snapshot = await repository.get_snapshot(snapshot_id) if snapshot_id else await repository.latest_snapshot()
    if snapshot is None:
        return {"ok": False, "error": "snapshot_not_found"}
    try:
        page = graph_page(
            snapshot,
            root=root or None,
            direction=direction,
            depth=max(0, min(depth, 6)),
            cursor=cursor or None,
            limit=max(1, min(limit, 500)),
        )
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "graph": page.model_dump(mode="json")}


@tool_with_audit(mcp, require_approval=False)
async def system_graph_diff(from_snapshot: str, to_snapshot: str) -> dict[str, object]:
    """Compare two immutable graph snapshots without inferring removals from outages."""

    repository = DatabaseGraphRepository()
    try:
        before = await repository.get_snapshot(from_snapshot)
        after = await repository.get_snapshot(to_snapshot)
    except KeyError:
        return {"ok": False, "error": "snapshot_not_found"}
    return {"ok": True, "diff": diff_snapshots(before, after).model_dump(mode="json")}


@tool_with_audit(mcp, require_approval=False)
async def system_graph_search(
    query: str,
    snapshot_id: str = "",
    cursor: str = "",
    limit: int = 50,
) -> dict[str, object]:
    """Search factual nodes and return stable adjacent-node paths."""

    repository = DatabaseGraphRepository()
    snapshot = await repository.get_snapshot(snapshot_id) if snapshot_id else await repository.latest_snapshot()
    if snapshot is None:
        return {"ok": False, "error": "snapshot_not_found"}
    try:
        result = search_page(snapshot, query=query, cursor=cursor or None, limit=max(1, min(limit, 200)))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result.model_dump(mode="json")}


@tool_with_audit(mcp, require_approval=False)
async def system_graph_list_findings(
    status: str = "",
    code: str = "",
    query: str = "",
) -> dict[str, object]:
    """List durable deterministic repair findings; unavailable stores return empty."""

    from app.services.system_graph.issues import IssueStatus

    try:
        parsed_status = IssueStatus(status) if status else None
    except ValueError:
        return {"ok": False, "error": "invalid_status"}
    issues = default_issue_store().list(status=parsed_status, code=code or None, query=query)
    return {"ok": True, "findings": [item.model_dump(mode="json") for item in issues]}
