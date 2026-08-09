"""Immediate-202 API for recoverable human-approved operations."""

from __future__ import annotations

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
    trusted_local_principal,
)


router = APIRouter(prefix="/api/v1/approval-operations", tags=["approval-operations"])


def get_approval_operation_service() -> ApprovalOperationService:
    return ApprovalOperationService()


async def _service_principal(request: Request) -> ApprovalPrincipal | None:
    actor_id = request.headers.get("x-omni-actor-id", "")
    actor_role = request.headers.get("x-omni-actor-role", "")
    if actor_id != "local-owner" or actor_role.lower() != "owner":
        return None
    return trusted_local_principal()


async def get_approval_principal(request: Request) -> ApprovalPrincipal:
    """Resolve an injected test principal or the fixed local owner."""

    injected = getattr(request.state, "approval_principal", None)
    if isinstance(injected, ApprovalPrincipal):
        return injected
    local = trusted_local_principal()
    if local is not None:
        return local
    service = await _service_principal(request)
    if service is not None:
        return service
    return trusted_local_principal()


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
