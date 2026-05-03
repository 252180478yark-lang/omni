"""5 个 W1 tool 的端到端测试（hits dev DB）。

前提：docker-compose up，dev DB 已 apply 全部 migration。
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _db():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture(scope="module")
async def seed_sku():
    """插一条已知 SKU；测试结束清理。"""
    pool = get_pool()
    sku_id = "_smoke_sku_001"
    await pool.execute(
        """
        INSERT INTO mvp_sku (id, name, category, douyin_product_id, status)
        VALUES ($1, '冒烟测试 SKU', '测试', '_smoke_dy_001', 'active')
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
        """,
        sku_id,
    )
    yield sku_id
    await pool.execute("DELETE FROM mvp_sku WHERE id=$1", sku_id)


@pytest.mark.asyncio
async def test_list_skus_returns_smoke_sku(seed_sku):
    from app.mcp.tools.sku import list_skus
    out = await list_skus(status="active")
    assert out["ok"] is True
    ids = [s["id"] for s in out["skus"]]
    assert seed_sku in ids


@pytest.mark.asyncio
async def test_get_sku_returns_detail(seed_sku):
    from app.mcp.tools.sku import get_sku
    out = await get_sku(sku_id=seed_sku)
    assert out["ok"] is True
    assert out["sku"]["id"] == seed_sku
    assert out["sku"]["name"] == "冒烟测试 SKU"
    # 关联字段（无数据时是空的，但 key 必须在）
    assert "recent_briefs" in out
    assert isinstance(out["recent_briefs"], list)


@pytest.mark.asyncio
async def test_get_sku_not_found_returns_tool_error():
    from app.mcp.tools.sku import get_sku
    out = await get_sku(sku_id="_definitely_not_exists_xyz")
    assert out["ok"] is False
    assert out["error"] == "sku_not_found"
    assert "list_skus" in out["hint"]


@pytest.mark.asyncio
async def test_list_kbs_basic():
    from app.mcp.tools.kb import list_kbs
    out = await list_kbs()
    assert out["ok"] is True
    assert "count" in out
    assert isinstance(out["kbs"], list)
    # 每条至少含 id / name / kb_role
    if out["kbs"]:
        kb0 = out["kbs"][0]
        for k in ("id", "name", "kb_role"):
            assert k in kb0


@pytest.mark.asyncio
async def test_list_kbs_filter_by_role():
    from app.mcp.tools.kb import list_kbs
    out = await list_kbs(role="general")
    assert out["ok"] is True
    for kb in out["kbs"]:
        assert kb["kb_role"] == "general"


@pytest.mark.asyncio
async def test_search_kb_no_kb_ids_returns_empty():
    """无任何 KB 时（或显式 kb_ids=[]）返回 ok=True + 空 hits，不抛错。"""
    from app.mcp.tools.kb import search_kb
    out = await search_kb(query="测试", kb_ids=[])
    assert out["ok"] is True
    assert out["hits"] == []
    assert out["count"] == 0


@pytest.mark.asyncio
async def test_search_kb_role_filter_resolves_kb_ids():
    """传 kb_roles 时应自动解析为 kb_ids；无匹配 KB 时返回空。"""
    from app.mcp.tools.kb import search_kb
    out = await search_kb(query="测试", kb_roles=["_no_such_role_"])
    # _no_such_role_ 不在 CHECK 约束允许列表，list_kbs 也查不到 → 空 hits
    assert out["ok"] is True
    assert out["hits"] == []
