from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


@pytest.mark.asyncio
async def test_system_graph_mcp_tools_are_registered_and_in_doctor_contract() -> None:
    from app.mcp.doctor import _wanted_tools
    from app.mcp.server import mcp

    names = {tool.name for tool in await mcp.list_tools()}
    expected = {
        "system_graph_plan_feature",
        "system_graph_update_plan",
        "system_graph_confirm_plan",
    }
    assert expected <= names
    assert expected <= _wanted_tools()


@pytest.mark.asyncio
async def test_system_graph_mcp_tools_refuse_to_bypass_owner_rest_boundary() -> None:
    from app.mcp.tools.system_graph import system_graph_confirm_plan

    result = await system_graph_confirm_plan("plan-0123456789abcdef")
    assert result["error"] == "owner_authenticated_rest_required"
    assert result["product_write_performed"] is False


@pytest.mark.asyncio
async def test_system_graph_plan_feature_returns_full_no_write_scaffold() -> None:
    from app.mcp.tools.system_graph import system_graph_plan_feature

    result = await system_graph_plan_feature(
        "candidate-owner-graph", "sha256:" + "a" * 64, "add an owner co-design entry"
    )
    assert result["ok"] is True
    assert result["product_write_performed"] is False
    assert {item["layer"] for item in result["items"]} == {
        "page",
        "skill",
        "model",
        "bff",
        "api",
        "mcp_tool",
        "service",
        "table_field",
        "source",
        "test",
        "permission",
    }
    assert all(item["evidence_class"] == "hypothesis" for item in result["items"])
