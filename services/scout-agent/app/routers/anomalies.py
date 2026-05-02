from typing import Optional

from fastapi import APIRouter, HTTPException

from app.database import get_pool

router = APIRouter()


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
