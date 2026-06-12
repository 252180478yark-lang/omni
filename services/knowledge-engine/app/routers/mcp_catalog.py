"""MCP 工具目录 + 通用执行端点（客户端「工具全集」面板的数据源与执行通路）。

GET  /api/v1/mcp/catalog/tools  全量工具元数据（名称/描述/参数 schema/是否走 Gate）
POST /api/v1/mcp/catalog/exec   按名执行任意已注册 tool（白名单=注册表本身；
                                require_approval 的工具照走 Human Gate——审计装饰器在 wrapper 里）

工具模型配置（桌面「模型配置」面板后端，2026-06-12）：
GET    /api/v1/mcp/catalog/tool-models             合并后生效配置（base+local overlay）+ hub providers
PUT    /api/v1/mcp/catalog/tool-models             写 local overlay 覆盖某 tool 的 provider/model（热生效）
DELETE /api/v1/mcp/catalog/tool-models/{tool_name} 删 overlay key，恢复 base
base `config/tool_models.yaml` 是老板手写注释的命门文件，**绝不重写**——一切运行时
改动只进 `config/tool_models.local.yaml`（gitignore，mtime 热生效不用重启）。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import settings

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


# ---------------------------------------------------------------------------
# 工具模型配置（local overlay；base yaml 老板注释绝不动）
# ---------------------------------------------------------------------------

_EFFECTIVE_KEYS = ("provider", "model", "temperature", "max_tokens")


def _effective_entry(name: str, overridden: bool) -> dict[str, Any]:
    """合并后生效值（只透出面板关心的 4 个字段 + overridden 标记）。"""
    from app.mcp.model_config import get_model_for_tool

    cfg = get_model_for_tool(name)
    out: dict[str, Any] = {"name": name, "overridden": overridden}
    for k in _EFFECTIVE_KEYS:
        if cfg.get(k) is not None:
            out[k] = cfg[k]
    return out


async def _fetch_hub_providers() -> tuple[list[dict[str, Any]], str | None]:
    """从 ai-provider-hub 拉 providers 状态；失败返 ([], warning) 不挂。"""
    url = f"{settings.ai_provider_hub_url.rstrip('/')}/api/v1/ai/providers"
    try:
        async with httpx.AsyncClient(timeout=5.0) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            raw = (r.json() or {}).get("providers") or {}
        providers = [
            {
                "name": name,
                "api_key_set": bool(info.get("api_key_set")),
                "default_chat_model": info.get("default_chat_model") or "",
            }
            for name, info in raw.items()
            if isinstance(info, dict)
        ]
        return providers, None
    except Exception as exc:
        logger.warning("拉 hub providers 失败：%s", exc)
        return [], f"ai-provider-hub 不可达（{type(exc).__name__}），providers 留空、provider 校验跳过"


@router.get("/tool-models")
async def list_tool_models() -> dict:
    """工具模型配置面板数据源：合并后生效值 + __default__ + hub providers。

    只列 LLM 类（base/local 里有 keyed 条目的）；__default__ 单独给。
    """
    from app.mcp import model_config as mc

    base = mc._load_yaml()
    local = mc.load_local_overrides()
    keyed_names = sorted(
        ({k for k in base if k != "__default__" and isinstance(base[k], dict)} | set(local))
    )
    tools = [_effective_entry(name, overridden=name in local) for name in keyed_names]

    default_raw = base.get("__default__") or {}
    default = {k: default_raw[k] for k in _EFFECTIVE_KEYS if default_raw.get(k) is not None}

    providers, warning = await _fetch_hub_providers()
    out: dict[str, Any] = {"ok": True, "tools": tools, "default": default, "providers": providers}
    if warning:
        out["warning"] = warning
    return out


class ToolModelUpdate(BaseModel):
    tool_name: str
    provider: str
    model: str
    temperature: float | None = None
    max_tokens: int | None = None


@router.put("/tool-models")
async def put_tool_model(payload: ToolModelUpdate) -> Any:
    """改某 tool 的模型（写 local overlay 该 key，base yaml 不动；mtime 热生效）。"""
    from app.mcp import model_config as mc

    tool_name = payload.tool_name.strip()
    provider = payload.provider.strip()
    model = payload.model.strip()
    if not tool_name or not provider or not model:
        return JSONResponse(status_code=422, content={
            "ok": False, "error": "bad_args",
            "hint": "tool_name / provider / model 都不能为空",
        })

    # provider 校验：在 hub providers 里且 api_key_set；hub 拉不到时跳过放行
    providers, warning = await _fetch_hub_providers()
    if providers:
        by_name = {p["name"]: p for p in providers}
        if provider not in by_name:
            return JSONResponse(status_code=422, content={
                "ok": False, "error": f"unknown_provider: {provider}",
                "hint": f"hub 可用 providers：{sorted(by_name)}",
            })
        if not by_name[provider]["api_key_set"]:
            return JSONResponse(status_code=422, content={
                "ok": False, "error": f"provider_key_missing: {provider}",
                "hint": "该 provider 在 hub 未配 api key，切过去会调不通；先配 key 再切",
            })

    cfg: dict[str, Any] = {"provider": provider, "model": model}
    if payload.temperature is not None:
        cfg["temperature"] = payload.temperature
    if payload.max_tokens is not None:
        cfg["max_tokens"] = payload.max_tokens
    mc.set_local_override(tool_name, cfg)

    out: dict[str, Any] = {
        "ok": True,
        "effective": _effective_entry(tool_name, overridden=True),
    }
    if warning:
        out["warning"] = warning
    return out


@router.delete("/tool-models/{tool_name}")
async def delete_tool_model(tool_name: str) -> dict:
    """删某 tool 的 local override（恢复 base yaml 生效值）。"""
    from app.mcp import model_config as mc

    removed = mc.remove_local_override(tool_name)
    return {
        "ok": True,
        "removed": removed,
        "effective": _effective_entry(tool_name, overridden=False),
    }
