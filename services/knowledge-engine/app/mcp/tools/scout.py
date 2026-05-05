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


@tool_with_audit(mcp, require_approval=False)
async def fetch_compass_store_daily(date: str | None = None) -> dict:
    """读罗盘全店日报最近一天数据（source_runbook LIKE 'compass/%' AND sku_id='')。

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
            WHERE source_runbook LIKE 'compass/%' AND sku_id = ''
            """
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
        WHERE source_runbook LIKE 'compass/%' AND sku_id = '' AND date = $1
        ORDER BY source_runbook, metric_name
        """,
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
            "db_query": "mvp_daily_metric WHERE source_runbook LIKE 'compass/%' AND sku_id=''",
            "row_count": len(metrics),
        },
    }
