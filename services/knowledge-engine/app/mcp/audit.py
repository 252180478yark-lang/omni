"""@tool_with_audit 装饰器（design doc §2.2）。

职责：
1. 审计：每次调用前插 mcp.tool_calls(status='pending')，结束后 update
   result/status/duration/error。
2. Human Gate（W3a T6 起真实现）：require_approval=True 时调
   human_gate.request_approval；DB poll 等批/驳/超时；超时记 rejected。

调用方式：
    from fastmcp import FastMCP
    from app.mcp.audit import tool_with_audit

    mcp = FastMCP("omni")

    @tool_with_audit(mcp, require_approval=False)
    async def list_skus(status: str | None = None) -> dict:
        ...

`tool_with_audit` 内部会调 `mcp.tool(...)` 把函数注册到 FastMCP。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from functools import wraps
from typing import Any, Awaitable, Callable

from fastmcp import FastMCP

from app.database import get_pool
from app.mcp import human_gate
from app.schemas.runtime_trace import EventType, RuntimeStatus
from app.services.runtime_trace import DatabaseTraceLedger, emit_audit_event

logger = logging.getLogger(__name__)

# 工具注册表：catalog/exec-any 端点用（tool_name → wrapper + 业务属性）。
# 在 tool_with_audit 注册时顺手维护，与 FastMCP 注册天然同步、零漂移。
TOOL_REGISTRY: dict[str, dict] = {}


def tool_with_audit(
    mcp: FastMCP,
    *,
    require_approval: bool = False,
    summary_fn: Callable[[dict], str] | None = None,
    timeout_seconds: int | None = None,
    **mcp_kwargs: Any,
) -> Callable[[Callable[..., Awaitable[dict]]], Callable[..., Awaitable[dict]]]:
    """把一个 async tool 函数包成"前置审计 → (gate) → 调用 → 后置审计"。

    Args:
        mcp: FastMCP 实例
        require_approval: 设 True 时在调函数前进 Human Gate（W3a T6 起为 DB poll 真实现）
        summary_fn: 给人看的摘要生成函数（用于 CLI list / 未来 /inbox 卡片）
        timeout_seconds: Gate 等批超时（None = 默认 3600）
        **mcp_kwargs: 透传给 `mcp.tool(...)`（如 description override 等）
    """

    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
        tool_name = fn.__name__

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict:
            pool = get_pool()
            args_dict = _bind_args(fn, args, kwargs)
            tool_call_id = str(uuid.uuid4())
            start = time.perf_counter()

            await pool.execute(
                """
                INSERT INTO mcp.tool_calls (id, tool_name, args, status, require_approval)
                VALUES ($1, $2, $3::jsonb, 'pending', $4)
                """,
                uuid.UUID(tool_call_id),
                tool_name,
                json.dumps(args_dict, ensure_ascii=False, default=str),
                require_approval,
            )
            await _emit_trace_safely(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                status=RuntimeStatus.RUNNING,
                event_type=EventType.STARTED,
            )

            if require_approval:
                summary = summary_fn(args_dict) if summary_fn else f"{tool_name}({args_dict})"
                decision = await human_gate.request_approval(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    summary=summary,
                    timeout_seconds=timeout_seconds or 21600,
                )
                if decision["decision"] != "approved":
                    # 区分"老板驳回" vs "超时未决"（§1.6：超时绝不等于驳回）
                    _err = (
                        "approval_timeout_expired"
                        if decision["decision"] == "expired"
                        else "rejected_by_user"
                    )
                    await _finalize_error(pool, tool_call_id, tool_name, _err, start)
                    return {
                        "ok": False,
                        "error": _err,
                        "note": decision.get("decision_note"),
                    }

            try:
                result = await fn(*args, **kwargs)
            except asyncio.CancelledError:
                # cancel 不吞：标 cancelled 后 re-raise，不破坏 task 取消语义
                await _finalize_error(pool, tool_call_id, tool_name, "cancelled", start)
                raise
            except BaseException as exc:  # 含 KeyboardInterrupt / SystemExit
                logger.exception("tool %s raised", tool_name)
                err_msg = f"{type(exc).__name__}: {exc}"
                await _finalize_error(pool, tool_call_id, tool_name, err_msg, start)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                # L0-3：异常被吞成 {ok:False} 返回前，再显式 error 级告警一次（带完整堆栈）。
                # 上面 logger.exception 已记一遍；这里专对"静默吞错→对外返成功结构"这条路径
                # 补一条明确的 server 日志告警，确保被吞的真异常不静默（向后兼容，返回结构不变）。
                logger.error(
                    "tool %s 异常被吞成 {ok:False} 返回（call_id=%s）: %s",
                    tool_name,
                    tool_call_id,
                    err_msg,
                    exc_info=True,
                )
                return {"ok": False, "error": err_msg, "hint": "tool 内部异常，看 server 日志定位"}

            duration_ms = int((time.perf_counter() - start) * 1000)
            await pool.execute(
                """
                UPDATE mcp.tool_calls
                SET status='completed', result=$1::jsonb, duration_ms=$2, completed_at=NOW()
                WHERE id=$3
                """,
                json.dumps(result, ensure_ascii=False, default=str),
                duration_ms,
                uuid.UUID(tool_call_id),
            )
            await _emit_trace_safely(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                status=RuntimeStatus.COMPLETED,
                event_type=EventType.COMPLETED,
                duration_ms=duration_ms,
            )
            return result

        # 关键：让 FastMCP 能反射出 fn 原签名生成 JSON schema
        # @functools.wraps 仅设 __wrapped__，不复制 __signature__；
        # 部分 FastMCP 版本直接读 __signature__，显式拷贝防止 schema 退化为 (*args, **kwargs)
        import inspect as _inspect
        wrapper.__signature__ = _inspect.signature(fn)  # type: ignore[attr-defined]
        wrapper.__annotations__ = dict(fn.__annotations__)

        # 维护全局注册表（catalog/exec-any 端点用）
        TOOL_REGISTRY[tool_name] = {
            "fn": wrapper,
            "require_approval": require_approval,
            "timeout_seconds": timeout_seconds,
        }

        # 注册到 FastMCP
        mcp.tool(**mcp_kwargs)(wrapper)
        return wrapper

    return decorator


async def _finalize_error(pool, tool_call_id: str, tool_name: str, error: str, start: float) -> None:
    duration_ms = int((time.perf_counter() - start) * 1000)
    await pool.execute(
        """
        UPDATE mcp.tool_calls
        SET status='error', error=$1, duration_ms=$2, completed_at=NOW()
        WHERE id=$3
        """,
        error,
        duration_ms,
        uuid.UUID(tool_call_id),
    )
    await _emit_trace_safely(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        status=RuntimeStatus.FAILED,
        event_type=EventType.FAILED,
        duration_ms=duration_ms,
    )


async def _emit_trace_safely(
    *,
    tool_call_id: str,
    tool_name: str,
    status: RuntimeStatus,
    event_type: EventType,
    duration_ms: int | None = None,
) -> None:
    """Trace failures never falsify tool execution; they are surfaced as a collector gap."""
    try:
        await emit_audit_event(
            DatabaseTraceLedger(),
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status=status,
            event_type=event_type,
            duration_ms=duration_ms,
        )
    except Exception:
        logger.warning("runtime trace append failed for MCP audit event", exc_info=True)


def _bind_args(fn: Callable[..., Any], args: tuple, kwargs: dict) -> dict:
    """把 (args, kwargs) 转成 {param_name: value} 用于审计。"""
    import inspect
    try:
        sig = inspect.signature(fn)
        bound = sig.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return {"_args": list(args), "_kwargs": kwargs}
