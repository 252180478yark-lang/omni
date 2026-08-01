"""S8 trace propagation for Scout HTTP handlers and outbound source requests."""

from __future__ import annotations

import os
import re
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from starlette.middleware.base import BaseHTTPMiddleware


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$")
_context: ContextVar["ScoutTraceContext | None"] = ContextVar("scout_trace_context", default=None)


@dataclass(frozen=True)
class ScoutTraceContext:
    trace_id: str
    execution_id: str
    span_id: str
    parent_span_id: str | None = None
    correlation_id: str | None = None
    session_id: str | None = None


def _safe(value: str | None) -> str | None:
    return value if value and _IDENTIFIER.fullmatch(value) else None


def context_from_headers(headers: Any) -> ScoutTraceContext:
    trace_id = _safe(headers.get("x-omni-trace-id")) or f"trace:{uuid.uuid4().hex}"
    execution_id = _safe(headers.get("x-omni-execution-id")) or trace_id
    return ScoutTraceContext(
        trace_id=trace_id,
        execution_id=execution_id,
        span_id=f"scout:{uuid.uuid4().hex}",
        parent_span_id=_safe(headers.get("x-omni-span-id")) or _safe(headers.get("x-omni-parent-span-id")),
        correlation_id=_safe(headers.get("x-omni-correlation-id")),
        session_id=_safe(headers.get("x-omni-session-id")),
    )


def current_context() -> ScoutTraceContext | None:
    return _context.get()


def outbound_trace_headers() -> dict[str, str]:
    context = current_context()
    if context is None:
        return {}
    return {
        "X-Omni-Trace-Id": context.trace_id,
        "X-Omni-Execution-Id": context.execution_id,
        "X-Omni-Parent-Span-Id": context.span_id,
        **({"X-Omni-Correlation-Id": context.correlation_id} if context.correlation_id else {}),
        **({"X-Omni-Session-Id": context.session_id} if context.session_id else {}),
    }


async def publish_trace_events(
    context: ScoutTraceContext,
    *,
    method: str,
    route: str,
    status_code: int,
    duration_ms: int,
    started_at: datetime,
    failed: bool,
) -> bool:
    base = os.getenv("OMNI_KE_URL", "").rstrip("/")
    token_path = os.getenv("OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE", "").strip()
    if not base or not token_path:
        return False
    try:
        token = Path(token_path).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if len(token) < 24:
        return False
    node_id = f"rest_operation:{method}:{route}"
    common = {
        "source": "scout.http", "trace_id": context.trace_id, "execution_id": context.execution_id,
        "span_id": context.span_id, "parent_span_id": context.parent_span_id,
        "correlation_id": context.correlation_id, "session_id": context.session_id,
        "span_kind": "http", "node_id": node_id,
        "read_write": "read" if method in {"GET", "HEAD", "OPTIONS"} else "write",
    }
    terminal_type = "failed" if failed else "completed"
    encoded_trace_id = quote(context.trace_id, safe="")
    payloads = [
        {**common, "event_id": f"{context.span_id}:started", "event_type": "started", "status": "running", "observed_at": started_at.isoformat(), "payload": {"method": method, "route": route}},
        {**common, "event_id": f"{context.span_id}:{terminal_type}", "event_type": terminal_type, "status": terminal_type, "observed_at": datetime.now(timezone.utc).isoformat(), "payload": {"method": method, "route": route, "status_code": status_code, "duration_ms": duration_ms}},
    ]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for payload in payloads:
                response = await client.post(
                    f"{base}/api/v1/runtime-traces/{encoded_trace_id}/events",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code not in {200, 201}:
                    return False
        return True
    except (httpx.HTTPError, ValueError):
        return False


class ScoutTraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        context = context_from_headers(request.headers)
        explicit = bool(request.headers.get("x-omni-trace-id") or request.headers.get("traceparent"))
        token: Token[ScoutTraceContext | None] = _context.set(context)
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        response = None
        failure = False
        try:
            response = await call_next(request)
        except Exception:
            failure = True
            raise
        finally:
            published = True
            if explicit:
                route = getattr(request.scope.get("route"), "path", None) or request.url.path
                published = await publish_trace_events(
                    context, method=request.method, route=route,
                    status_code=getattr(response, "status_code", 500),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    started_at=started_at, failed=failure,
                )
            _context.reset(token)
        response.headers["X-Omni-Trace-Id"] = context.trace_id
        response.headers["X-Omni-Execution-Id"] = context.execution_id
        response.headers["X-Omni-Span-Id"] = context.span_id
        if explicit and not published:
            response.headers["X-Omni-Trace-Gap"] = "runtime_trace_append_failed"
        return response
