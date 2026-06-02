"""W4-A T2: rate_tool_call tool 测试。"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.mcp import pattern_lib
from app.mcp.tools.feedback import rate_tool_call


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def seed_call():
    """插一条 mcp.tool_calls 给 rate 用，返 id str。"""
    pool = get_pool()
    call_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO mcp.tool_calls (id, tool_name, args, status, require_approval, completed_at) "
        "VALUES ($1, 'fake_tool', '{}'::jsonb, 'completed', FALSE, NOW())",
        call_id,
    )
    yield str(call_id)
    await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", call_id)


@pytest.fixture
def tmp_state_dir(monkeypatch, tmp_path):
    success = tmp_path / "successful_patterns.md"
    failed = tmp_path / "failed_patterns.md"
    success.write_text("# Successful Patterns\n\n", encoding="utf-8")
    failed.write_text("# Failed Patterns\n\n", encoding="utf-8")
    monkeypatch.setattr(pattern_lib, "AGENT_STATE_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_rate_good_writes_db_and_patterns(seed_call, tmp_state_dir):
    res = await rate_tool_call(call_id=seed_call, rating="good", note="完美")
    assert res["ok"] is True
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT user_rating, rating_note FROM mcp.tool_calls WHERE id=$1",
        uuid.UUID(seed_call),
    )
    assert row["user_rating"] == "good"
    assert row["rating_note"] == "完美"
    text = (tmp_state_dir / "successful_patterns.md").read_text(encoding="utf-8")
    assert seed_call in text


@pytest.mark.asyncio
async def test_rate_bad_writes_failed_patterns(seed_call, tmp_state_dir):
    res = await rate_tool_call(call_id=seed_call, rating="bad", note="返空")
    assert res["ok"] is True
    text = (tmp_state_dir / "failed_patterns.md").read_text(encoding="utf-8")
    assert seed_call in text


@pytest.mark.asyncio
async def test_rate_invalid_returns_error(seed_call, tmp_state_dir):
    res = await rate_tool_call(call_id=seed_call, rating="awesome")
    assert res["ok"] is False
    assert "invalid_rating" in res.get("error", "")


@pytest.mark.asyncio
async def test_rate_unknown_call_id_returns_error(tmp_state_dir):
    fake_id = str(uuid.uuid4())
    res = await rate_tool_call(call_id=fake_id, rating="good")
    assert res["ok"] is False
    assert "call_not_found" in res.get("error", "")
