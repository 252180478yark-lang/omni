"""W3b: scout 5 tool 测试。

数据库 fixture：用 _smoke_W3b_ 前缀的 sku_id 行隔离，module teardown 清理。
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.mcp.tools.scout import (
    fetch_compass_store_daily,
)

SMOKE_PREFIX = "_smoke_W3b_"
TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    pool = get_pool()
    # 清理可能残留的 _smoke_ 行
    await pool.execute(
        "DELETE FROM mvp_daily_metric WHERE sku_id LIKE $1 OR source_run_id LIKE $2",
        SMOKE_PREFIX + "%",
        SMOKE_PREFIX + "%",
    )
    # 先插全店日报数据（sku_id='', source_run_id 用 _smoke_W3b_run1）
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('', $1, 'gmv_paid', 12345.6, 'compass/sell-analysis', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('', $1, 'visit_uv', 8765, 'compass/business-part', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    yield
    # teardown：清理 _smoke 数据
    await pool.execute(
        "DELETE FROM mvp_daily_metric WHERE source_run_id LIKE $1",
        SMOKE_PREFIX + "%",
    )
    await close_pool()


@pytest.mark.asyncio
async def test_fetch_compass_store_daily_returns_yesterday():
    result = await fetch_compass_store_daily(date=YESTERDAY.isoformat())
    assert result["ok"] is True
    res = result["result"]
    assert res["date"] == YESTERDAY.isoformat()
    assert res["count"] >= 2
    metric_names = {m["metric_name"] for m in res["metrics"]}
    assert "gmv_paid" in metric_names
    assert "visit_uv" in metric_names
    assert all("compass/" in m["source_runbook"] for m in res["metrics"])


@pytest.mark.asyncio
async def test_fetch_compass_store_daily_default_latest():
    """date=None 时返回最近一天有数据的日期。"""
    result = await fetch_compass_store_daily()
    assert result["ok"] is True
    # 应该至少返回我们插的 _smoke 数据
    assert result["result"]["count"] >= 2


@pytest.mark.asyncio
async def test_fetch_compass_store_daily_no_data():
    """查 1990-01-01（铁定无数据）应返回 no_data 错误。"""
    result = await fetch_compass_store_daily(date="1990-01-01")
    assert result["ok"] is False
    assert result["error"] == "no_data"


@pytest.mark.asyncio
async def test_fetch_compass_store_daily_invalid_date():
    """非 ISO 日期返回 invalid_date。"""
    result = await fetch_compass_store_daily(date="not-a-date")
    assert result["ok"] is False
    assert result["error"] == "invalid_date"
