"""Owner-authenticated S4 issue and S5 candidate-plan APIs."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from app.routers.approval_operations import get_approval_principal
from app.schemas.system_graph import IntegrationPlanState, StrictModel
from app.services.approval_operations import ApprovalPrincipal
from app.services.system_graph.integration_plans import (
    IntegrationPlanService,
    PlanConflict,
    PlanItem,
    PlanStale,
    UnresolvedCriticalUnknown,
    create_candidate_plan,
    default_integration_plan_service,
    plan_summary,
)
from app.services.system_graph.issues import (
    IssueConflict,
    IssueStatus,
    IssueStore,
    default_issue_store,
)


router = APIRouter(prefix="/api/v1/system-graph", tags=["system-graph"])


class CreatePlanRequest(StrictModel):
    feature_id: str
    base_snapshot_id: str
    intent: str
    items: list[PlanItem] = Field(default_factory=list)


class UpdatePlanRequest(StrictModel):
    expected_revision: int
    current_snapshot_id: str
    items: list[PlanItem]


class RebasePlanRequest(StrictModel):
    expected_revision: int
    base_snapshot_id: str
    items: list[PlanItem] | None = None


class ArchivePlanRequest(StrictModel):
    expected_revision: int
    reason: str


class ConfirmPlanRequest(StrictModel):
    expected_revision: int
    current_snapshot_id: str
    request_id: str
    confirmed: Literal[True]


class TransitionIssueRequest(StrictModel):
    expected_revision: int
    status: IssueStatus
    reason: str = ""


def get_integration_plan_service() -> IntegrationPlanService:
    return default_integration_plan_service()


def get_issue_store() -> IssueStore:
    return default_issue_store()


def _require_plan_reader(principal: ApprovalPrincipal) -> None:
    if not principal.can("system_graph:plan:read"):
        raise HTTPException(
            status_code=403,
            detail={"code": "system_graph_plan_read_permission_required", "message": "Plan read permission is required."},
        )


def _require_plan_owner(principal: ApprovalPrincipal) -> None:
    if not principal.can("system_graph:plan"):
        raise HTTPException(
            status_code=403,
            detail={"code": "system_graph_plan_permission_required", "message": "Owner permission is required."},
        )


def _error(exc: Exception) -> JSONResponse:
    extra: dict[str, object] = {}
    if isinstance(exc, KeyError):
        status, code = 404, "plan_not_found"
    elif isinstance(exc, (PlanConflict, IssueConflict)):
        status, code = 409, "revision_conflict"
    elif isinstance(exc, PlanStale):
        status, code = 409, "plan_stale"
        if exc.revision is not None:
            extra["plan"] = exc.revision.model_dump(mode="json")
    elif isinstance(exc, UnresolvedCriticalUnknown):
        status, code = 409, "plan_not_impact_locked"
    else:
        status, code = 422, "invalid_plan_request"
    return JSONResponse(status_code=status, content={"code": code, "message": str(exc), **extra})


def _plan_payload(plan) -> dict[str, object]:
    return {"plan": plan.model_dump(mode="json"), "summary": plan_summary(plan), "product_write_performed": False}


@router.post("/integration-plans")
async def create_integration_plan(
    payload: CreatePlanRequest,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan = create_candidate_plan(service, **payload.model_dump(), actor_id=principal.principal_id)
    except (KeyError, PlanConflict, PlanStale, UnresolvedCriticalUnknown, ValueError) as exc:
        return _error(exc)
    return {
        **_plan_payload(plan),
        "side_effects": ["candidate_plan_revision_artifact"],
    }


@router.get("/integration-plans")
async def list_integration_plans(
    state: IntegrationPlanState | None = Query(default=None),
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_reader(principal)
    plans = service.list(state=state)
    return {
        "plans": [plan.model_dump(mode="json") for plan in plans],
        "summaries": {plan.plan_id: plan_summary(plan) for plan in plans},
        "product_write_performed": False,
    }


@router.get("/integration-plans/{plan_id}")
async def get_integration_plan(
    plan_id: str,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_reader(principal)
    try:
        plan = service.latest(plan_id)
    except KeyError as exc:
        return _error(exc)
    return _plan_payload(plan)


@router.patch("/integration-plans/{plan_id}")
async def update_integration_plan(
    plan_id: str,
    payload: UpdatePlanRequest,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan = service.patch(plan_id=plan_id, **payload.model_dump(), actor_id=principal.principal_id)
    except (KeyError, PlanConflict, PlanStale, UnresolvedCriticalUnknown, ValueError) as exc:
        return _error(exc)
    return {**_plan_payload(plan), "side_effects": ["candidate_plan_revision_artifact"]}


@router.post("/integration-plans/{plan_id}/rebase")
async def rebase_integration_plan(
    plan_id: str,
    payload: RebasePlanRequest,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan = service.rebase(plan_id=plan_id, **payload.model_dump(), actor_id=principal.principal_id)
    except (KeyError, PlanConflict, PlanStale, ValueError) as exc:
        return _error(exc)
    return {**_plan_payload(plan), "side_effects": ["candidate_plan_revision_artifact"]}


@router.post("/integration-plans/{plan_id}/archive")
async def archive_integration_plan(
    plan_id: str,
    payload: ArchivePlanRequest,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan = service.archive(plan_id=plan_id, **payload.model_dump(), actor_id=principal.principal_id)
    except (KeyError, PlanConflict, ValueError) as exc:
        return _error(exc)
    return {**_plan_payload(plan), "side_effects": ["candidate_plan_revision_artifact"]}


@router.post("/integration-plans/{plan_id}/confirm")
async def confirm_integration_plan(
    plan_id: str,
    payload: ConfirmPlanRequest,
    service: IntegrationPlanService = Depends(get_integration_plan_service),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        plan, impact_draft = service.confirm(
            plan_id=plan_id, **payload.model_dump(), actor_id=principal.principal_id
        )
    except (KeyError, PlanConflict, PlanStale, UnresolvedCriticalUnknown, ValueError) as exc:
        return _error(exc)
    return {
        **_plan_payload(plan),
        "impact_draft": impact_draft,
        "side_effects": ["candidate_plan_revision_artifact", "candidate_impact_draft_artifact"],
    }


@router.get("/issues")
async def list_system_graph_issues(
    status: IssueStatus | None = Query(default=None),
    code: str | None = Query(default=None),
    query: str = Query(default=""),
    store: IssueStore = Depends(get_issue_store),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_reader(principal)
    issues = store.list(status=status, code=code, query=query)
    return {"issues": [issue.model_dump(mode="json") for issue in issues]}


@router.post("/issues/{fingerprint}/transition")
async def transition_system_graph_issue(
    fingerprint: str,
    payload: TransitionIssueRequest,
    store: IssueStore = Depends(get_issue_store),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_owner(principal)
    try:
        issue = store.transition(
            fingerprint,
            expected_revision=payload.expected_revision,
            status=payload.status,
            actor=principal.principal_id,
            reason=payload.reason,
        )
    except (KeyError, IssueConflict, ValueError) as exc:
        return _error(exc)
    return {"issue": issue.model_dump(mode="json")}
