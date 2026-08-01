import asyncio
import re
from pathlib import Path

import pytest

from app.mcp.audit import TOOL_REGISTRY
from app.services import compatibility
from app.services.tool_execution import (
    ToolExecutionFailure,
    execute_registered_tool,
    operation_tool,
)


@pytest.mark.asyncio
async def test_canonical_and_legacy_families_use_one_executor(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    async def sample_tool(name: str, count: int = 1):
        calls.append((name, count))
        return {"ok": True, "name": name, "count": count}

    async def no_telemetry(**_kwargs):
        return None

    monkeypatch.setitem(TOOL_REGISTRY, "sample_tool", {"fn": sample_tool, "require_approval": False, "timeout_seconds": None})
    monkeypatch.setattr(compatibility, "append_route_telemetry", no_telemetry)
    canonical = await execute_registered_tool(tool_name="sample_tool", args={"name": "sku", "count": 2}, route_family="canonical_operation")
    legacy = await execute_registered_tool(tool_name="sample_tool", args={"name": "sku", "count": 2}, route_family="legacy_exec")
    assert canonical == legacy == {"ok": True, "name": "sku", "count": 2}
    assert calls == [("sku", 2), ("sku", 2)]


@pytest.mark.asyncio
async def test_executor_rejects_bad_args_and_times_out(monkeypatch) -> None:
    async def slow_tool(required: str):
        await asyncio.sleep(0.05)
        return {"ok": True, "required": required}

    async def no_telemetry(**_kwargs):
        return None

    monkeypatch.setitem(TOOL_REGISTRY, "slow_tool", {"fn": slow_tool, "require_approval": False, "timeout_seconds": None})
    monkeypatch.setattr(compatibility, "append_route_telemetry", no_telemetry)
    with pytest.raises(ToolExecutionFailure) as missing:
        await execute_registered_tool(tool_name="slow_tool", args={}, route_family="legacy_exec")
    assert missing.value.status_code == 422
    with pytest.raises(ToolExecutionFailure) as timeout:
        await execute_registered_tool(tool_name="slow_tool", args={"required": "x"}, route_family="canonical_operation", timeout_seconds=0.001)
    assert timeout.value.code == "tool_timeout"


def test_operation_registry_is_closed() -> None:
    assert operation_tool("sku.selling-points.generate") == "generate_selling_points_matrix"
    with pytest.raises(ToolExecutionFailure) as unknown:
        operation_tool("app.mcp.tools.media.any_import")
    assert unknown.value.code == "unknown_operation"


def test_frontend_operation_ids_are_a_subset_of_backend_registry() -> None:
    from app.services.tool_execution import OPERATION_REGISTRY
    repo = Path(__file__).resolve().parents[3]
    source = (repo / "frontend/src/lib/sku-pipeline/operations.ts").read_text(encoding="utf-8")
    frontend_ids = set(re.findall(r"'((?:sku|experiment|video)\.[a-z0-9.-]+)'", source.split("} as const", 1)[0]))
    assert frontend_ids
    assert frontend_ids <= set(OPERATION_REGISTRY)

