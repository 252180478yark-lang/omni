"""MCP discovery surface for S5 integration plans.

FastMCP callers do not carry the owner-authenticated principal required by the
REST boundary. These tools are deliberately non-writing so MCP cannot become
an authentication bypass or a pre-confirmation product writer.
"""

from __future__ import annotations

from app.mcp.server import mcp
from app.services.system_graph.integration_plans import default_plan_items


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
