"""W3b: 5 个 scout fetch tool。

直读 mvp_* 表的最近一天入库数据，不去 trigger scout-agent runbook 重跑
（cookies 状态/异步 polling 复杂度高）。memory 实锤 8 套件 A-H 已 success
跑过 + 数据已入库（2026-05-03）。

5 个 tool：
- fetch_compass_store_daily(date?) — 全店日报
- fetch_compass_sku_detail(sku_id, date?) — 单 SKU
- fetch_compass_search_traffic(date?) — 搜索流量营销
- fetch_yuntu_5a(date?) — 5A 资产
- fetch_yuntu_brand_mind(date?) — 品牌心智
"""
from __future__ import annotations

from datetime import date as date_cls

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp


def _parse_date(date_str: str | None) -> date_cls | None:
    """解析 ISO 日期，None 透传，非法抛 ValueError。"""
    if date_str is None:
        return None
    return date_cls.fromisoformat(date_str)


_SHOP_SENTINEL = "_SHOP_"  # scout-agent runbook_executor 约定的全店行 sku_id sentinel


@tool_with_audit(mcp, require_approval=False)
async def fetch_compass_store_daily(date: str | None = None) -> dict:
    """读罗盘全店日报最近一天数据（source_runbook LIKE 'compass/%' AND sku_id='_SHOP_'）。

    Args:
        date: ISO 日期（"2026-05-03"）。None = DB 中最近一天有数据的日期。

    Returns:
        {ok, result: {date, metrics: [{metric_name, value, source_runbook}], count}, trace}
    """
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式（如 2026-05-03），给的是 {date!r}: {exc}",
        }

    pool = get_pool()
    if target_date is None:
        latest = await pool.fetchval(
            """
            SELECT MAX(date) FROM mvp_daily_metric
            WHERE source_runbook LIKE 'compass/%' AND sku_id = $1
            """,
            _SHOP_SENTINEL,
        )
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": "mvp_daily_metric 中无 compass 全店日报数据；先去 scout-agent 跑 runbook A",
            }
        target_date = latest

    rows = await pool.fetch(
        """
        SELECT metric_name, value, source_runbook
        FROM mvp_daily_metric
        WHERE source_runbook LIKE 'compass/%' AND sku_id = $1 AND date = $2
        ORDER BY source_runbook, metric_name
        """,
        _SHOP_SENTINEL,
        target_date,
    )
    if not rows:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"date={target_date.isoformat()} 无 compass 全店日报数据",
        }

    metrics = [
        {
            "metric_name": r["metric_name"],
            "value": str(r["value"]) if r["value"] is not None else None,
            "source_runbook": r["source_runbook"],
        }
        for r in rows
    ]
    return {
        "ok": True,
        "result": {
            "date": target_date.isoformat(),
            "metrics": metrics,
            "count": len(metrics),
        },
        "trace": {
            "db_query": "mvp_daily_metric WHERE source_runbook LIKE 'compass/%' AND sku_id='_SHOP_'",
            "row_count": len(metrics),
        },
    }


_SEARCH_TRAFFIC_PREFIXES = ("compass/search", "compass/business")


@tool_with_audit(mcp, require_approval=False)
async def fetch_compass_sku_detail(sku_id: str, date: str | None = None) -> dict:
    """读指定 SKU 的罗盘最近一天数据。

    Args:
        sku_id: SKU id（必填，如 'SKU-367991-0002'）
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {sku_id, date, metrics, count}, trace}
    """
    if not sku_id or not sku_id.strip():
        return {
            "ok": False,
            "error": "invalid_sku_id",
            "hint": "sku_id 不能为空",
        }
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式: {exc}",
        }

    pool = get_pool()
    if target_date is None:
        latest = await pool.fetchval(
            """
            SELECT MAX(date) FROM mvp_daily_metric
            WHERE source_runbook LIKE 'compass/%' AND sku_id = $1
            """,
            sku_id,
        )
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": f"mvp_daily_metric 中无 sku_id={sku_id} 的 compass 数据",
            }
        target_date = latest

    rows = await pool.fetch(
        """
        SELECT metric_name, value, source_runbook
        FROM mvp_daily_metric
        WHERE source_runbook LIKE 'compass/%' AND sku_id = $1 AND date = $2
        ORDER BY source_runbook, metric_name
        """,
        sku_id,
        target_date,
    )
    if not rows:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"sku_id={sku_id} date={target_date.isoformat()} 无 compass 数据",
        }

    metrics = [
        {
            "metric_name": r["metric_name"],
            "value": str(r["value"]) if r["value"] is not None else None,
            "source_runbook": r["source_runbook"],
        }
        for r in rows
    ]
    return {
        "ok": True,
        "result": {
            "sku_id": sku_id,
            "date": target_date.isoformat(),
            "metrics": metrics,
            "count": len(metrics),
        },
        "trace": {
            "db_query": "mvp_daily_metric WHERE source_runbook LIKE 'compass/%' AND sku_id=$1",
            "row_count": len(metrics),
        },
    }


@tool_with_audit(mcp, require_approval=False)
async def fetch_compass_search_traffic(date: str | None = None) -> dict:
    """读罗盘搜索/流量/营销相关数据最近一天。

    覆盖 source_runbook：compass/search-* + compass/business-*
    （搜索词、流量分版、广告/营销类，按入库 source_runbook 名筛选）

    Args:
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {date, metrics, count}, trace}
    """
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式: {exc}",
        }

    pool = get_pool()
    where_runbook = " OR ".join(
        f"source_runbook LIKE '{prefix}%'" for prefix in _SEARCH_TRAFFIC_PREFIXES
    )

    if target_date is None:
        latest = await pool.fetchval(
            f"SELECT MAX(date) FROM mvp_daily_metric WHERE ({where_runbook})"
        )
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": "mvp_daily_metric 中无 compass search/business 数据",
            }
        target_date = latest

    rows = await pool.fetch(
        f"""
        SELECT sku_id, metric_name, value, source_runbook
        FROM mvp_daily_metric
        WHERE ({where_runbook}) AND date = $1
        ORDER BY source_runbook, sku_id, metric_name
        """,
        target_date,
    )
    if not rows:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"date={target_date.isoformat()} 无 compass search/business 数据",
        }

    metrics = [
        {
            "sku_id": None if (r["sku_id"] in ("", _SHOP_SENTINEL)) else r["sku_id"],
            "metric_name": r["metric_name"],
            "value": str(r["value"]) if r["value"] is not None else None,
            "source_runbook": r["source_runbook"],
        }
        for r in rows
    ]
    return {
        "ok": True,
        "result": {
            "date": target_date.isoformat(),
            "metrics": metrics,
            "count": len(metrics),
        },
        "trace": {
            "db_query": f"mvp_daily_metric WHERE ({where_runbook})",
            "row_count": len(metrics),
        },
    }


@tool_with_audit(mcp, require_approval=False)
async def fetch_yuntu_5a(date: str | None = None) -> dict:
    """读云图 5A 资产最近一天。

    返回每个 (brand_id, sku_id) 组合一行，含 O/A1-A5/total 数值
    + 行业平均（industry_avg 子对象）。

    Args:
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {date, rows: [{brand_id, sku_id, o_count, a1_aware, ..., industry_avg}], count}, trace}
    """
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式: {exc}",
        }

    pool = get_pool()
    if target_date is None:
        latest = await pool.fetchval("SELECT MAX(date) FROM mvp_5a_asset_daily")
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": "mvp_5a_asset_daily 表无数据；先去 scout-agent 跑 yuntu/spu-5a runbook",
            }
        target_date = latest

    rows_db = await pool.fetch(
        """
        SELECT date, brand_id, sku_id,
               o_count, a1_aware, a2_appeal, a3_ask, a4_act, a5_advocate, total_5a,
               o_industry_avg, a1_industry_avg, a2_industry_avg, a3_industry_avg,
               a4_industry_avg, a5_industry_avg, total_industry_avg
        FROM mvp_5a_asset_daily
        WHERE date = $1
        ORDER BY brand_id, sku_id
        """,
        target_date,
    )
    if not rows_db:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"mvp_5a_asset_daily 在 date={target_date.isoformat()} 无数据",
        }

    rows = [
        {
            "brand_id": r["brand_id"],
            "sku_id": r["sku_id"] or None,
            "o_count": r["o_count"],
            "a1_aware": r["a1_aware"],
            "a2_appeal": r["a2_appeal"],
            "a3_ask": r["a3_ask"],
            "a4_act": r["a4_act"],
            "a5_advocate": r["a5_advocate"],
            "total_5a": r["total_5a"],
            "industry_avg": {
                "o_industry_avg": r["o_industry_avg"],
                "a1_industry_avg": r["a1_industry_avg"],
                "a2_industry_avg": r["a2_industry_avg"],
                "a3_industry_avg": r["a3_industry_avg"],
                "a4_industry_avg": r["a4_industry_avg"],
                "a5_industry_avg": r["a5_industry_avg"],
                "total_industry_avg": r["total_industry_avg"],
            },
        }
        for r in rows_db
    ]
    return {
        "ok": True,
        "result": {
            "date": target_date.isoformat(),
            "rows": rows,
            "count": len(rows),
        },
        "trace": {
            "db_query": "mvp_5a_asset_daily WHERE date=$1",
            "row_count": len(rows),
        },
    }


@tool_with_audit(mcp, require_approval=False)
async def fetch_yuntu_brand_mind(date: str | None = None) -> dict:
    """读云图品牌心智最近一天数据。

    返回每个 (brand_id, sku_id) 一行：品牌资产关联数 + 行业份额 + 行业排名 +
    品牌心智 3 指标（reputation 美誉度 / preference 偏好度 / connection 联结度）+
    停留 / 渗透 / 增长。

    Args:
        date: ISO 日期，None = 最近一天

    Returns:
        {ok, result: {date, rows, count}, trace}
    """
    try:
        target_date = _parse_date(date)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_date",
            "hint": f"date 必须是 ISO 格式: {exc}",
        }

    pool = get_pool()
    if target_date is None:
        latest = await pool.fetchval("SELECT MAX(date) FROM mvp_brand_mind_daily")
        if latest is None:
            return {
                "ok": False,
                "error": "no_data",
                "hint": "mvp_brand_mind_daily 表无数据；先去 scout-agent 跑 yuntu brand-mind runbook",
            }
        target_date = latest

    rows_db = await pool.fetch(
        """
        SELECT brand_id, sku_id, brand_assoc_count, industry_share,
               industry_rank, reputation, preference, dwell, connection, increase
        FROM mvp_brand_mind_daily
        WHERE date = $1
        ORDER BY brand_id, sku_id
        """,
        target_date,
    )
    if not rows_db:
        return {
            "ok": False,
            "error": "no_data",
            "hint": f"mvp_brand_mind_daily 在 date={target_date.isoformat()} 无数据",
        }

    rows = [
        {
            "brand_id": r["brand_id"],
            "sku_id": r["sku_id"] or None,
            "brand_assoc_count": r["brand_assoc_count"],
            "industry_share": str(r["industry_share"]) if r["industry_share"] is not None else None,
            "industry_rank": r["industry_rank"],
            "reputation": str(r["reputation"]) if r["reputation"] is not None else None,
            "preference": str(r["preference"]) if r["preference"] is not None else None,
            "dwell": r["dwell"],
            "connection": r["connection"],
            "increase": r["increase"],
        }
        for r in rows_db
    ]
    return {
        "ok": True,
        "result": {
            "date": target_date.isoformat(),
            "rows": rows,
            "count": len(rows),
        },
        "trace": {
            "db_query": "mvp_brand_mind_daily WHERE date=$1",
            "row_count": len(rows),
        },
    }
