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
