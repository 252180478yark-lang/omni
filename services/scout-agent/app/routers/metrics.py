"""落库桥路由（2026-06-03）：手动触发 ingest + 读序列。

- POST /api/v1/scout/metrics/ingest  —— 实时取 10 端点 → 29 抽取器 + 同行标杆 → upsert 两表
- GET  /api/v1/scout/metrics/series  —— 读 mvp_daily_metric 某 metric 近 N 天序列（桌面/AI 取数）

executor 复用 fetch.py 注入的 live_fetch 单例（lifespan set_executor）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.routers.fetch import _exec
from app.services import metric_ingest

router = APIRouter()


@router.post("/metrics/ingest")
async def metrics_ingest():
    """全量落库一次（手动触发；cron 也调同一函数）。返回写入行数 + 错误明细。"""
    try:
        return await metric_ingest.ingest_metrics(_exec())
    except HTTPException:
        raise
    except Exception as exc:  # 抓不到 cookies / DB 异常等
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/metrics/series")
async def metrics_series(
    metric: str = Query(..., description="metric_name，如 gmv_paid / asset_5a_total"),
    days: int = Query(30, ge=1, le=365),
):
    """读全店某 metric 近 N 天序列。"""
    return await metric_ingest.fetch_series(metric, days)
