"""Dedicated non-blocking audit decorator for human-approved MCP tools.

The ordinary audit decorator remains the owner of non-gated tools. This module
owns only the R3 ``request -> pending -> approve -> worker resume`` path so its
security and persistence rules can evolve without changing that shared path.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
import uuid
from contextvars import ContextVar
from functools import wraps
from typing import Any, Awaitable, Callable

from fastmcp import FastMCP

from app.database import get_pool
from app.mcp import human_gate
from app.mcp.audit import TOOL_REGISTRY
from app.schemas.approval_operations import ApprovalOperationCreate, IdempotencyStrategy
from app.services.approval_operations import (
    ApprovalOperationException,
    ApprovalOperationService,
    _bounded_json,
    freeze_input,
    knowledge_engine_requester_principal,
    redact_payload,
    sanitize_text,
)
from app.workers.approval_operations import HANDLERS, HandlerRegistration


logger = logging.getLogger(__name__)
_CURRENT_TOOL_CALL_ID: ContextVar[str | None] = ContextVar(
    "current_approved_tool_call_id", default=None
)


def get_current_tool_call_id() -> str | None:
    """Return the authoritative audit UUID only inside an approved tool body."""

    return _CURRENT_TOOL_CALL_ID.get()


def _legacy_blocking_enabled() -> bool:
    return os.getenv("OMNI_LEGACY_BLOCKING_APPROVAL", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bind_args(
    fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return {"_args": list(args), "_kwargs": kwargs}


async def _finalize_error(
    pool: Any, tool_call_id: str, code: str, started: float
) -> None:
    await pool.execute(
        """
        UPDATE mcp.tool_calls
           SET status='error', error=$1, duration_ms=$2, completed_at=NOW()
         WHERE id=$3
        """,
        code,
        int((time.perf_counter() - started) * 1000),
        uuid.UUID(tool_call_id),
    )


async def _record_rejected_input(
    pool: Any,
    tool_call_id: str,
    tool_name: str,
    code: str,
    started: float,
) -> None:
    """Persist only a bounded placeholder after pre-write validation fails."""

    await pool.execute(
        """
        INSERT INTO mcp.tool_calls
            (id, tool_name, args, status, require_approval,
             error, duration_ms, completed_at)
        VALUES ($1, $2, $3::jsonb, 'error', TRUE, $4, $5, NOW())
        """,
        uuid.UUID(tool_call_id),
        tool_name,
        json.dumps({"input_rejected": True, "code": code}, separators=(",", ":")),
        code,
        int((time.perf_counter() - started) * 1000),
    )


def approval_tool_with_audit(
    mcp: FastMCP,
    *,
    summary_fn: Callable[[dict[str, Any]], str] | None = None,
    timeout_seconds: int | None = None,
    **mcp_kwargs: Any,
) -> Callable[[Callable[..., Awaitable[dict]]], Callable[..., Awaitable[dict]]]:
    """Register one R3 tool with immediate pending response and durable resume."""

    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
        tool_name = fn.__name__
        handler_name = f"mcp.{tool_name}"

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict:
            pool = get_pool()
            tool_call_id = str(uuid.uuid4())
            started = time.perf_counter()
            raw_args = _bind_args(fn, args, kwargs)

            # Freeze before the first audit/operation write and before summary
            # rendering. Rejected credentials therefore never reach durable
            # storage, logs, notifications, or human-readable text.
            try:
                frozen_args = freeze_input(raw_args)
            except ApprovalOperationException as exc:
                await _record_rejected_input(
                    pool, tool_call_id, tool_name, exc.code, started
                )
                return {"ok": False, "error": exc.code, "retryable": exc.retryable}

            await pool.execute(
                """
                INSERT INTO mcp.tool_calls
                    (id, tool_name, args, status, require_approval)
                VALUES ($1, $2, $3::jsonb, 'pending', TRUE)
                """,
                uuid.UUID(tool_call_id),
                tool_name,
                json.dumps(frozen_args, ensure_ascii=False, separators=(",", ":")),
            )
            try:
                summary = sanitize_text(
                    str(
                        summary_fn(frozen_args)
                        if summary_fn
                        else f"{tool_name}({frozen_args})"
                    )
                )
            except Exception as exc:
                logger.warning(
                    "approval summary failed tool=%s exception_type=%s",
                    tool_name,
                    type(exc).__name__,
                )
                await _finalize_error(
                    pool, tool_call_id, "approval_summary_failed", started
                )
                return {
                    "ok": False,
                    "error": "approval_summary_failed",
                    "retryable": False,
                }

            if not _legacy_blocking_enabled():
                principal = knowledge_engine_requester_principal()
                if principal is None:
                    await _finalize_error(
                        pool,
                        tool_call_id,
                        "approval_requester_not_configured",
                        started,
                    )
                    return {
                        "ok": False,
                        "error": "approval_requester_not_configured",
                        "retryable": False,
                    }
                try:
                    accepted = await ApprovalOperationService(
                        principal=principal
                    ).create(
                        ApprovalOperationCreate(
                            request_id=f"mcp-{tool_call_id}",
                            requested_by=principal.principal_id,
                            permission_snapshot={"roles": [], "scopes": []},
                            trace_id=tool_call_id,
                            handler=handler_name,
                            summary=summary,
                            payload=frozen_args,
                            target={
                                "kind": "mcp_tool",
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                            },
                            idempotency_strategy=IdempotencyStrategy.MANUAL_RECONCILIATION,
                            expires_in_seconds=max(
                                30, min(timeout_seconds or 21600, 604800)
                            ),
                        )
                    )
                except ApprovalOperationException as exc:
                    await _finalize_error(pool, tool_call_id, exc.code, started)
                    return {"ok": False, "error": exc.code, "retryable": exc.retryable}
                except Exception as exc:
                    logger.warning(
                        "approval enqueue failed tool=%s exception_type=%s",
                        tool_name,
                        type(exc).__name__,
                    )
                    await _finalize_error(
                        pool, tool_call_id, "approval_enqueue_failed", started
                    )
                    return {
                        "ok": False,
                        "error": "approval_enqueue_failed",
                        "retryable": True,
                    }
                return {
                    "ok": True,
                    "status": "pending_approval",
                    "operation_id": accepted.operation_id,
                    "gate_id": accepted.gate_id,
                    "status_url": accepted.status_url,
                    "expires_at": accepted.expires_at.isoformat(),
                }

            logger.warning(
                "legacy blocking approval compatibility enabled for tool=%s", tool_name
            )
            decision = await human_gate.request_approval(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                summary=summary,
                timeout_seconds=timeout_seconds or 21600,
            )
            if decision["decision"] != "approved":
                code = (
                    "approval_timeout_expired"
                    if decision["decision"] == "expired"
                    else "rejected_by_user"
                )
                await _finalize_error(pool, tool_call_id, code, started)
                return {
                    "ok": False,
                    "error": code,
                    "note": sanitize_text(str(decision.get("decision_note") or "")),
                }

            context_token = _CURRENT_TOOL_CALL_ID.set(tool_call_id)
            try:
                try:
                    result = await fn(*args, **kwargs)
                except asyncio.CancelledError:
                    await _finalize_error(pool, tool_call_id, "cancelled", started)
                    raise
                except BaseException as exc:
                    code = f"approved_effect_failed:{type(exc).__name__}"
                    await _finalize_error(pool, tool_call_id, code, started)
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    logger.error(
                        "approved tool failed tool=%s exception_type=%s",
                        tool_name,
                        type(exc).__name__,
                    )
                    return {"ok": False, "error": "approved_effect_failed"}
            finally:
                _CURRENT_TOOL_CALL_ID.reset(context_token)

            try:
                persisted_result = _bounded_json(redact_payload(_bounded_json(result)))
            except ApprovalOperationException as exc:
                persisted_result = {
                    "result_recorded": False,
                    "code": "approved_result_not_persistable",
                    "validation_code": exc.code,
                }
            await pool.execute(
                """
                UPDATE mcp.tool_calls
                   SET status='completed', result=$1::jsonb, duration_ms=$2,
                       completed_at=NOW()
                 WHERE id=$3
                """,
                json.dumps(persisted_result, ensure_ascii=False, separators=(",", ":")),
                int((time.perf_counter() - started) * 1000),
                uuid.UUID(tool_call_id),
            )
            return result

        wrapper.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
        wrapper.__annotations__ = dict(fn.__annotations__)

        async def resume_approved_tool(
            payload: dict[str, Any], target: dict[str, Any], operation_id: str
        ) -> dict[str, Any]:
            if target.get("kind") != "mcp_tool" or target.get("tool_name") != tool_name:
                raise ValueError("approval target does not match registered MCP tool")
            resumed_tool_call_id = str(target.get("tool_call_id", ""))
            try:
                tool_call_uuid = uuid.UUID(resumed_tool_call_id)
            except ValueError as exc:
                raise ValueError("approval target has an invalid tool-call id") from exc

            resumed_at = time.perf_counter()
            context_token = _CURRENT_TOOL_CALL_ID.set(resumed_tool_call_id)
            try:
                try:
                    result = await fn(**payload)
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:
                    await get_pool().execute(
                        """
                        UPDATE mcp.tool_calls
                           SET status='error', error=$1, duration_ms=$2,
                               completed_at=NOW()
                         WHERE id=$3
                        """,
                        f"approved_effect_failed:{type(exc).__name__}",
                        int((time.perf_counter() - resumed_at) * 1000),
                        tool_call_uuid,
                    )
                    raise
            finally:
                _CURRENT_TOOL_CALL_ID.reset(context_token)

            await get_pool().execute(
                """
                UPDATE mcp.tool_calls
                   SET status='completed', result=$1::jsonb, duration_ms=$2,
                       completed_at=NOW()
                 WHERE id=$3
                """,
                json.dumps(
                    {
                        "approval_operation_id": operation_id,
                        "result_recorded_on_approval_operation": True,
                    }
                ),
                int((time.perf_counter() - resumed_at) * 1000),
                tool_call_uuid,
            )
            return result

        if handler_name in HANDLERS:
            raise ValueError(f"approval handler already registered: {handler_name}")
        HANDLERS[handler_name] = HandlerRegistration(
            resume_approved_tool, IdempotencyStrategy.MANUAL_RECONCILIATION
        )
        TOOL_REGISTRY[tool_name] = {
            "fn": wrapper,
            "require_approval": True,
            "timeout_seconds": timeout_seconds,
        }
        mcp.tool(**mcp_kwargs)(wrapper)
        return wrapper

    return decorator
