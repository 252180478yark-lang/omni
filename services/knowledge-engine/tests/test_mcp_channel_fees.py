"""W4-B 切片 9：渠道扣点表 + compute_margin fallback 测试。"""
from __future__ import annotations

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
async def seed_test_fees():
    """造 2 条测试用扣点行。"""
    pool = get_pool()
    inserted = []
    for ch, ft, rate, desc in [
        ("_test_douyin", "percentage", "0.030000", "测试渠道扣点 3%"),
        ("_test_tmall", "percentage", "0.060000", "测试天猫扣点 6%"),
    ]:
        row = await pool.fetchrow(
            "INSERT INTO accounting.channel_fees "
            "(channel, fee_type, fee_rate, description) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            ch, ft, Decimal(rate), desc,
        )
        inserted.append(row["id"])
    yield
    for cid in inserted:
        await pool.execute(
            "DELETE FROM accounting.channel_fees WHERE id=$1", cid,
        )


@pytest.mark.asyncio
async def test_list_channel_fees_returns_active(seed_test_fees):
    from app.mcp.tools.accounting import list_channel_fees

    r = await list_channel_fees()
    assert r["ok"] is True
    items = r["result"]["items"]
    chans = {i["channel"] for i in items}
    assert "_test_douyin" in chans
    assert "_test_tmall" in chans


@pytest.mark.asyncio
async def test_list_channel_fees_filter_by_channel(seed_test_fees):
    from app.mcp.tools.accounting import list_channel_fees

    r = await list_channel_fees(channel="_test_douyin")
    assert r["ok"] is True
    items = r["result"]["items"]
    assert all(i["channel"] == "_test_douyin" for i in items)
    # fee_rate 应为 str (decimal_to_jsonable)
    assert isinstance(items[0]["fee_rate"], str)


@pytest.mark.asyncio
async def test_list_channel_fees_inactive_excluded():
    """is_active=FALSE 不应出现在结果。"""
    from app.mcp.tools.accounting import list_channel_fees

    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO accounting.channel_fees "
        "(channel, fee_type, fee_rate, description, is_active) "
        "VALUES ('_test_inactive', 'percentage', 0.99, '已停用', FALSE) "
        "RETURNING id",
    )
    try:
        r = await list_channel_fees(channel="_test_inactive")
        assert len(r["result"]["items"]) == 0
    finally:
        await pool.execute(
            "DELETE FROM accounting.channel_fees WHERE id=$1", row["id"],
        )


# ── compute_margin fallback ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_channel_fee_explicit_wins(seed_test_fees):
    from app.mcp.tools.accounting import _resolve_channel_fee_rate

    rate, src = await _resolve_channel_fee_rate("_test_douyin", "0.10")
    assert rate == Decimal("0.10")
    assert src == "caller"


@pytest.mark.asyncio
async def test_resolve_channel_fee_falls_back_to_db(seed_test_fees):
    from app.mcp.tools.accounting import _resolve_channel_fee_rate

    rate, src = await _resolve_channel_fee_rate("_test_douyin", None)
    assert rate == Decimal("0.030000")
    assert src == "channel_fees"


@pytest.mark.asyncio
async def test_resolve_channel_fee_default_when_no_match():
    from app.mcp.tools.accounting import _resolve_channel_fee_rate

    rate, src = await _resolve_channel_fee_rate("_unknown_channel_xyz", None)
    assert rate == Decimal("0.05")
    assert src == "default"


@pytest.mark.asyncio
async def test_resolve_channel_fee_empty_string_treated_as_none(seed_test_fees):
    """caller 传空字符串 → 当 None 走 fallback。"""
    from app.mcp.tools.accounting import _resolve_channel_fee_rate

    rate, src = await _resolve_channel_fee_rate("_test_tmall", "")
    assert rate == Decimal("0.060000")
    assert src == "channel_fees"


@pytest.mark.asyncio
async def test_compute_margin_uses_channel_fees_for_douyin(seed_test_fees):
    """compute_margin 调 douyin 不传 channel_fee_rate，应用 channel_fees 的 3%。"""
    from app.mcp.tools.accounting import compute_margin

    r = await compute_margin(
        sku_id="_smoke_sku_001", channel="_test_douyin",
        sale_price="100", qty=1, skip_llm=True,
        # 注意不传 channel_fee_rate
    )
    assert r["ok"] is True
    breakdown = r["result"]["breakdown"]
    # gmv = 100，fee_rate = 0.03，channel_fee = 3.00
    assert breakdown["channel_fee_rate"] == "0.030000"
    assert breakdown["fee_rate_source"] == "channel_fees"
    assert Decimal(breakdown["channel_fee"]) == Decimal("3.0000")


@pytest.mark.asyncio
async def test_compute_margin_explicit_overrides_channel_fees(seed_test_fees):
    """caller 显式传 channel_fee_rate 应胜过 channel_fees。"""
    from app.mcp.tools.accounting import compute_margin

    r = await compute_margin(
        sku_id="_smoke_sku_001", channel="_test_douyin",
        sale_price="100", qty=1, skip_llm=True,
        channel_fee_rate="0.07",
    )
    assert r["ok"] is True
    breakdown = r["result"]["breakdown"]
    assert breakdown["channel_fee_rate"] == "0.07"
    assert breakdown["fee_rate_source"] == "caller"
    assert Decimal(breakdown["channel_fee"]) == Decimal("7.0000")


@pytest.mark.asyncio
async def test_compute_margin_default_when_unknown_channel():
    """没在 channel_fees 找到时兜底 0.05。"""
    from app.mcp.tools.accounting import compute_margin

    r = await compute_margin(
        sku_id="_smoke_sku_001", channel="_unknown_channel_xyz",
        sale_price="100", qty=1, skip_llm=True,
    )
    assert r["ok"] is True
    breakdown = r["result"]["breakdown"]
    assert breakdown["fee_rate_source"] == "default"
    assert Decimal(breakdown["channel_fee_rate"]) == Decimal("0.05")


@pytest.mark.asyncio
async def test_real_douyin_2_percent_in_db():
    """生产数据：抖音 2% 应已录入（migration 020 INSERT）。"""
    from app.mcp.tools.accounting import list_channel_fees

    r = await list_channel_fees(channel="douyin")
    assert r["ok"] is True
    items = r["result"]["items"]
    assert len(items) >= 1
    assert any(
        i["fee_type"] == "percentage" and Decimal(i["fee_rate"]) == Decimal("0.020000")
        for i in items
    )
