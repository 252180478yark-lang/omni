"""S5 local-owner API for candidate integration-plan revisions.

The API owns candidate-plan artifacts only.  It never writes product code,
business data, a shared database, or an impact contract.  Confirmation merely
returns an in-memory impact draft for a later, separately governed adoption.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.routers.approval_operations import get_approval_principal
from app.schemas.system_graph import StrictModel
from app.services.approval_operations import ApprovalPrincipal
from app.services.system_graph.integration_plans import (
    IntegrationPlanService,
    PlanConflict,
    PlanItem,
    PlanStale,
    UnresolvedCriticalUnknown,
    create_candidate_plan,
    default_integration_plan_service,
)


router = APIRouter(prefix="/api/v1/system-graph/integration-plans", tags=["system-graph"])


class CreatePlanRequest(StrictModel):
    feature_id: str
    base_snapshot_id: str
    intent: str
    items: list[PlanItem]


class UpdatePlanRequest(StrictModel):
    expected_revision: int
    current_snapshot_id: str
    items: list[PlanItem]


class ConfirmPlanRequest(StrictModel):
    expected_revision: int
    current_snapshot_id: str
    request_id: str
    confirmed: Literal[True]


def get_integration_plan_service() -> IntegrationPlanService:
    return default_integration_plan_service()


def _require_plan_owner(principal: ApprovalPrincipal) -> None:
    if not principal.can("system_graph:plan"):
        raise HTTPException(
            status_code=403,
            detail={"code": "system_graph_plan_permission_required", "message": "Owner permission is required."},
        )


def _error(exc: Exception) -> JSONResponse:
    if isinstance(exc, KeyError):
        status, code = 404, "plan_not_found"
    elif isinstance(exc, PlanConflict):
        status, code = 409, "plan_revision_conflict"
    elif isinstance(exc, (PlanStale, UnresolvedCriticalUnknown)):
        status, code = 409, "plan_not_impact_locked"
    else:
        status, code = 422, "invalid_plan_request"
    return JSONResponse(status_code=status, content={"code": code, "message": str(exc)})


@router.post("")
async def create_integration_plan(
    payload: CreatePlanRequest,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan = create_candidate_plan(service, **payload.model_dump())
    except (KeyError, PlanConflict, PlanStale, UnresolvedCriticalUnknown, ValueError) as exc:
        return _error(exc)
    return {
        "plan": plan.model_dump(mode="json"),
        "side_effects": ["candidate_plan_revision_artifact"],
        "product_write_performed": False,
    }


@router.get("/{plan_id}")
async def get_integration_plan(
    plan_id: str,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan = service.latest(plan_id)
    except KeyError as exc:
        return _error(exc)
    return {"plan": plan.model_dump(mode="json"), "product_write_performed": False}


@router.patch("/{plan_id}")
async def update_integration_plan(
    plan_id: str,
    payload: UpdatePlanRequest,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan = service.patch(plan_id=plan_id, **payload.model_dump())
    except (KeyError, PlanConflict, PlanStale, UnresolvedCriticalUnknown, ValueError) as exc:
        return _error(exc)
    return {
        "plan": plan.model_dump(mode="json"),
        "side_effects": ["candidate_plan_revision_artifact"],
        "product_write_performed": False,
    }


@router.post("/{plan_id}/confirm")
async def confirm_integration_plan(
    plan_id: str,
    payload: ConfirmPlanRequest,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan, impact_draft = service.confirm(plan_id=plan_id, **payload.model_dump())
    except (KeyError, PlanConflict, PlanStale, UnresolvedCriticalUnknown, ValueError) as exc:
        return _error(exc)
    return {
        "plan": plan.model_dump(mode="json"),
        "impact_draft": impact_draft,
        "side_effects": ["candidate_plan_revision_artifact"],
        "product_write_performed": False,
    }
