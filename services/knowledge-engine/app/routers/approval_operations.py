"""Immediate-202 API for recoverable human-approved operations."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.schemas.approval_operations import (
    ApprovalOperationCreate,
    ApprovalOperationError,
    ApprovalOperationStatus,
    RevokeRequest,
)
from app.services.approval_operations import (
    ApprovalOperationException,
    ApprovalOperationService,
    ApprovalPrincipal,
    identity_approver_principal,
    trusted_local_principal,
)


router = APIRouter(prefix="/api/v1/approval-operations", tags=["approval-operations"])


def get_approval_operation_service() -> ApprovalOperationService:
    return ApprovalOperationService()


_SERVICE_NONCES: dict[str, float] = {}
_SERVICE_NONCE_LOCK = asyncio.Lock()
_SERVICE_AUTH_WINDOW_SECONDS = 30


def _service_secret() -> bytes | None:
    path = os.getenv("OMNI_APPROVAL_SERVICE_SECRET_FILE", "").strip()
    if not path:
        return None
    try:
        value = Path(path).read_bytes()
    except OSError:
        return None
    return value if len(value) >= 32 else None


async def _service_principal(request: Request) -> ApprovalPrincipal | None:
    service_id = request.headers.get("x-omni-service-id", "")
    timestamp_text = request.headers.get("x-omni-timestamp", "")
    nonce = request.headers.get("x-omni-nonce", "")
    actor_id = request.headers.get("x-omni-actor-id", "")
    actor_role = request.headers.get("x-omni-actor-role", "")
    body_hash = request.headers.get("x-omni-body-sha256", "")
    supplied = request.headers.get("x-omni-signature", "")
    if service_id != "frontend" or not nonce or len(nonce) > 128:
        return None
    try:
        timestamp = int(timestamp_text)
    except ValueError:
        return None
    now = int(time.time())
    if abs(now - timestamp) > _SERVICE_AUTH_WINDOW_SECONDS:
        return None
    body = await request.body()
    actual_body_hash = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(actual_body_hash, body_hash):
        return None
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    actor = identity_approver_principal(actor_id, actor_role)
    if actor is None:
        return None
    canonical = "\n".join(
        (
            service_id,
            timestamp_text,
            nonce,
            request.method.upper(),
            target,
            body_hash,
            actor_id,
            actor_role.lower(),
        )
    ).encode("utf-8")
    secret = _service_secret()
    if secret is None:
        return None
    expected = hmac.new(secret, canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        return None
    async with _SERVICE_NONCE_LOCK:
        cutoff = now - _SERVICE_AUTH_WINDOW_SECONDS
        for old_nonce, seen_at in list(_SERVICE_NONCES.items()):
            if seen_at < cutoff:
                _SERVICE_NONCES.pop(old_nonce, None)
        if nonce in _SERVICE_NONCES:
            return None
        _SERVICE_NONCES[nonce] = float(now)
    return actor


async def get_approval_principal(request: Request) -> ApprovalPrincipal:
    """Resolve only server-injected or explicitly configured loopback identity."""

    injected = getattr(request.state, "approval_principal", None)
    if isinstance(injected, ApprovalPrincipal):
        return injected
    service = await _service_principal(request)
    if service is not None:
        return service
    client_host = request.client.host if request.client else ""
    if client_host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        local = trusted_local_principal()
        if local is not None:
            return local
    raise HTTPException(
        status_code=401,
        detail={"code": "authentication_required", "message": "Trusted approval authentication is required."},
    )


def _error(exc: ApprovalOperationException) -> JSONResponse:
    body = ApprovalOperationError(
        code=exc.code,
        message=str(exc),
        status=exc.status,
        retryable=exc.retryable,
        operation_id=exc.operation_id,
    )
    return JSONResponse(status_code=exc.status, content=body.model_dump(mode="json"))


@router.post("", status_code=202)
async def create_approval_operation(
    payload: ApprovalOperationCreate,
    service: ApprovalOperationService = Depends(get_approval_operation_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    try:
        accepted = await service.create(payload, principal)
    except ApprovalOperationException as exc:
        return _error(exc)
    return JSONResponse(
        status_code=202,
        headers={"Location": accepted.status_url},
        content=accepted.model_dump(mode="json"),
    )


@router.get("/{operation_id}", response_model=ApprovalOperationStatus)
async def get_approval_operation(
    operation_id: str,
    service: ApprovalOperationService = Depends(get_approval_operation_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    try:
        return await service.status(operation_id, principal)
    except ApprovalOperationException as exc:
        return _error(exc)


@router.post("/{operation_id}/revoke", response_model=ApprovalOperationStatus)
async def revoke_approval_operation(
    operation_id: str,
    payload: RevokeRequest,
    service: ApprovalOperationService = Depends(get_approval_operation_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    try:
        return await service.revoke(operation_id, payload.note, principal)
    except ApprovalOperationException as exc:
        return _error(exc)
