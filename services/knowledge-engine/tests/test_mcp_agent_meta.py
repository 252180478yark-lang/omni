"""W4-A T3-T5: agent_meta tool 测试。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def seed_calls():
    """造一批 tool_calls：3 次 generate_brief→search_kb→get_sku 序列 + 5 次散调。"""
    pool = get_pool()
    inserted = []
    now = datetime.now(timezone.utc)
    # 3 次序列（间隔 1 天）
    # 注意：用 enumerate 给同序列内 3 个 tool 递增 ts（间隔 1 秒），保证
    # ORDER BY created_at ASC 能严格还原 [generate_brief, search_kb, get_sku]
    # 顺序，让滑窗 3 命中。plan 原 minutes=ord(tool_name[0]) 推导有误。
    for i in range(3):
        for j, tool_name in enumerate(["generate_brief", "search_kb", "get_sku"]):
            cid = uuid.uuid4()
            ts = now - timedelta(days=i + 1) + timedelta(seconds=j)
            await pool.execute(
                "INSERT INTO mcp.tool_calls "
                "(id, tool_name, args, status, require_approval, created_at, completed_at, user_rating) "
                "VALUES ($1, $2, '{}'::jsonb, 'completed', FALSE, $3, $3, $4)",
                cid, tool_name, ts, "good" if (i == 0 and tool_name == "generate_brief") else None,
            )
            inserted.append(cid)
    # 散调
    for tool_name in ["list_skus", "list_kbs", "compute_margin", "list_briefs", "search_kb"]:
        cid = uuid.uuid4()
        await pool.execute(
            "INSERT INTO mcp.tool_calls "
            "(id, tool_name, args, status, require_approval, created_at, completed_at) "
            "VALUES ($1, $2, '{}'::jsonb, 'completed', FALSE, NOW(), NOW())",
            cid, tool_name,
        )
        inserted.append(cid)
    yield
    for cid in inserted:
        await pool.execute("DELETE FROM mcp.tool_calls WHERE id=$1", cid)


@pytest.mark.asyncio
async def test_agent_self_review_basic_stats(seed_calls):
    from app.mcp.tools.agent_meta import agent_self_review
    res = await agent_self_review(period_days=7)
    assert res["ok"] is True
    r = res["result"]
    assert r["total_calls"] >= 14  # 9 序列 + 5 散调
    assert "by_tool" in r
    assert r["by_tool"].get("generate_brief", 0) >= 3
    assert r["by_status"].get("completed", 0) >= 14


@pytest.mark.asyncio
async def test_agent_self_review_finds_pattern(seed_calls):
    from app.mcp.tools.agent_meta import agent_self_review
    res = await agent_self_review(period_days=7)
    patterns = res["result"]["candidate_patterns"]
    # 期望找到 (generate_brief, search_kb, get_sku) 滑窗 3 序列
    seqs = [tuple(p["sequence"]) for p in patterns]
    assert ("generate_brief", "search_kb", "get_sku") in seqs


@pytest.mark.asyncio
async def test_agent_self_review_rating_distribution(seed_calls):
    from app.mcp.tools.agent_meta import agent_self_review
    res = await agent_self_review(period_days=7)
    r = res["result"]
    assert "by_rating" in r
    assert r["by_rating"].get("good", 0) >= 1
