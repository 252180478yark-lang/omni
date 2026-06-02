"""W3a T6：human_gate 真实现集成测（hits dev DB）。"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from app.database import get_pool, init_pool, close_pool
from app.mcp import human_gate


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


async def _create_pending_tool_call(pool) -> str:
    tc_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO mcp.tool_calls (id, tool_name, args, status, require_approval) "
        "VALUES ($1, '_smoke_gate_test', '{}'::jsonb, 'pending', TRUE)",
        uuid.UUID(tc_id),
    )
    return tc_id


async def _set_decision(pool, tool_call_id: str, decision: str, note: str = "") -> None:
    """模拟外部进程（CLI / /inbox）批/驳的写入。"""
    await pool.execute(
        "UPDATE mcp.human_gates SET decision=$1, decision_note=$2, decided_at=NOW() "
        "WHERE tool_call_id=$3",
        decision, note, uuid.UUID(tool_call_id),
    )


@pytest.mark.asyncio
async def test_smoke_gate_approved():
    """approved 路径：写 gate → 外部批 → request_approval 返 approved。"""
    pool = get_pool()
    tc_id = await _create_pending_tool_call(pool)

    async def _approve_after_short_delay():
        await asyncio.sleep(0.3)
        await _set_decision(pool, tc_id, "approved", "看起来 OK")

    approve_task = asyncio.create_task(_approve_after_short_delay())

    decision = await human_gate.request_approval(
        tool_call_id=tc_id,
        summary="_smoke gate test approved",
        timeout_seconds=5,
        poll_interval_seconds=0.1,
    )
    await approve_task

    assert decision["decision"] == "approved"
    assert decision["decision_note"] == "看起来 OK"

    await pool.execute("DELETE FROM mcp.human_gates WHERE tool_call_id=$1", uuid.UUID(tc_id))
    await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", uuid.UUID(tc_id))


@pytest.mark.asyncio
async def test_smoke_gate_rejected():
    pool = get_pool()
    tc_id = await _create_pending_tool_call(pool)

    async def _reject_after_short_delay():
        await asyncio.sleep(0.3)
        await _set_decision(pool, tc_id, "rejected", "不行")

    reject_task = asyncio.create_task(_reject_after_short_delay())

    decision = await human_gate.request_approval(
        tool_call_id=tc_id,
        summary="_smoke gate test rejected",
        timeout_seconds=5,
        poll_interval_seconds=0.1,
    )
    await reject_task

    assert decision["decision"] == "rejected"
    assert decision["decision_note"] == "不行"

    await pool.execute("DELETE FROM mcp.human_gates WHERE tool_call_id=$1", uuid.UUID(tc_id))
    await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", uuid.UUID(tc_id))


@pytest.mark.asyncio
async def test_smoke_gate_timeout():
    """timeout 内无人批 → 返 expired（蓝图 §1.6/§7 R-1：超时绝不等于 rejected，系统永不替老板说 No）。"""
    pool = get_pool()
    tc_id = await _create_pending_tool_call(pool)

    decision = await human_gate.request_approval(
        tool_call_id=tc_id,
        summary="_smoke gate test timeout",
        timeout_seconds=1,
        poll_interval_seconds=0.1,
    )
    assert decision["decision"] == "expired"
    assert "timeout" in (decision.get("decision_note") or "").lower()

    # 验证 DB 也写了 timeout 标记
    row = await pool.fetchrow(
        "SELECT decision, decision_note FROM mcp.human_gates WHERE tool_call_id=$1",
        uuid.UUID(tc_id),
    )
    assert row is not None
    assert row["decision"] == "expired"

    await pool.execute("DELETE FROM mcp.human_gates WHERE tool_call_id=$1", uuid.UUID(tc_id))
    await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", uuid.UUID(tc_id))
