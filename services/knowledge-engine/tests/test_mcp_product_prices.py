"""W4-B 切片 8：list_product_prices tool 测试。

依赖 import_product_prices.py 跑过让表里有数据。本测试不依赖具体行数，
只验过滤 / 排序 / 字段类型。
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.database import close_pool, get_pool, init_pool


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def seed_test_products():
    """造 3 行隔离测试数据；不删用户真实数据。"""
    pool = get_pool()
    inserted = []
    for vendor, name, grade, spec, pack, price, bc in [
        ("_test_vendor_A", "_test_产品α", "特级", "500ml*12", 12, 9.99, "TEST_BC_001"),
        ("_test_vendor_A", "_test_产品β", "酸度5°", "200ml*24", 24, 4.50, "TEST_BC_002"),
        ("_test_vendor_B", "_test_产品γ", None, "1L*6", 6, 12.00, None),
    ]:
        row = await pool.fetchrow(
            "INSERT INTO accounting.product_price_list "
            "(product_name, grade, spec, pack_size, unit_price, "
            " barcode, vendor, visibility) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,'public') RETURNING id",
            name, grade, spec, pack, Decimal(str(price)), bc, vendor,
        )
        inserted.append(row["id"])
    yield
    for cid in inserted:
        await pool.execute(
            "DELETE FROM accounting.product_price_list WHERE id=$1", cid,
        )


@pytest.mark.asyncio
async def test_list_product_prices_empty_query_returns_all_test(seed_test_products):
    from app.mcp.tools.accounting import list_product_prices

    r = await list_product_prices(query="_test_", limit=20)
    assert r["ok"] is True
    items = r["result"]["items"]
    names = {i["product_name"] for i in items}
    assert "_test_产品α" in names
    assert "_test_产品β" in names
    assert "_test_产品γ" in names


@pytest.mark.asyncio
async def test_list_product_prices_vendor_filter(seed_test_products):
    from app.mcp.tools.accounting import list_product_prices

    r = await list_product_prices(query="_test_", vendor="_test_vendor_A", limit=10)
    assert r["ok"] is True
    vendors = {i["vendor"] for i in r["result"]["items"]}
    assert vendors == {"_test_vendor_A"}


@pytest.mark.asyncio
async def test_list_product_prices_barcode_exact(seed_test_products):
    from app.mcp.tools.accounting import list_product_prices

    r = await list_product_prices(barcode="TEST_BC_001")
    assert r["ok"] is True
    items = r["result"]["items"]
    assert len(items) == 1
    assert items[0]["product_name"] == "_test_产品α"


@pytest.mark.asyncio
async def test_list_product_prices_query_matches_grade(seed_test_products):
    """grade 字段也参与模糊匹配（'酸度5°' should match）。"""
    from app.mcp.tools.accounting import list_product_prices

    r = await list_product_prices(query="酸度5", limit=10)
    items = r["result"]["items"]
    test_items = [i for i in items if i["product_name"].startswith("_test_")]
    assert any("β" in i["product_name"] for i in test_items)


@pytest.mark.asyncio
async def test_list_product_prices_returns_jsonable_types(seed_test_products):
    """unit_price 应转 str（decimal_to_jsonable）；valid_from 应转 ISO str。"""
    from app.mcp.tools.accounting import list_product_prices

    r = await list_product_prices(query="_test_产品α", limit=1)
    items = r["result"]["items"]
    assert len(items) == 1
    it = items[0]
    assert isinstance(it["unit_price"], str)
    assert it["valid_from"] and isinstance(it["valid_from"], str)


@pytest.mark.asyncio
async def test_list_product_prices_limit_clamps(seed_test_products):
    from app.mcp.tools.accounting import list_product_prices

    r = await list_product_prices(query="_test_", limit=2)
    assert len(r["result"]["items"]) <= 2


@pytest.mark.asyncio
async def test_list_product_prices_inactive_excluded(seed_test_products):
    """is_active=FALSE 的行不应返。"""
    from app.mcp.tools.accounting import list_product_prices

    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO accounting.product_price_list "
        "(product_name, vendor, unit_price, visibility, is_active) "
        "VALUES ('_test_停用产品', '_test_vendor_A', 1.0, 'public', FALSE) "
        "RETURNING id",
    )
    try:
        r = await list_product_prices(query="_test_停用产品")
        assert r["ok"] is True
        assert len(r["result"]["items"]) == 0
    finally:
        await pool.execute(
            "DELETE FROM accounting.product_price_list WHERE id=$1", row["id"],
        )
