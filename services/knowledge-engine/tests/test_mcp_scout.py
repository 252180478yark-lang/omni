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
    fetch_compass_sku_detail,
    fetch_compass_search_traffic,
    fetch_yuntu_5a,
    fetch_yuntu_brand_mind,
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
        "DELETE FROM mvp_daily_metric WHERE source_run_id LIKE $1",
        SMOKE_PREFIX + "%",
    )
    # 落库桥(source_runbook='metric_ingest')会往 (_SHOP_, 今/昨, gmv_paid 等) 写真数据，
    # 跟本测试种子的 (_SHOP_, YESTERDAY, <同名 metric>) 撞唯一键 (sku_id,date,metric_name)。
    # 先保存被撞的真行 → 删 → 让测试 seed；teardown 再恢复，绝不丢老板的落库桥数据。
    _SEED_SHOP_METRICS = ["gmv_paid", "visit_uv", "search_uv", "paid_clicks"]
    saved_real_rows = await pool.fetch(
        """
        SELECT sku_id, date, metric_name, value, source_runbook, source_run_id, raw
        FROM mvp_daily_metric
        WHERE date = $1 AND sku_id = '_SHOP_' AND metric_name = ANY($2::text[])
        """,
        YESTERDAY, _SEED_SHOP_METRICS,
    )
    await pool.execute(
        "DELETE FROM mvp_daily_metric WHERE date = $1 AND sku_id = '_SHOP_' AND metric_name = ANY($2::text[])",
        YESTERDAY, _SEED_SHOP_METRICS,
    )
    # 先插全店日报数据（sku_id='_SHOP_'，scout-agent 约定的 sentinel）
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('_SHOP_', $1, 'gmv_paid', 12345.6, 'compass/sell-analysis', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('_SHOP_', $1, 'visit_uv', 8765, 'compass/business-part', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    # SKU 级数据（sku_id='_smoke_W3b_sku_X', source_run_id 用 _smoke_W3b_run1）
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('_smoke_W3b_sku_X', $1, 'sku_gmv', 999.99, 'compass/sell-analysis', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('_smoke_W3b_sku_X', $1, 'sku_visit', 88, 'compass/sell-analysis', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('_SHOP_', $1, 'search_uv', 1234, 'compass/search-drainage-terms', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    await pool.execute(
        """
        INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
        VALUES ('_SHOP_', $1, 'paid_clicks', 567, 'compass/business-part', '_smoke_W3b_run1', '{}'::jsonb)
        """,
        YESTERDAY,
    )
    # brand_mind 数据先清后插
    await pool.execute(
        "DELETE FROM mvp_brand_mind_daily WHERE brand_id = '_smoke_W3b_brand'",
    )
    await pool.execute(
        """
        INSERT INTO mvp_brand_mind_daily
            (date, brand_id, sku_id, brand_assoc_count, industry_share,
             industry_rank, reputation, preference, dwell, connection, increase)
        VALUES ($1, '_smoke_W3b_brand', '', 555, 0.123456, 7, 0.85, 0.72,
                300, 150, 50)
        """,
        YESTERDAY,
    )
    # 5A 数据先清后插（不用 _smoke_W3b_run1，因为 mvp_5a_asset_daily 没 source_run_id 列）
    await pool.execute(
        "DELETE FROM mvp_5a_asset_daily WHERE brand_id = '_smoke_W3b_brand'",
    )
    await pool.execute(
        """
        INSERT INTO mvp_5a_asset_daily
            (date, brand_id, sku_id, o_count, a1_aware, a2_appeal, a3_ask, a4_act,
             a5_advocate, total_5a, o_industry_avg, a1_industry_avg, a2_industry_avg,
             a3_industry_avg, a4_industry_avg, a5_industry_avg, total_industry_avg)
        VALUES ($1, '_smoke_W3b_brand', '', 1000, 500, 200, 100, 50, 30, 880,
                10000, 5000, 2000, 1000, 500, 300, 8800)
        """,
        YESTERDAY,
    )
    yield
    # teardown：清理 _smoke 数据（_SHOP_ 测试行 source_run_id 也是 _smoke_W3b_run1，一并删）
    await pool.execute(
        "DELETE FROM mvp_daily_metric WHERE source_run_id LIKE $1",
        SMOKE_PREFIX + "%",
    )
    await pool.execute(
        "DELETE FROM mvp_5a_asset_daily WHERE brand_id = '_smoke_W3b_brand'",
    )
    await pool.execute(
        "DELETE FROM mvp_brand_mind_daily WHERE brand_id = '_smoke_W3b_brand'",
    )
    # 恢复被测试临时接管的落库桥真行（绝不丢老板真实数据）
    for r in saved_real_rows:
        await pool.execute(
            """
            INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, source_runbook, source_run_id, raw)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            ON CONFLICT (sku_id, date, metric_name) DO UPDATE
              SET value = EXCLUDED.value, source_runbook = EXCLUDED.source_runbook,
                  source_run_id = EXCLUDED.source_run_id, raw = EXCLUDED.raw
            """,
            r["sku_id"], r["date"], r["metric_name"], r["value"],
            r["source_runbook"], r["source_run_id"], r["raw"],
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
    assert result["result"]["date"] == YESTERDAY.isoformat()


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


@pytest.mark.asyncio
async def test_fetch_compass_sku_detail_returns_sku():
    result = await fetch_compass_sku_detail(
        sku_id="_smoke_W3b_sku_X",
        date=YESTERDAY.isoformat(),
    )
    assert result["ok"] is True
    res = result["result"]
    assert res["sku_id"] == "_smoke_W3b_sku_X"
    assert res["date"] == YESTERDAY.isoformat()
    metric_names = {m["metric_name"] for m in res["metrics"]}
    assert "sku_gmv" in metric_names
    assert "sku_visit" in metric_names


@pytest.mark.asyncio
async def test_fetch_compass_sku_detail_no_data_for_sku():
    result = await fetch_compass_sku_detail(
        sku_id="_smoke_W3b_nonexistent_sku",
        date=YESTERDAY.isoformat(),
    )
    assert result["ok"] is False
    assert result["error"] == "no_data"


@pytest.mark.asyncio
async def test_fetch_compass_sku_detail_default_latest():
    result = await fetch_compass_sku_detail(sku_id="_smoke_W3b_sku_X")
    assert result["ok"] is True
    assert result["result"]["count"] >= 2


@pytest.mark.asyncio
async def test_fetch_compass_search_traffic_returns():
    result = await fetch_compass_search_traffic(date=YESTERDAY.isoformat())
    assert result["ok"] is True
    res = result["result"]
    metric_names = {m["metric_name"] for m in res["metrics"]}
    assert "search_uv" in metric_names
    assert "paid_clicks" in metric_names
    sources = {m["source_runbook"] for m in res["metrics"]}
    assert all(
        s.startswith("compass/search") or s.startswith("compass/business")
        for s in sources
    )


@pytest.mark.asyncio
async def test_fetch_compass_search_traffic_default_latest():
    result = await fetch_compass_search_traffic()
    assert result["ok"] is True
    assert result["result"]["count"] >= 2


@pytest.mark.asyncio
async def test_fetch_yuntu_5a_returns_brand_row():
    result = await fetch_yuntu_5a(date=YESTERDAY.isoformat())
    assert result["ok"] is True
    res = result["result"]
    assert res["date"] == YESTERDAY.isoformat()
    smoke_rows = [r for r in res["rows"] if r["brand_id"] == "_smoke_W3b_brand"]
    assert len(smoke_rows) == 1
    row = smoke_rows[0]
    assert row["o_count"] == 1000
    assert row["a3_ask"] == 100
    assert row["total_5a"] == 880
    assert row["industry_avg"]["a3_industry_avg"] == 1000


@pytest.mark.asyncio
async def test_fetch_yuntu_5a_default_latest():
    result = await fetch_yuntu_5a()
    assert result["ok"] is True
    assert result["result"]["count"] >= 1


@pytest.mark.asyncio
async def test_fetch_yuntu_brand_mind_returns_smoke():
    result = await fetch_yuntu_brand_mind(date=YESTERDAY.isoformat())
    assert result["ok"] is True
    smoke_rows = [r for r in result["result"]["rows"] if r["brand_id"] == "_smoke_W3b_brand"]
    assert len(smoke_rows) == 1
    row = smoke_rows[0]
    assert row["brand_assoc_count"] == 555
    assert row["industry_rank"] == 7
    # numeric(8,6) 转 Decimal 序列化为 str
    assert row["reputation"] == "0.850000"
    assert row["preference"] == "0.720000"


@pytest.mark.asyncio
async def test_fetch_yuntu_brand_mind_default_latest():
    result = await fetch_yuntu_brand_mind()
    assert result["ok"] is True
    assert result["result"]["count"] >= 1
