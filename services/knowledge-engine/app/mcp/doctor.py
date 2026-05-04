"""omni MCP 健康检查（design doc §6.3 调试三件套之一）。

用法：
    # CLI（容器内）
    docker exec omni-knowledge-engine python -m app.mcp.doctor
    # 退出码 0 = 全绿；1 = 有红

    # 启动期（main.py lifespan 内）
    from app.mcp.doctor import run_at_startup
    await run_at_startup()  # 仅日志，不抛
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field

import httpx

from app.config import settings
from app.database import init_pool, close_pool, get_pool

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_green(self) -> bool:
        return all(c.ok for c in self.checks)

    def render(self) -> str:
        lines = ["omni MCP doctor 报告"]
        for c in self.checks:
            mark = "OK  " if c.ok else "FAIL"
            lines.append(f"  [{mark}] {c.name}{(': ' + c.detail) if c.detail else ''}")
        lines.append("")
        lines.append("结论：全绿 ✓" if self.all_green else "结论：存在 FAIL ✗")
        return "\n".join(lines)


async def _check_db_pool(report: DoctorReport) -> None:
    try:
        pool = get_pool()
        v = await pool.fetchval("SELECT 1")
        report.checks.append(CheckResult("DB pool", v == 1))
    except Exception as exc:
        report.checks.append(CheckResult("DB pool", False, str(exc)))


async def _check_mcp_schema(report: DoctorReport) -> None:
    try:
        pool = get_pool()
        n = await pool.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables"
            " WHERE table_schema='mcp' AND table_name IN ('tool_calls','human_gates')"
        )
        ok = n == 2
        report.checks.append(CheckResult("mcp schema tables", ok, f"found {n}/2"))
    except Exception as exc:
        report.checks.append(CheckResult("mcp schema tables", False, str(exc)))


def _check_yaml(report: DoctorReport) -> None:
    try:
        from app.mcp.model_config import _load_yaml
        raw = _load_yaml()
        ok = "__default__" in raw
        report.checks.append(CheckResult("tool_models.yaml", ok, f"keys={list(raw.keys())[:5]}"))
    except Exception as exc:
        report.checks.append(CheckResult("tool_models.yaml", False, str(exc)))


async def _check_tools_registered(report: DoctorReport) -> None:
    """FastMCP 3.x: mcp.list_tools() 是 async coroutine，必须 await。"""
    try:
        from app.mcp.server import mcp
        tools = await mcp.list_tools()
        # W1 5 + W2 5 = 10
        wanted = {
            # W1
            "list_skus", "get_sku", "search_kb", "list_kbs", "list_briefs",
            # W2
            "query_costs", "compute_margin",
            "generate_brief", "generate_image", "generate_video",
        }
        names = {getattr(t, "name", str(t)) for t in tools}
        missing = wanted - names
        n = len(wanted)
        report.checks.append(CheckResult(
            f"{n} tools registered", not missing,
            f"missing={sorted(missing)}" if missing else f"all {n} ok",
        ))
    except Exception as exc:
        report.checks.append(CheckResult("tools registered", False, str(exc)))


async def _check_mcp_http(report: DoctorReport) -> None:
    url = f"http://localhost:{settings.service_port}/mcp/"
    try:
        async with httpx.AsyncClient(timeout=5.0) as cli:
            # 用 initialize JSON-RPC 探活；MCP 协议要求 Accept SSE
            r = await cli.post(
                url,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "doctor", "version": "0.0"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            ok = r.status_code in (200, 202)
            report.checks.append(CheckResult("/mcp HTTP", ok, f"status={r.status_code}"))
    except Exception as exc:
        report.checks.append(CheckResult("/mcp HTTP", False, str(exc)))


async def run(*, skip_http: bool = False) -> DoctorReport:
    report = DoctorReport()
    await _check_db_pool(report)
    await _check_mcp_schema(report)
    _check_yaml(report)
    await _check_tools_registered(report)
    if not skip_http:
        await _check_mcp_http(report)
    return report


async def _deferred_http_check(delay: float = 2.0) -> None:
    """等 uvicorn 完成端口绑定后再探 /mcp HTTP。"""
    await asyncio.sleep(delay)
    report = DoctorReport()
    await _check_mcp_http(report)
    c = report.checks[0]
    if c.ok:
        logger.info("[doctor] %s OK %s", c.name, c.detail)
    else:
        logger.warning("[doctor] %s FAIL %s", c.name, c.detail)


async def run_at_startup() -> None:
    """启动期非阻塞自检：只 logger.warning 不抛。

    前 4 项（DB / schema / yaml / tools）在 lifespan 内同步检查；
    /mcp HTTP 探针通过后台任务延迟 2 s 执行（uvicorn 端口绑定完成后）。
    """
    try:
        report = await run(skip_http=True)
        for c in report.checks:
            if c.ok:
                logger.info("[doctor] %s OK %s", c.name, c.detail)
            else:
                logger.warning("[doctor] %s FAIL %s", c.name, c.detail)
        # HTTP 探针延迟触发，不阻塞 lifespan
        asyncio.create_task(_deferred_http_check(delay=2.0))
    except Exception:
        logger.warning("doctor self-check failed", exc_info=True)


async def _cli() -> int:
    await init_pool()
    try:
        report = await run()
    finally:
        await close_pool()
    print(report.render())
    return 0 if report.all_green else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli()))
