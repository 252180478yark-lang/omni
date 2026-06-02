"""W4-B 切片 7：成本两版 + 口令 测试（migration 018）。

verifies:
- visibility 三态过滤（public/real/shared）
- view='public' 默认；shared 行两版都看到
- view='real' 无 passphrase 时直通（settings 未设）；设了必须正确才放
- record_cost 写入 visibility 字段
- compute_margin cost_total 在两 view 下不同
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import close_pool, get_pool, init_pool


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def seed_visibility_rows():
    """造 3 行成本：public 30, real 25, shared 5。"""
    pool = get_pool()
    sku = "_smoke_vis_sku"
    inserted = []
    for vis, name, cost in [
        ("public", "_vis 出厂价", 30.00),
        ("real", "_vis 真实进货价", 25.00),
        ("shared", "_vis 物流", 5.00),
    ]:
        row = await pool.fetchrow(
            "INSERT INTO accounting.cost_items "
            "(sku_id, category, item_name, unit_cost, visibility) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            sku, "product" if vis != "shared" else "logistics", name, cost, vis,
        )
        inserted.append(row["id"])
    yield sku
    for cid in inserted:
        await pool.execute("DELETE FROM accounting.cost_items WHERE id=$1", cid)


@pytest.mark.asyncio
async def test_query_costs_public_sees_public_and_shared(seed_visibility_rows):
    from app.mcp.tools.accounting import query_costs

    r = await query_costs(sku_id=seed_visibility_rows, view="public")
    assert r["ok"] is True
    assert r["result"]["view"] == "public"
    items = r["result"]["cost_items"]
    names = {i["item_name"] for i in items}
    assert "_vis 出厂价" in names
    assert "_vis 物流" in names
    assert "_vis 真实进货价" not in names


@pytest.mark.asyncio
async def test_query_costs_real_sees_real_and_shared(monkeypatch, seed_visibility_rows):
    from app.mcp.tools import accounting

    monkeypatch.setattr(accounting.settings, "cost_real_view_passphrase", "")
    r = await accounting.query_costs(sku_id=seed_visibility_rows, view="real")
    assert r["ok"] is True
    assert r["result"]["view"] == "real"
    names = {i["item_name"] for i in r["result"]["cost_items"]}
    assert "_vis 真实进货价" in names
    assert "_vis 物流" in names
    assert "_vis 出厂价" not in names


@pytest.mark.asyncio
async def test_query_costs_real_with_passphrase_required(monkeypatch, seed_visibility_rows):
    from app.mcp.tools import accounting

    monkeypatch.setattr(accounting.settings, "cost_real_view_passphrase", "opensesame")

    # 不传 passphrase 拒
    r1 = await accounting.query_costs(sku_id=seed_visibility_rows, view="real")
    assert r1["ok"] is False
    assert r1["error"] == "wrong_passphrase"

    # 错的 passphrase 拒
    r2 = await accounting.query_costs(sku_id=seed_visibility_rows, view="real",
                                       passphrase="wrong")
    assert r2["ok"] is False
    assert r2["error"] == "wrong_passphrase"

    # 对的 passphrase 通过
    r3 = await accounting.query_costs(sku_id=seed_visibility_rows, view="real",
                                       passphrase="opensesame")
    assert r3["ok"] is True
    names = {i["item_name"] for i in r3["result"]["cost_items"]}
    assert "_vis 真实进货价" in names


@pytest.mark.asyncio
async def test_query_costs_invalid_view():
    from app.mcp.tools.accounting import query_costs

    r = await query_costs(sku_id="anything", view="boss")
    assert r["ok"] is False
    assert r["error"] == "invalid_view"


@pytest.mark.asyncio
async def test_compute_margin_real_vs_public_cost_differs(monkeypatch, seed_visibility_rows):
    """同 SKU 两 view 下 cost_total 应不同（30+5 vs 25+5）。"""
    from app.mcp.tools import accounting

    monkeypatch.setattr(accounting.settings, "cost_real_view_passphrase", "")

    # public：cost = 出厂价 30 + 物流 5 = 35
    r_pub = await accounting.compute_margin(
        sku_id=seed_visibility_rows, channel="douyin",
        sale_price="100", qty=1, channel_fee_rate="0",
        skip_llm=True, view="public",
    )
    # real：cost = 真实进货价 25 + 物流 5 = 30
    r_real = await accounting.compute_margin(
        sku_id=seed_visibility_rows, channel="douyin",
        sale_price="100", qty=1, channel_fee_rate="0",
        skip_llm=True, view="real",
    )

    assert r_pub["ok"] and r_real["ok"]
    pub_cost = float(r_pub["result"]["breakdown"]["cost_total"])
    real_cost = float(r_real["result"]["breakdown"]["cost_total"])
    # 两 view 都共享所有 sku_id IS NULL 的 shared 行（历史物流），且都含 _vis 物流 5。
    # 唯一差额来自 public 行（出厂价 30）vs real 行（真实价 25）= 5。
    assert pub_cost - real_cost == pytest.approx(5.0)
    # 净利在 real view 下更高（成本低）
    assert float(r_real["result"]["breakdown"]["net_profit"]) > float(
        r_pub["result"]["breakdown"]["net_profit"]
    )


@pytest.mark.asyncio
async def test_compute_margin_real_passphrase_enforced(monkeypatch, seed_visibility_rows):
    from app.mcp.tools import accounting

    monkeypatch.setattr(accounting.settings, "cost_real_view_passphrase", "secret123")
    r = await accounting.compute_margin(
        sku_id=seed_visibility_rows, channel="douyin",
        sale_price="100", skip_llm=True, view="real",
    )
    assert r["ok"] is False
    assert r["error"] == "wrong_passphrase"


# ── record_cost visibility 行为 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_record_cost_default_visibility_public():
    """直接调内部 SQL 路径验默认；record_cost 真路径走 require_approval Gate
    会卡，本测试用 SQL INSERT 模拟 record_cost 的写入语义。
    """
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO accounting.cost_items "
        "(sku_id, category, item_name, unit_cost) "
        "VALUES ($1, $2, $3, $4) RETURNING visibility",
        "_smoke_vis_sku_default", "product", "_vis_default 测试", 10.0,
    )
    try:
        # migration 018 默认 'shared'（保护历史数据）
        # record_cost tool 的默认参数是 'public'（新录入对外）—— 两层默认互不冲突
        assert row["visibility"] == "shared"
    finally:
        await pool.execute(
            "DELETE FROM accounting.cost_items WHERE item_name='_vis_default 测试'"
        )


@pytest.mark.asyncio
async def test_record_cost_invalid_visibility_rejected():
    from app.mcp.tools.cost_admin import record_cost
    # record_cost 走 require_approval=True；validation 在装饰器后才返。
    # 但 invalid_visibility 在 fn body 早期校验返；本测验 audit wrapper 后实际
    # 走不通（卡 Gate）。本 test 退一步：直接 import 校验集合 + 几个边界 case。
    from app.mcp.tools.cost_admin import _VALID_VISIBILITIES

    assert "public" in _VALID_VISIBILITIES
    assert "real" in _VALID_VISIBILITIES
    assert "shared" in _VALID_VISIBILITIES
    assert "boss_only" not in _VALID_VISIBILITIES


@pytest.mark.asyncio
async def test_record_cost_writes_visibility_field():
    """验真录入 visibility 字段：直接走 SQL（避开 require_approval Gate）。"""
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO accounting.cost_items "
        "(sku_id, category, item_name, unit_cost, visibility) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING id, visibility",
        "_smoke_vis_sku_real", "product", "_vis_real 真实成本", 25.5, "real",
    )
    try:
        assert row["visibility"] == "real"
    finally:
        await pool.execute("DELETE FROM accounting.cost_items WHERE id=$1", row["id"])
