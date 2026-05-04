"""@tool_with_audit 装饰器（design doc §2.2）。

职责：
1. 审计：每次调用前插 mcp.tool_calls(status='pending')，结束后 update
   result/status/duration/error。
2. Human Gate（W2 起）：require_approval=True 时调 human_gate.request_approval；
   W1 当前为 stub，stub 抛出时 graceful 返回 `ToolError`，避免 LLM 拿到 500。

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

logger = logging.getLogger(__name__)


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
        require_approval: 设 True 时在调函数前进 Human Gate（W1 stub 抛 NotImplementedError）
        summary_fn: 给人看的摘要生成函数（用于 /inbox 卡片）；W1 暂存表里
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

            if require_approval:
                try:
                    summary = summary_fn(args_dict) if summary_fn else f"{tool_name}({args_dict})"
                    decision = await human_gate.request_approval(
                        tool_call_id=tool_call_id,
                        summary=summary,
                        timeout_seconds=timeout_seconds or 3600,
                    )
                    if decision["decision"] != "approved":
                        await _finalize_error(pool, tool_call_id, "rejected_by_user", start)
                        return {
                            "ok": False,
                            "error": "rejected_by_user",
                            "note": decision.get("decision_note"),
                        }
                except NotImplementedError as exc:
                    logger.warning("Human Gate stub hit (W1): %s", exc)
                    await _finalize_error(pool, tool_call_id, "human_gate_unavailable", start)
                    return {
                        "ok": False,
                        "error": "human_gate_unavailable",
                        "hint": "Human Gate 在 W1 未启用，所有 W1 tool 必须 require_approval=False",
                    }

            try:
                result = await fn(*args, **kwargs)
            except asyncio.CancelledError:
                # cancel 不吞：标 cancelled 后 re-raise，不破坏 task 取消语义
                await _finalize_error(pool, tool_call_id, "cancelled", start)
                raise
            except BaseException as exc:  # 含 KeyboardInterrupt / SystemExit
                logger.exception("tool %s raised", tool_name)
                err_msg = f"{type(exc).__name__}: {exc}"
                await _finalize_error(pool, tool_call_id, err_msg, start)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
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
            return result

        # 关键：让 FastMCP 能反射出 fn 原签名生成 JSON schema
        # @functools.wraps 仅设 __wrapped__，不复制 __signature__；
        # 部分 FastMCP 版本直接读 __signature__，显式拷贝防止 schema 退化为 (*args, **kwargs)
        import inspect as _inspect
        wrapper.__signature__ = _inspect.signature(fn)  # type: ignore[attr-defined]
        wrapper.__annotations__ = dict(fn.__annotations__)

        # 注册到 FastMCP
        mcp.tool(**mcp_kwargs)(wrapper)
        return wrapper

    return decorator


async def _finalize_error(pool, tool_call_id: str, error: str, start: float) -> None:
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


def _bind_args(fn: Callable[..., Any], args: tuple, kwargs: dict) -> dict:
    """把 (args, kwargs) 转成 {param_name: value} 用于审计。"""
    import inspect
    try:
        sig = inspect.signature(fn)
        bound = sig.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return {"_args": list(args), "_kwargs": kwargs}
