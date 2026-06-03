"""实时取数 MCP tool：HTTP 调 scout-agent /api/v1/scout/fetch。

5 个 tool（均 read/触发，require_approval=False）：
- platform_fetch / platform_batch_fetch / platform_list_endpoints / platform_auth_status
- ingest_platform_metrics（落库桥：手动触发全量 ingest → mvp_daily_metric + mvp_industry_benchmark）
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp

_TIMEOUT = 90.0  # 浏览器起 context + 导航 + XHR，给足
_FAIL_VERDICTS = {"FAIL_AUTH", "FAIL_404", "FAIL_DRIFT", "FAIL_OTHER", "EXCEPTION"}


def _base() -> str:
    return settings.scout_agent_url.rstrip("/")


async def _platform_fetch_impl(platform: str, endpoint: str,
                               params: dict | None = None, body: dict | None = None) -> dict:
    payload = {"platform": platform, "endpoint": endpoint, "params": params, "body": body}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            resp = await cli.post(f"{_base()}/api/v1/scout/fetch", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # scout-agent 不可达等
        return {"ok": False, "error": "scout_agent_unreachable",
                "hint": f"调 scout-agent 失败：{exc}；确认容器在跑"}
    verdict = data.get("verdict")
    if verdict in _FAIL_VERDICTS:
        return {"ok": False, "error": verdict,
                "hint": data.get("hint") or f"{endpoint} 取数 {verdict}",
                "result": data}
    return {"ok": True, "result": data, "trace": {"url": data.get("url"), "verdict": verdict}}


async def _batch_fetch_impl(requests: list[dict]) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT * 3) as cli:
            resp = await cli.post(f"{_base()}/api/v1/scout/fetch/batch",
                                  json={"requests": requests})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": "scout_agent_unreachable", "hint": str(exc)}
    passed = [d for d in data if d.get("verdict", "").startswith("PASS")]
    return {"ok": True, "result": {"results": data, "count": len(data),
                                   "pass_count": len(passed)},
            "trace": {"endpoints": [d.get("endpoint_key") for d in data]}}


async def _list_endpoints_impl(platform: str | None, query: str | None,
                               verified_only: bool) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            resp = await cli.get(f"{_base()}/api/v1/scout/fetch/endpoints",
                                 params={"platform": platform, "query": query,
                                         "verified_only": verified_only})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": "scout_agent_unreachable", "hint": str(exc)}
    return {"ok": True, "result": {"endpoints": data, "count": len(data)}}


async def _auth_status_impl() -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            resp = await cli.get(f"{_base()}/api/v1/scout/fetch/auth-status")
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": "scout_agent_unreachable", "hint": str(exc)}
    return {"ok": True, "result": data}


@tool_with_audit(mcp, require_approval=False)
async def platform_fetch(platform: str, endpoint: str,
                         params: dict | None = None, body: dict | None = None) -> dict:
    """实时取云图/罗盘/抖店单个端点的真实数据（浏览器登录态 + 原生签名）。

    Args:
        platform: yuntu|compass|doudian
        endpoint: 目录 key（用 platform_list_endpoints 检索）
        params: 覆盖目录默认参数（如 {"audience_end_date":"20260520"}）
        body: POST body 覆盖
    Returns:
        {ok, result:{verdict,status,code,has_data,fields,url}, trace} 或 {ok:false,error,hint}
    """
    return await _platform_fetch_impl(platform, endpoint, params, body)


@tool_with_audit(mcp, require_approval=False)
async def platform_batch_fetch(requests: list[dict]) -> dict:
    """一个浏览器会话连打多个端点。requests=[{platform,endpoint,params?,body?}]。"""
    return await _batch_fetch_impl(requests)


@tool_with_audit(mcp, require_approval=False)
async def platform_list_endpoints(platform: str | None = None, query: str | None = None,
                                  verified_only: bool = False) -> dict:
    """在端点目录里检索（按 platform / 关键词 / 是否已验证）。"""
    return await _list_endpoints_impl(platform, query, verified_only)


@tool_with_audit(mcp, require_approval=False)
async def platform_auth_status() -> dict:
    """报告三平台 cookies 是否有效（无效需去 /scout 扫码登录）。"""
    return await _auth_status_impl()


async def _ingest_metrics_impl() -> dict:
    """触发 scout-agent 落库桥全量 ingest（实时取 10 端点 → 29 抽取器 → upsert 两表）。"""
    try:
        # ingest 走浏览器 + 多端点，给足时间
        async with httpx.AsyncClient(timeout=600.0) as cli:
            resp = await cli.post(f"{_base()}/api/v1/scout/metrics/ingest")
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": "scout_agent_unreachable",
                "hint": f"调 scout-agent /metrics/ingest 失败：{exc}；确认容器在跑 + 三平台已登录"}
    if not data.get("ok"):
        return {"ok": False, "error": data.get("error", "ingest_failed"), "result": data}
    return {"ok": True, "result": data,
            "trace": {"metric_rows": data.get("metric_rows_written"),
                      "benchmark_rows": data.get("benchmark_rows_written"),
                      "extractors": f"{data.get('metrics_ok')}/{data.get('metrics_total')}"}}


@tool_with_audit(mcp, require_approval=False)
async def ingest_platform_metrics() -> dict:
    """落库桥：手动触发一次全量落库（罗盘/云图/抖店真返回 → 29 指标 + 同行标杆）。

    实时取 10 个核心端点 → 跑 29 抽取器（series 落整段历史/snap 落今日）→
    upsert mvp_daily_metric（sku_id='_SHOP_', platform='douyin'）+ mvp_industry_benchmark。
    需三平台 cookies 有效（先用 platform_auth_status 查）。日级 cron 也自动跑。

    Returns:
        {ok, result:{metric_rows_written, benchmark_rows_written, metrics_ok/total,
         fetch_errors, extract_errors, benchmark_errors}, trace} 或 {ok:false,error,hint}
    """
    return await _ingest_metrics_impl()
