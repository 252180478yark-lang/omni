"""MCP discovery surface for S5 integration plans.

FastMCP callers do not carry the owner-authenticated principal required by the
REST boundary. These tools are deliberately non-writing so MCP cannot become
an authentication bypass or a pre-confirmation product writer.
"""

from __future__ import annotations

from app.mcp.server import mcp


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
async def system_graph_plan_feature(feature_id: str, base_snapshot_id: str) -> dict[str, object]:
    """Explain the owner-authenticated route for creating an S5 candidate plan."""

    if not feature_id or not base_snapshot_id:
        return {"ok": False, "error": "feature_id_and_base_snapshot_id_required", "product_write_performed": False}
    return _rest_only("create")


@mcp.tool()
async def system_graph_update_plan(plan_id: str) -> dict[str, object]:
    """Explain the owner-authenticated route for CAS updating an S5 plan."""

    return _rest_only("patch", plan_id)


@mcp.tool()
async def system_graph_confirm_plan(plan_id: str) -> dict[str, object]:
    """Refuse confirmation without the REST owner identity and explicit body flag."""

    return _rest_only("confirm", plan_id)
