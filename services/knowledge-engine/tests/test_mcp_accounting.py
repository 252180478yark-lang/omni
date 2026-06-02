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


from app.mcp.tools.accounting import compute_margin


# 复用 _seed_data fixture 的 _smoke_sku_001（成本：瓶身 0.80 + 标签 0.15 + 物流 4.50 = 5.45）

@pytest.mark.asyncio
async def test_smoke_compute_margin_basic_math():
    """sale_price=29.9 / cost=自家 0.95 + shared 物流总和 → 数学链路必须自洽。

    LLM 解读字段允许波动；但数字字段必须是确定性。

    W4-B 切片 7 后：表内可能有非 _smoke 的真业务 sku_id IS NULL shared 物流行
    被一并算进去（历史 record_cost e2e 留的）。本测改用动态 expected：从表上
    实算 _smoke_sku_001 自家成本 + 所有 sku_id IS NULL shared 物流，断言
    compute_margin 输出与之一致。
    """
    pool = get_pool()
    expected_cost = await pool.fetchval(
        """
        SELECT COALESCE(SUM(unit_cost / quantity_per_unit), 0)
        FROM accounting.cost_items
        WHERE (sku_id = '_smoke_sku_001' OR sku_id IS NULL)
          AND is_active = TRUE
          AND visibility IN ('public', 'shared')
          AND valid_from <= CURRENT_DATE
          AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
        """
    )
    expected_cost = Decimal(str(expected_cost))

    r = await compute_margin(
        sku_id="_smoke_sku_001",
        channel="douyin",
        sale_price="29.90",
        qty=1,
        channel_fee_rate="0.05",   # 抖音典型扣点
        skip_llm=True,             # 仅算账，跳过 LLM 写解读（测试隔离）
    )
    assert r["ok"] is True
    breakdown = r["result"]["breakdown"]
    assert Decimal(breakdown["cost_total"]) == expected_cost.quantize(Decimal("0.01"))
    assert breakdown["gmv"] == "29.90"
    assert breakdown["channel_fee"] == "1.4950"
    # net_profit = gmv - cost_total - channel_fee
    expected_net = Decimal("29.90") - expected_cost.quantize(Decimal("0.01")) - Decimal("1.4950")
    assert Decimal(breakdown["net_profit"]) == expected_net
    # margin_pct 介于 (0,1)
    margin_pct = Decimal(breakdown["margin_pct"])
    assert 0 < margin_pct < 1


@pytest.mark.asyncio
async def test_smoke_compute_margin_no_costs_returns_warning():
    r = await compute_margin(
        sku_id="_smoke_sku_does_not_exist_999",
        channel="douyin",
        sale_price="9.99",
        qty=1,
        skip_llm=True,
    )
    assert r["ok"] is True
    # cost_total 至少含共享成本物流 4.50；如全无，breakdown 仍要返
    assert "cost_total" in r["result"]["breakdown"]


@pytest.mark.asyncio
async def test_smoke_compute_margin_trace_fields_present():
    r = await compute_margin(
        sku_id="_smoke_sku_001", channel="douyin",
        sale_price="29.90", qty=1, skip_llm=True,
    )
    # 即使 skip_llm，trace 也要有（写"skipped"）
    assert "trace" in r
    assert r["trace"]["model"]
    # next_step_hint 链路终点：margin 后建议 generate_brief
    assert r["next_step_hint"]["suggested_tool"] == "generate_brief"
