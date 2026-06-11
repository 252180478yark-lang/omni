"""MCP 工具目录 + 通用执行端点（客户端「工具全集」面板的数据源与执行通路）。

GET  /api/v1/mcp/catalog/tools  全量工具元数据（名称/描述/参数 schema/是否走 Gate）
POST /api/v1/mcp/catalog/exec   按名执行任意已注册 tool（白名单=注册表本身；
                                require_approval 的工具照走 Human Gate——审计装饰器在 wrapper 里）
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mcp/catalog", tags=["mcp-catalog"])


@router.get("/tools")
async def list_tool_catalog() -> dict:
    """全量工具目录。新 tool 上线（@tool_with_audit 注册）即自动出现，前端零维护。"""
    from app.mcp.audit import TOOL_REGISTRY
    from app.mcp.server import mcp

    tools = await mcp.list_tools()
    out = []
    for t in tools:
        reg = TOOL_REGISTRY.get(t.name, {})
        # FastMCP 3.x Tool 对象：schema 在 .parameters；MCP 协议层 to_mcp_tool().inputSchema 也有
        schema = getattr(t, "parameters", None) or getattr(t, "inputSchema", None) or {}
        out.append({
            "name": t.name,
            "description": t.description or "",
            "input_schema": schema,
            "require_approval": bool(reg.get("require_approval", False)),
        })
    out.sort(key=lambda x: x["name"])
    return {"ok": True, "count": len(out), "tools": out}


class ExecRequest(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


@router.post("/exec")
async def exec_tool(payload: ExecRequest) -> Any:
    """按名执行任意已注册 tool。

    - 白名单 = TOOL_REGISTRY（只有 @tool_with_audit 注册过的能调）
    - 审计/trace/Human Gate 都在 wrapper 里，本端点不绕过任何护栏
    - 参数错误（TypeError）返 ok=False 带 hint，不 500
    """
    from app.mcp.audit import TOOL_REGISTRY

    reg = TOOL_REGISTRY.get(payload.tool_name)
    if not reg:
        return JSONResponse(status_code=404, content={
            "ok": False,
            "error": f"unknown_tool: {payload.tool_name}",
            "hint": "GET /api/v1/mcp/catalog/tools 看可用清单",
        })
    import inspect

    fn = reg["fn"]
    args = payload.args or {}

    # 提前验证参数名：audit wrapper 会把 TypeError 吞成 ok=False 200，
    # 我们在进 wrapper 之前先用 bind 检验，让参数错误能返回 422。
    try:
        sig = inspect.signature(fn)
        sig.bind(**args)
    except TypeError as exc:
        return JSONResponse(status_code=422, content={
            "ok": False,
            "error": f"bad_args: {exc}",
            "hint": "对照 catalog 里该工具的 input_schema 检查参数名/类型",
        })

    try:
        return await fn(**args)
    except Exception as exc:
        logger.exception("catalog exec %s 异常", payload.tool_name)
        return JSONResponse(status_code=500, content={
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        })
