"""Authenticated S8 append/reconnect/replay API."""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.schemas.runtime_trace import RuntimeEventAppendResponse, RuntimeEventInput, RuntimeEventPage, RuntimeExecutionPage
from app.services.runtime_trace import DatabaseTraceLedger, TraceLedger

router = APIRouter(prefix="/api/v1/runtime-traces", tags=["runtime-traces"])


def get_trace_ledger() -> TraceLedger:
    return DatabaseTraceLedger()


def _token() -> str:
    path = os.getenv("OMNI_RUNTIME_TRACE_TOKEN_FILE", "").strip()
    if not path:
        raise HTTPException(status_code=503, detail={"code": "runtime_trace_auth_unconfigured"})
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        raise HTTPException(status_code=503, detail={"code": "runtime_trace_auth_unavailable"}) from None
    if len(value) < 24:
        raise HTTPException(status_code=503, detail={"code": "runtime_trace_auth_invalid"})
    return value


def require_trace_access(authorization: str | None = Header(default=None)) -> None:
    token = _token()
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not supplied or not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail={"code": "runtime_trace_auth_required"})


@router.get("/active", response_model=RuntimeExecutionPage, dependencies=[Depends(require_trace_access)])
async def list_active_runs(
    limit: int = Query(default=50, ge=1, le=200),
    ledger: TraceLedger = Depends(get_trace_ledger),
) -> RuntimeExecutionPage:
    return await ledger.active_runs(limit=limit)


@router.post("/{trace_id}/events", response_model=RuntimeEventAppendResponse, dependencies=[Depends(require_trace_access)])
async def append_runtime_event(trace_id: str, payload: RuntimeEventInput, ledger: TraceLedger = Depends(get_trace_ledger)) -> RuntimeEventAppendResponse:
    if trace_id != payload.trace_id:
        raise HTTPException(status_code=409, detail={"code": "trace_id_path_body_mismatch"})
    try:
        return await ledger.append(payload)
    except ValueError as exc:
        if str(exc) in {"runtime_event_id_conflict", "runtime_trace_identity_conflict", "runtime_span_identity_conflict"}:
            raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
        raise


@router.get("/{trace_id}/events", response_model=RuntimeEventPage, dependencies=[Depends(require_trace_access)])
async def list_runtime_events(
    trace_id: str, cursor: int = Query(default=0, ge=0), limit: int = Query(default=500, ge=1, le=2000),
    ledger: TraceLedger = Depends(get_trace_ledger),
) -> RuntimeEventPage:
    return await ledger.events(trace_id, cursor=cursor, limit=limit)


@router.get("/{trace_id}/replay", response_model=RuntimeEventPage, dependencies=[Depends(require_trace_access)])
async def replay_runtime_trace(
    trace_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=2000, ge=1, le=2000),
    ledger: TraceLedger = Depends(get_trace_ledger),
) -> RuntimeEventPage:
    return await ledger.events(trace_id, cursor=cursor, limit=limit)
