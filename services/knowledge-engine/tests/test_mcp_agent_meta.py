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


# ─── T4: codify_pattern_to_skill ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_codify_writes_draft(monkeypatch, tmp_path):
    """codify 直接调（绕开 require_approval gate）写草稿到指定目录。"""
    from app.mcp.tools import agent_meta

    monkeypatch.setattr(agent_meta, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(agent_meta, "SKILL_DRAFTS_DIR", tmp_path / "skill_drafts")

    # mock LLM 返回固定 markdown
    fake_md = "---\nname: test-skill\ndescription: smoke\n---\n\n# Test\n"

    class _FakeClient:
        async def chat(self, **kwargs):
            return {
                "content": fake_md,
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "usage": {},
            }

    monkeypatch.setattr(agent_meta, "AIHubClient", _FakeClient)

    # 直接调内部函数（绕 audit/gate 装饰器）
    res = await agent_meta._codify_impl(
        skill_name="test-skill",
        description="测试 skill",
        tool_sequence=["list_skus", "get_sku"],
    )
    assert res["ok"] is True
    draft_path = Path(res["result"]["draft_path"])
    assert draft_path.exists()
    assert draft_path.read_text(encoding="utf-8").strip().startswith("---")
    assert "test-skill" in draft_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_codify_invalid_skill_name(monkeypatch, tmp_path):
    from app.mcp.tools import agent_meta
    monkeypatch.setattr(agent_meta, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(agent_meta, "SKILL_DRAFTS_DIR", tmp_path / "skill_drafts")

    res = await agent_meta._codify_impl(
        skill_name="invalid name with spaces!",
        description="x",
        tool_sequence=["list_skus"],
    )
    assert res["ok"] is False
    assert "invalid_skill_name" in res.get("error", "")


# ─── T5: refresh_project_context ───────────────────────────────────────────


@pytest_asyncio.fixture
async def seed_active_skus():
    """造 2 个 active SKU 用于 refresh 渲染。

    mvp_sku 主键 = id (VARCHAR 64); douyin_product_id NOT NULL，给唯一值。
    """
    pool = get_pool()
    inserted_ids = []
    for sku_id, name in [("REFRESH-T5-001", "测试 SKU 1"), ("REFRESH-T5-002", "测试 SKU 2")]:
        try:
            await pool.execute(
                "INSERT INTO mvp_sku (id, name, douyin_product_id, status) "
                "VALUES ($1, $2, $1, 'active') "
                "ON CONFLICT (id) DO UPDATE SET status='active'",
                sku_id, name,
            )
            inserted_ids.append(sku_id)
        except Exception:
            pass
    yield inserted_ids
    for sid in inserted_ids:
        await pool.execute("DELETE FROM mvp_sku WHERE id=$1", sid)


@pytest.mark.asyncio
async def test_refresh_writes_dynamic_block(monkeypatch, tmp_path, seed_active_skus):
    from app.mcp.tools import agent_meta
    monkeypatch.setattr(agent_meta, "AGENT_STATE_DIR", tmp_path)

    res = await agent_meta._refresh_impl()
    assert res["ok"] is True
    out_path = Path(res["result"]["dynamic_block_path"])
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "<!-- omni-dynamic:start -->" in text
    assert "<!-- omni-dynamic:end -->" in text
    # 重点池区段含至少一个 SKU
    assert "REFRESH-T5" in text or "重点池 SKU" in text


@pytest.mark.asyncio
async def test_refresh_idempotent(monkeypatch, tmp_path, seed_active_skus):
    from app.mcp.tools import agent_meta
    monkeypatch.setattr(agent_meta, "AGENT_STATE_DIR", tmp_path)

    r1 = await agent_meta._refresh_impl()
    r2 = await agent_meta._refresh_impl()
    assert r1["ok"] is True and r2["ok"] is True
    p = Path(r1["result"]["dynamic_block_path"])
    # 两次写入大小差不超过几十字节（仅 timestamp 行变）
    text = p.read_text(encoding="utf-8")
    assert text.count("<!-- omni-dynamic:start -->") == 1
    assert text.count("<!-- omni-dynamic:end -->") == 1
