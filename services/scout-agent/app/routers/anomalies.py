from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_pool

router = APIRouter()


class ExpectedRequest(BaseModel):
    """一键标记"这是预期的"请求体。"""
    reason: Optional[str] = None
    days: Optional[int] = None      # 抑制窗口天数（end_date = today + days）；None = 永久
    scope: str = "this"             # 'this' 精确 sku+metric+rule / 'metric' 该指标全 sku / 'all' 该平台全


@router.get("/anomalies")
async def list_anomalies(
    unhandled_only: bool = True,
    sku_id: Optional[str] = None,
    limit: int = 50,
):
    pool = await get_pool()
    wheres = []
    params: list = []
    if unhandled_only:
        wheres.append("NOT handled")
    if sku_id:
        params.append(sku_id)
        wheres.append(f"a.sku_id = ${len(params)}")
    where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    params.append(limit)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT a.*, s.name AS sku_name
            FROM mvp_anomaly a
            LEFT JOIN mvp_sku s ON s.id = a.sku_id
            {where_clause}
            ORDER BY
                CASE severity WHEN 'urgent' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                detected_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.patch("/anomalies/{anomaly_id}")
async def mark_handled(anomaly_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE mvp_anomaly SET handled=TRUE, handled_at=NOW() WHERE id=$1",
            anomaly_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return {"id": anomaly_id, "handled": True}


@router.post("/anomalies/{anomaly_id}/expected")
async def mark_expected(anomaly_id: int, body: ExpectedRequest):
    """
    R-18 自学习抑制的"一键这是预期的"后端。
    标该异常 expected=TRUE + handled=TRUE，并按其 sku_id/metric_name/platform/rule_id
    插一条 mvp_expected_event（start_date=今天，end_date=今天+days 或 NULL）。
    scope 控通配粒度：
      'this'   精确 sku + metric + rule（默认）
      'metric' 该指标全 sku（sku_id 通配）
      'all'    该平台全（sku_id + metric_name + rule_id 全通配）
    下次检测命中该预期窗口的异常会被静默抑制（不再产新异常行）。
    """
    pool = await get_pool()
    today = date.today()
    end_date = (today + timedelta(days=body.days)) if body.days else None

    async with pool.acquire() as conn:
        anomaly = await conn.fetchrow(
            "SELECT sku_id, metric_name, rule_id, platform FROM mvp_anomaly WHERE id = $1",
            anomaly_id,
        )
        if anomaly is None:
            raise HTTPException(status_code=404, detail="Anomaly not found")

        platform = anomaly["platform"] or "douyin"
        # scope 决定哪些字段写 NULL（通配）
        if body.scope == "all":
            ev_sku, ev_metric, ev_rule = None, None, None
        elif body.scope == "metric":
            ev_sku, ev_metric, ev_rule = None, anomaly["metric_name"], anomaly["rule_id"]
        else:  # 'this'（默认）
            ev_sku, ev_metric, ev_rule = anomaly["sku_id"], anomaly["metric_name"], anomaly["rule_id"]

        async with conn.transaction():
            await conn.execute(
                "UPDATE mvp_anomaly SET expected=TRUE, handled=TRUE, handled_at=NOW() WHERE id=$1",
                anomaly_id,
            )
            event_id = await conn.fetchval(
                """
                INSERT INTO mvp_expected_event
                    (sku_id, metric_name, platform, rule_id, start_date, end_date, reason)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                ev_sku, ev_metric, platform, ev_rule, today, end_date, body.reason,
            )

    return {
        "id": anomaly_id,
        "expected": True,
        "handled": True,
        "expected_event_id": event_id,
        "scope": body.scope,
        "start_date": str(today),
        "end_date": str(end_date) if end_date else None,
    }


@router.get("/expected-events")
async def list_expected_events(active_only: bool = True, limit: int = 100):
    """当前抑制项列表（active_only=True 只看今天仍生效的）。"""
    pool = await get_pool()
    wheres: list[str] = []
    params: list = []
    if active_only:
        wheres.append("(end_date IS NULL OR end_date >= CURRENT_DATE)")
    where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    params.append(limit)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT e.*, s.name AS sku_name
            FROM mvp_expected_event e
            LEFT JOIN mvp_sku s ON s.id = e.sku_id
            {where_clause}
            ORDER BY e.created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [dict(r) for r in rows]
