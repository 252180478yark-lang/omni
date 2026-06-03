"""综合经营分析 + 临时问数 REST router（蓝图 §6.1 "推到老板眼前"，供桌面/前端读）。

桌面客户端经 IPC→http 调（调不了 MCP tool）。两套路由指向**同一份 service 函数**（禁漂移）：

1. 桌面契约（omni-desktop AiAnalysisPanel 实际在调，body = AnalyticsRange/Filter/focus 壳）：
   - POST /api/v1/mcp/analysis/comprehensive   {range, filter, focus, face?} → 综合经营分析
   - POST /api/v1/mcp/analysis/nl-query        {question, range, filter}     → 临时问数
2. 直测用 GET（curl/前端快速验证）：
   - GET /api/v1/analytics/ai-analysis?face=&days=&platform=&polish=
   - GET /api/v1/analytics/nl-query?q=&days=&platform=

逻辑全在 business_analysis_service（与 MCP tool 共用同一份函数）。纯读、无副作用。
"""
from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import business_analysis_service as svc
from app.services import metric_registry as reg

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

# 桌面契约 router：/api/v1/mcp/analysis/*（POST，吃 AnalyticsRange/Filter 壳）
mcp_analysis_router = APIRouter(prefix="/api/v1/mcp/analysis", tags=["analytics"])


# ───────────────────────── 入参壳（与 omni-desktop shared/types.ts 对齐）─────────────────────────


class _Range(BaseModel):
    preset: str = "30d"          # today | 7d | 30d | this_month | custom
    start: str | None = None     # YYYY-MM-DD（custom 用）
    end: str | None = None


class _ComprehensiveReq(BaseModel):
    range: _Range | None = None
    filter: dict | None = None   # {platform?, category?, sku_id?, audience_layer?, channel?}
    focus: str | None = None     # 老板临时关注点（注入叙事提示词）
    face: str | None = None      # owner（默认）| operator
    polish: bool | None = None   # 缺省 True（AI 面板就是要叙事层）


class _NlQueryReq(BaseModel):
    question: str
    range: _Range | None = None
    filter: dict | None = None


def _range_to_days(rng: _Range | None) -> int:
    """AnalyticsRange → 天数窗口（与桌面 preset 一致）。"""
    if rng is None:
        return 28
    preset = (rng.preset or "30d").lower()
    if preset == "today":
        return 1
    if preset == "7d":
        return 7
    if preset == "30d":
        return 30
    if preset == "this_month":
        return max(1, _dt.date.today().day)
    if preset == "custom" and rng.start and rng.end:
        try:
            s = _dt.date.fromisoformat(rng.start)
            e = _dt.date.fromisoformat(rng.end)
            return max(1, min((e - s).days + 1, 365))
        except Exception:  # noqa: BLE001
            return 28
    return 28


def _platform_of(flt: dict | None) -> str:
    return (flt or {}).get("platform") or "douyin"


# ───────────────────────── 桌面契约：POST ─────────────────────────


@mcp_analysis_router.post("/comprehensive")
async def comprehensive_post(req: _ComprehensiveReq):
    """综合经营分析（桌面 AiAnalysisPanel 调）。

    body: {range:{preset,start,end}, filter:{platform,sku_id,...}, focus, face?}
    返: {ok, markdown, sections, as_of, observed, hypotheses, ...}（fail-open，LLM 挂回退确定性骨架）。
    """
    days = _range_to_days(req.range)
    platform = _platform_of(req.filter)
    face = req.face if req.face in ("owner", "operator") else "owner"
    polish = True if req.polish is None else bool(req.polish)
    result = await svc.generate_business_analysis(
        face=face, days=days, platform=platform, polish=polish, focus=req.focus,
    )
    if not result.get("ok"):
        code = 400 if str(result.get("error", "")).startswith("invalid") else 500
        return JSONResponse(content=result, status_code=code)
    return result


@mcp_analysis_router.post("/nl-query")
async def nl_query_post(req: _NlQueryReq):
    """临时问数（桌面问数框调）。body: {question, range?, filter?} → {ok, answer, table}。"""
    days = _range_to_days(req.range)
    platform = _platform_of(req.filter)
    result = await svc.query_metric_nl(
        question=req.question, default_days=days, platform=platform,
    )
    # metric 没听出来：不报错，把候选清单作为 answer 返回（老板看着再说清）
    if not result.get("ok"):
        if result.get("error") == "metric_not_resolved":
            sup = result.get("supported") or []
            names = "、".join(s.get("cn", "") for s in sup[:20])
            return {
                "ok": True,
                "answer": (result.get("hint", "没听出要查哪个指标。") + "\n\n目前支持的指标：" + names),
            }
        code = 400 if result.get("error") in ("empty_question",) else 500
        return JSONResponse(content=result, status_code=code)

    # 序列 → 表格（桌面有 table 就渲图）
    series = result.get("series") or []
    cn = result.get("metric_cn") or result.get("metric_name") or "数值"
    table = None
    if series:
        table = {
            "columns": ["日期", cn],
            "rows": [[s.get("date"), s.get("value")] for s in series],
        }
    return {"ok": True, "answer": result.get("summary"), "table": table, "meta": {
        "metric_name": result.get("metric_name"), "metric_cn": cn,
        "sku_id": result.get("sku_id"), "days": result.get("days"),
        "benchmark": result.get("benchmark"), "baseline": result.get("baseline"),
    }}


# ───────────────────────── 直测用：GET ─────────────────────────


@router.get("/ai-analysis")
async def ai_analysis_endpoint(
    face: str = "owner",
    days: int = 28,
    platform: str = "douyin",
    polish: bool = False,
    focus: str | None = None,
):
    """综合经营分析（face='owner' 经营诊断 / 'operator' 投放选品建议）。GET 直测用。"""
    result = await svc.generate_business_analysis(
        face=face, days=days, platform=platform, polish=polish, focus=focus,
    )
    if not result.get("ok"):
        code = 400 if str(result.get("error", "")).startswith("invalid") else 500
        return JSONResponse(content=result, status_code=code)
    return result


@router.get("/nl-query")
async def nl_query_endpoint(
    q: str,
    days: int = 28,
    platform: str = "douyin",
):
    """临时问数：口语问句 q → 指标序列 + 简述（确定性，不归因）。GET 直测用。"""
    result = await svc.query_metric_nl(
        question=q, default_days=days, platform=platform,
    )
    if not result.get("ok"):
        code = 400 if result.get("error") in ("empty_question", "metric_not_resolved") else 500
        return JSONResponse(content=result, status_code=code)
    return result
