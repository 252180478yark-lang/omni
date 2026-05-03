"""tool_with_audit 装饰器单测（hits dev DB）。

每条用例自插自删，避免互相干扰。
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from fastmcp import FastMCP

from app.database import init_pool, close_pool, get_pool
from app.mcp.audit import tool_with_audit


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _db():
    await init_pool()
    yield
    # 清理本测试新增的所有 _smoke_ 行
    pool = get_pool()
    await pool.execute("DELETE FROM mcp.tool_calls WHERE tool_name LIKE '_smoke_%'")
    await close_pool()


@pytest.fixture
def mcp():
    return FastMCP("test-omni")


@pytest.mark.asyncio
async def test_audit_writes_completed_row_on_success(mcp):
    @tool_with_audit(mcp, require_approval=False)
    async def _smoke_ok(x: int) -> dict:
        """smoke tool"""
        return {"ok": True, "doubled": x * 2}

    result = await _smoke_ok(7)
    assert result == {"ok": True, "doubled": 14}

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT tool_name, status, args, result, error, duration_ms"
        " FROM mcp.tool_calls WHERE tool_name=$1 ORDER BY created_at DESC LIMIT 1",
        "_smoke_ok",
    )
    assert row is not None
    assert row["status"] == "completed"
    assert row["error"] is None
    assert row["duration_ms"] is not None and row["duration_ms"] >= 0
    # asyncpg 自动把 jsonb 转成 dict / list（已通过 register_vector / json codec）
    args = row["args"] if isinstance(row["args"], dict) else json.loads(row["args"])
    assert args["x"] == 7
    res = row["result"] if isinstance(row["result"], dict) else json.loads(row["result"])
    assert res["doubled"] == 14


@pytest.mark.asyncio
async def test_audit_writes_error_row_on_exception(mcp):
    @tool_with_audit(mcp, require_approval=False)
    async def _smoke_boom() -> dict:
        """raises"""
        raise RuntimeError("synthetic failure for test")

    # 装饰器把异常吞掉，转成 ToolError dict
    result = await _smoke_boom()
    assert result["ok"] is False
    assert "synthetic failure" in result["error"]

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT status, error FROM mcp.tool_calls"
        " WHERE tool_name='_smoke_boom' ORDER BY created_at DESC LIMIT 1",
    )
    assert row["status"] == "error"
    assert "synthetic failure" in row["error"]


@pytest.mark.asyncio
async def test_audit_returns_tool_error_when_approval_required_in_w1(mcp):
    """W1 暂未实现 human_gate；require_approval=True 应 graceful 返回 ToolError，
    而不是 hard crash。"""

    @tool_with_audit(
        mcp,
        require_approval=True,
        summary_fn=lambda args: f"smoke gated {args}",
    )
    async def _smoke_gated() -> dict:
        return {"ok": True}

    result = await _smoke_gated()
    assert result["ok"] is False
    assert result["error"] in {"human_gate_unavailable", "not_implemented"}
