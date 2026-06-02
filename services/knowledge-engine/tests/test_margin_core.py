"""§3/R-4：_margin_core 单一口径纯函数单元测试。

**纯单元测试，不连 DB、不连 LLM、不连网络**——只断言 _margin_core 的数学口径正确，
覆盖正常 + 边界（无广告花费 roi=None、零成本、零毛利保本线为 None、份数折算、
partner_quote 不计入、qty>1、除零防护）。

跑法（cwd = services/knowledge-engine）：
    python -m pytest tests/test_margin_core.py -v
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.accounting_tool import _margin_core


def _D(x) -> Decimal:
    return Decimal(str(x))


# ── 基础正常用例 ───────────────────────────────────────────────


def test_basic_margin_no_fee():
    """售价 100、单件成本 60（product 40 + logistics 20）、无渠道费、qty=1。

    gmv=100, cost=60, fee=0, net=40, margin=0.4
    breakeven_roas = 1/0.4 = 2.5
    breakeven_price = 单件成本/(1-0) = 60
    roi = None（无广告花费入参）
    """
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 40, "quantity_per_unit": 1, "sku_id": "S"},
            {"category": "logistics", "unit_cost": 20, "quantity_per_unit": 1, "sku_id": None},
        ],
        sale_price=100,
        quantity=1,
        fee_rate=0,
    )
    assert core["gmv"] == _D(100)
    assert core["cost_subtotal"] == _D(60)
    assert core["channel_fee"] == _D(0)
    assert core["net_profit"] == _D(40)
    assert core["margin"] == _D("0.4")
    assert core["unit_cost_total"] == _D(60)
    assert core["items_used"] == 2
    # ROI 由后端投后层算，core 无广告花费入参 → None
    assert core["roi"] is None
    assert core["breakeven_roas"] == _D("2.5")
    assert core["breakeven_price"] == _D(60)
    # 共享判定
    shared_flags = {r["category"]: r["shared"] for r in core["breakdown"]}
    assert shared_flags["product"] is False  # sku_id 有值
    assert shared_flags["logistics"] is True  # sku_id None


def test_margin_with_channel_fee():
    """售价 100、单件成本 50、渠道费 2%、qty=1。

    gmv=100, cost=50, fee=2, net=48, margin=0.48
    breakeven_roas = 1/0.48
    breakeven_price = 50/(1-0.02) = 51.020408...
    """
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 50, "quantity_per_unit": 1, "sku_id": "S"},
        ],
        sale_price=100,
        quantity=1,
        fee_rate="0.02",
    )
    assert core["gmv"] == _D(100)
    assert core["cost_subtotal"] == _D(50)
    assert core["channel_fee"] == _D(2)
    assert core["net_profit"] == _D(48)
    assert core["margin"] == _D("0.48")
    assert core["breakeven_roas"] == (_D(1) / _D("0.48"))
    assert core["breakeven_price"] == (_D(50) / (_D(1) - _D("0.02")))


def test_quantity_per_unit_folding():
    """份数折算："一箱 24 瓶" unit_cost=240 → 单件成本 10。"""
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 240, "quantity_per_unit": 24, "sku_id": "S"},
        ],
        sale_price=30,
        quantity=1,
        fee_rate=0,
    )
    assert core["unit_cost_total"] == _D(10)
    assert core["cost_subtotal"] == _D(10)
    assert core["net_profit"] == _D(20)
    assert core["margin"] == (_D(20) / _D(30))
    # breakdown 行 line_cost = 单件成本 * qty = 10 * 1
    assert core["breakdown"][0]["line_cost"] == _D(10)


def test_quantity_multi_units():
    """qty>1：售价 50 单件成本 30，卖 3 件，渠道费 10%。

    gmv=150, cost=90, fee=15, net=45, margin=0.3
    breakdown line_cost = 30*3 = 90
    breakeven_price = 单件成本30/(1-0.1) = 33.333...（与 qty 无关，单件口径）
    """
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 30, "quantity_per_unit": 1, "sku_id": "S"},
        ],
        sale_price=50,
        quantity=3,
        fee_rate="0.1",
    )
    assert core["gmv"] == _D(150)
    assert core["cost_subtotal"] == _D(90)
    assert core["channel_fee"] == _D(15)
    assert core["net_profit"] == _D(45)
    assert core["margin"] == _D("0.3")
    assert core["breakdown"][0]["line_cost"] == _D(90)
    assert core["breakeven_price"] == (_D(30) / _D("0.9"))


# ── 边界用例 ───────────────────────────────────────────────────


def test_partner_quote_excluded_from_cost():
    """partner_quote 行不计入成本（仅比价参考）。"""
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 40, "quantity_per_unit": 1, "sku_id": "S"},
            {"category": "partner_quote", "unit_cost": 999, "quantity_per_unit": 1, "sku_id": "S"},
        ],
        sale_price=100,
        quantity=1,
        fee_rate=0,
    )
    assert core["cost_subtotal"] == _D(40)  # 999 的报价不算进来
    assert core["items_used"] == 1          # 只 1 行进 breakdown
    assert core["net_profit"] == _D(60)


def test_zero_cost():
    """零成本（无成本行）：cost=0，margin=1，breakeven_roas=1，breakeven_price=0。"""
    core = _margin_core(
        cost_lines=[],
        sale_price=50,
        quantity=1,
        fee_rate=0,
    )
    assert core["cost_subtotal"] == _D(0)
    assert core["unit_cost_total"] == _D(0)
    assert core["net_profit"] == _D(50)
    assert core["margin"] == _D(1)
    assert core["items_used"] == 0
    assert core["breakeven_roas"] == _D(1)   # 1 / 1
    assert core["breakeven_price"] == _D(0)  # 0 / (1-0)
    assert core["roi"] is None


def test_negative_margin_breakeven_roas_none():
    """亏本（成本 > 售价）：margin <= 0 → 没有保本点，breakeven_roas=None。"""
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 120, "quantity_per_unit": 1, "sku_id": "S"},
        ],
        sale_price=100,
        quantity=1,
        fee_rate=0,
    )
    assert core["net_profit"] == _D(-20)
    assert core["margin"] == _D("-0.2")
    assert core["breakeven_roas"] is None  # 毛利率<=0 无保本 ROAS
    # breakeven_price 仍可算（单件成本/(1-rate)）
    assert core["breakeven_price"] == _D(120)


def test_zero_gmv_margin_zero():
    """售价 0（gmv=0）：margin 兜底 0，不抛除零。"""
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 10, "quantity_per_unit": 1, "sku_id": "S"},
        ],
        sale_price=0,
        quantity=1,
        fee_rate=0,
    )
    assert core["gmv"] == _D(0)
    assert core["margin"] == _D(0)
    assert core["breakeven_roas"] is None  # margin 0 → None


def test_quantity_per_unit_missing_defaults_one():
    """quantity_per_unit 缺失/None/0 → 按 1 件折算，不除零崩。"""
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 15, "sku_id": "S"},               # 缺 per
            {"category": "logistics", "unit_cost": 5, "quantity_per_unit": 0, "sku_id": None},  # per=0
        ],
        sale_price=40,
        quantity=1,
        fee_rate=0,
    )
    # 15/1 + 5/1（per=0 防护按 1）= 20
    assert core["unit_cost_total"] == _D(20)
    assert core["net_profit"] == _D(20)


def test_fee_rate_ge_one_breakeven_price_none():
    """渠道扣点率 >=1（异常，扣点≥100%）：breakeven_price 无解 → None。"""
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 10, "quantity_per_unit": 1, "sku_id": "S"},
        ],
        sale_price=100,
        quantity=1,
        fee_rate="1.0",
    )
    assert core["breakeven_price"] is None


def test_cost_by_category_accumulates():
    """同类多行累加到 cost_by_category。"""
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": 10, "quantity_per_unit": 1, "sku_id": "S"},
            {"category": "product", "unit_cost": 5, "quantity_per_unit": 1, "sku_id": "S"},
            {"category": "logistics", "unit_cost": 3, "quantity_per_unit": 1, "sku_id": None},
        ],
        sale_price=50,
        quantity=1,
        fee_rate=0,
    )
    assert core["cost_by_category"]["product"] == _D(15)
    assert core["cost_by_category"]["logistics"] == _D(3)
    assert core["unit_cost_total"] == _D(18)


def test_decimal_precision_no_float_drift():
    """口径用 Decimal，不应出现 0.1+0.2 类 float 漂移。"""
    core = _margin_core(
        cost_lines=[
            {"category": "product", "unit_cost": "0.1", "quantity_per_unit": 1, "sku_id": "S"},
            {"category": "logistics", "unit_cost": "0.2", "quantity_per_unit": 1, "sku_id": None},
        ],
        sale_price="1.0",
        quantity=1,
        fee_rate=0,
    )
    assert core["cost_subtotal"] == _D("0.3")  # 不是 0.30000000000000004
    assert core["net_profit"] == _D("0.7")


def test_breakdown_passthrough_fields():
    """breakdown 行原样透传调用方给的额外字段（item_id/vendor/visibility）。"""
    core = _margin_core(
        cost_lines=[
            {
                "category": "product",
                "unit_cost": 40,
                "quantity_per_unit": 1,
                "sku_id": "S",
                "item_id": "abc",
                "item_name": "瓶身",
                "vendor": "和田宽",
                "visibility": "public",
            },
        ],
        sale_price=100,
        quantity=1,
        fee_rate=0,
    )
    row = core["breakdown"][0]
    assert row["item_id"] == "abc"
    assert row["item_name"] == "瓶身"
    assert row["vendor"] == "和田宽"
    assert row["visibility"] == "public"
    assert row["line_cost"] == _D(40)


if __name__ == "__main__":  # 允许直接 python 跑（不依赖 pytest 收集）
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
