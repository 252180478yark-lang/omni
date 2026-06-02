"""W3a T8：cost_admin tools 集成测（hits dev DB）。"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from app.database import get_pool, init_pool, close_pool
from app.mcp import human_gate as _hg


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def _approve_immediately(monkeypatch):
    """测试用 monkey patch：让 request_approval 立刻返 approved。"""
    async def _fake_approve(*, tool_call_id, summary, tool_name=None, timeout_seconds=3600, poll_interval_seconds=2.0):
        return {"decision": "approved", "decision_note": "auto-approved in test"}
    monkeypatch.setattr(_hg, "request_approval", _fake_approve)
    yield


@pytest_asyncio.fixture
async def _reject_immediately(monkeypatch):
    async def _fake_reject(*, tool_call_id, summary, tool_name=None, timeout_seconds=3600, poll_interval_seconds=2.0):
        return {"decision": "rejected", "decision_note": "auto-rejected in test"}
    monkeypatch.setattr(_hg, "request_approval", _fake_reject)
    yield


@pytest.mark.asyncio
async def test_smoke_record_cost_approved_inserts(_approve_immediately):
    """approved → cost_items 多 1 行。"""
    from app.mcp.tools.cost_admin import record_cost

    pool = get_pool()
    item_name = f"_smoke_record_{uuid.uuid4().hex[:8]}"
    resp = await record_cost(
        sku_id=None,
        category="logistics",
        item_name=item_name,
        unit_cost="5.50",
        currency="CNY",
        unit="次",
        quantity_per_unit="1",
        vendor="顺丰",
        valid_from="2026-05-05",
        valid_to=None,
        notes="单元测试",
    )
    assert resp["ok"] is True
    inserted_id = resp["result"]["cost_item_id"]
    assert inserted_id

    row = await pool.fetchrow(
        "SELECT category, item_name, unit_cost, vendor FROM accounting.cost_items WHERE id=$1",
        uuid.UUID(inserted_id),
    )
    assert row["category"] == "logistics"
    assert row["item_name"] == item_name
    assert str(row["unit_cost"]) == "5.5000"
    assert row["vendor"] == "顺丰"

    # 清理
    await pool.execute(
        "DELETE FROM accounting.cost_items WHERE id=$1", uuid.UUID(inserted_id)
    )


@pytest.mark.asyncio
async def test_smoke_record_cost_rejected_does_not_insert(_reject_immediately):
    """rejected → cost_items 没多行。"""
    from app.mcp.tools.cost_admin import record_cost

    pool = get_pool()
    item_name = f"_smoke_record_rej_{uuid.uuid4().hex[:8]}"
    before = await pool.fetchval(
        "SELECT COUNT(*) FROM accounting.cost_items WHERE item_name=$1", item_name
    )
    resp = await record_cost(
        sku_id=None,
        category="logistics",
        item_name=item_name,
        unit_cost="5.5",
    )
    assert resp["ok"] is False
    assert resp["error"] == "rejected_by_user"

    after = await pool.fetchval(
        "SELECT COUNT(*) FROM accounting.cost_items WHERE item_name=$1", item_name
    )
    assert after == before


@pytest.mark.asyncio
async def test_smoke_disable_cost_item_approved(_approve_immediately):
    """disable 走 Gate；approved 后行 is_active=False。"""
    from app.mcp.tools.cost_admin import disable_cost_item

    pool = get_pool()
    # 先插一条
    item_id = uuid.uuid4()
    item_name = f"_smoke_disable_{uuid.uuid4().hex[:8]}"
    await pool.execute(
        "INSERT INTO accounting.cost_items "
        "  (id, sku_id, category, item_name, unit_cost) "
        "VALUES ($1, NULL, 'logistics', $2, 1.0)",
        item_id, item_name,
    )

    resp = await disable_cost_item(cost_item_id=str(item_id), reason="测试")
    assert resp["ok"] is True
    assert resp["result"]["disabled"] is True

    row = await pool.fetchrow(
        "SELECT is_active FROM accounting.cost_items WHERE id=$1", item_id
    )
    assert row["is_active"] is False

    await pool.execute("DELETE FROM accounting.cost_items WHERE id=$1", item_id)


@pytest.mark.asyncio
async def test_smoke_record_cost_invalid_category(_approve_immediately):
    """category 不在 product/logistics/partner_quote 内 → 返 ok=False, 不写入。"""
    from app.mcp.tools.cost_admin import record_cost

    resp = await record_cost(
        sku_id=None,
        category="unknown_category",
        item_name="_smoke_invalid_cat",
        unit_cost="1",
    )
    assert resp["ok"] is False
    assert resp["error"] == "invalid_category"
