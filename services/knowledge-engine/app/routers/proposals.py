"""诊断官《改进提议》+ 问数 REST router（蓝图 §6.2 + §6.1 "推到老板眼前不只写 markdown"）。

给前端"改进建议"收件箱 + 趋势归因下钻用（桌面客户端经 IPC→http 调，调不了 MCP tool）：
- GET  /api/v1/mcp/proposals          列提议（默认 open，带消化率）
- POST /api/v1/mcp/proposals/diagnose 触发跑一轮诊断（content / analysis）
- POST /api/v1/mcp/proposals/{id}/resolve  老板三态拍板（接受/忽略/snooze）
- GET  /api/v1/mcp/explain-anomaly?anomaly_id=         解释某条异动（分层归因）
- GET  /api/v1/mcp/metric-trend?metric_name=&...       某指标近 N 天趋势序列

逻辑全在 diagnose_service（与 MCP tool 共用同一份函数，禁漂移）。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import diagnose_service as svc

router = APIRouter(prefix="/api/v1/mcp/proposals", tags=["mcp-proposals"])

# 问数端点不挂 /proposals 前缀（语义是"读指标/异动"，非"改进提议"），单独一个 router 挂同 app。
query_router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-diagnose-query"])


class DiagnoseRequest(BaseModel):
    mode: str = "content"
    lookback_days: int = 7
    persist: bool = True
    platform: str = "douyin"


class ResolveRequest(BaseModel):
    action: str                     # accept / ignore / snooze
    note: str | None = None
    snooze_days: int = 7


@router.get("")
async def list_proposals_endpoint(
    status: str = "open",
    mode: str | None = None,
    limit: int = 50,
) -> dict:
    return await svc.list_proposals(status=status, mode=mode, limit=limit)


@router.post("/diagnose")
async def diagnose_endpoint(payload: DiagnoseRequest) -> dict:
    return await svc.run_diagnose(
        mode=payload.mode, lookback_days=payload.lookback_days,
        persist=payload.persist, platform=payload.platform,
    )


@router.post("/{proposal_id}/resolve")
async def resolve_endpoint(proposal_id: str, payload: ResolveRequest):
    result = await svc.resolve_proposal(
        proposal_id=proposal_id, action=payload.action,
        note=payload.note, snooze_days=payload.snooze_days,
    )
    if not result.get("ok"):
        code = 404 if result.get("error") == "not_found" else 400
        return JSONResponse(content=result, status_code=code)
    return result


# ───────────────────────── 问数端点（与 MCP tool 共用 service 函数）─────────────


@query_router.get("/explain-anomaly")
async def explain_anomaly_endpoint(anomaly_id: int):
    """解释某条趋势异动（分层归因 + 近 28 天序列）。与 explain_anomaly tool 同一逻辑。"""
    result = await svc.explain_anomaly(anomaly_id=anomaly_id)
    if not result.get("ok"):
        code = 404 if result.get("error") == "not_found" else 400
        return JSONResponse(content=result, status_code=code)
    return result


@query_router.get("/metric-trend")
async def metric_trend_endpoint(
    metric_name: str,
    sku_id: str | None = None,
    platform: str = "douyin",
    days: int = 28,
):
    """某指标近 days 天趋势序列 + 基线。与 query_metric_trend tool 同一逻辑。"""
    result = await svc.query_metric_trend(
        metric_name=metric_name, sku_id=sku_id, platform=platform, days=days,
    )
    if not result.get("ok"):
        code = 400
        return JSONResponse(content=result, status_code=code)
    return result
