"""T4 + T5：accounting tools 集成测（hits dev DB）。"""
import asyncio
from decimal import Decimal

import pytest
import pytest_asyncio
from app.database import get_pool, init_pool, close_pool
from app.mcp.tools.accounting import query_costs


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed_data():
    """插测试 cost_items；module teardown 清。"""
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO accounting.cost_items
            (sku_id, category, item_name, unit_cost, currency, unit, quantity_per_unit, vendor, is_active)
        VALUES
            ('_smoke_sku_001', 'product', '_smoke 瓶身', 0.80, 'CNY', '个', 1, '_smoke 厂', TRUE),
            ('_smoke_sku_001', 'product', '_smoke 标签', 0.15, 'CNY', '张', 1, '_smoke 印刷', TRUE),
            (NULL, 'logistics', '_smoke 顺丰华东', 4.50, 'CNY', '件', 1, '_smoke 物流', TRUE)
        """
    )
    yield
    await pool.execute("DELETE FROM accounting.cost_items WHERE item_name LIKE '_smoke %'")


@pytest.mark.asyncio
async def test_smoke_query_costs_returns_sku_and_shared():
    r = await query_costs(sku_id="_smoke_sku_001")
    assert r["ok"] is True
    items = r["result"]["cost_items"]
    # 至少 3 行：2 product (sku) + 1 logistics (shared)
    smoke = [i for i in items if i["item_name"].startswith("_smoke ")]
    assert len(smoke) >= 3
    # 验证字段都是 jsonable（unit_cost 应为 str）
    for i in smoke:
        assert isinstance(i["unit_cost"], str)


@pytest.mark.asyncio
async def test_smoke_query_costs_unknown_sku_returns_only_shared():
    r = await query_costs(sku_id="_smoke_sku_does_not_exist_999")
    assert r["ok"] is True
    items = r["result"]["cost_items"]
    smoke = [i for i in items if i["item_name"].startswith("_smoke ")]
    # 共享（sku_id IS NULL）的物流应在结果里
    cats = [i["category"] for i in smoke]
    assert "logistics" in cats


@pytest.mark.asyncio
async def test_smoke_query_costs_inactive_excluded():
    pool = get_pool()
    await pool.execute(
        "INSERT INTO accounting.cost_items (sku_id, category, item_name, unit_cost, is_active) "
        "VALUES ('_smoke_sku_001', 'product', '_smoke 已停', 9.99, FALSE)"
    )
    try:
        r = await query_costs(sku_id="_smoke_sku_001")
        names = [i["item_name"] for i in r["result"]["cost_items"]]
        assert "_smoke 已停" not in names
    finally:
        await pool.execute("DELETE FROM accounting.cost_items WHERE item_name='_smoke 已停'")
