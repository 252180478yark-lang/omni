"""Authenticated system graph, issue, planning, and snapshot APIs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from app.routers.approval_operations import get_approval_principal
from app.schemas.system_graph import (
    GraphDiff,
    GraphPage,
    GraphRefreshRecord,
    GraphRefreshRequest,
    GraphSearchPage,
    GraphSnapshot,
    IntegrationPlanState,
    StrictModel,
)
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
from app.services.system_graph.scanner import ScanRequest, scan_repository
from app.services.system_graph.diff import diff_snapshots
from app.services.system_graph.query import graph_page, search_page
from app.services.system_graph.repository import (
    DatabaseGraphRepository,
    GraphRepository,
    refresh_fingerprint,
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


def get_graph_repository() -> GraphRepository:
    return DatabaseGraphRepository()


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


def repository_root() -> Path:
    configured = os.getenv("OMNI_REPO_ROOT", "").strip()
    root = Path(configured).resolve() if configured else Path(__file__).resolve().parents[4]
    if not (root / "AGENTS.md").is_file():
        raise RuntimeError("system_graph_repository_unavailable")
    return root


@router.get("/snapshot", response_model=GraphSnapshot)
async def read_system_graph_snapshot(
    repository: GraphRepository = Depends(get_graph_repository),
) -> GraphSnapshot:
    # Dynamic probes are deliberately disabled: the adapter must not turn a
    # runtime outage into a changed static fact just to render execution mode.
    try:
        latest = await repository.latest_snapshot()
    except RuntimeError:
        latest = None
    return latest or scan_repository(ScanRequest(repo=repository_root(), dynamic=False))


async def _run_refresh(
    refresh_id: str,
    request: GraphRefreshRequest,
    repository: GraphRepository,
) -> None:
    try:
        await repository.mark_refresh_running(refresh_id)
        base = await repository.latest_snapshot()
        snapshot = scan_repository(
            ScanRequest(
                repo=repository_root(),
                feature_ids=tuple(request.feature_ids),
                dynamic=request.include_runtime,
                base_snapshot=base,
            )
        )
        await repository.save_snapshot(snapshot)
        await repository.complete_refresh(refresh_id, snapshot)
    except Exception as exc:
        try:
            await repository.fail_refresh(
                refresh_id,
                code=f"collector_{type(exc).__name__.lower()}",
                retryable=True,
            )
        except Exception:
            pass


@router.post("/refresh", status_code=202)
async def refresh_system_graph(
    payload: GraphRefreshRequest,
    background_tasks: BackgroundTasks,
    repository: GraphRepository = Depends(get_graph_repository),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    _require_plan_reader(principal)
    request_payload = payload.model_dump(mode="json")
    fingerprint = refresh_fingerprint(request_payload)
    record, created = await repository.begin_refresh(
        fingerprint=fingerprint,
        actor_id=principal.principal_id,
        request=request_payload,
    )
    if created:
        background_tasks.add_task(_run_refresh, record.refresh_id, payload, repository)
    return {
        "refresh": record.model_dump(mode="json"),
        "reused": not created,
        "status_url": f"/api/v1/system-graph/refreshes/{record.refresh_id}",
    }


@router.get("/refreshes/{refresh_id}", response_model=GraphRefreshRecord)
async def get_system_graph_refresh(
    refresh_id: str,
    repository: GraphRepository = Depends(get_graph_repository),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
) -> GraphRefreshRecord:
    _require_plan_reader(principal)
    try:
        return await repository.get_refresh(refresh_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail={"code": "refresh_not_found"}) from exc


@router.get("/snapshots/{snapshot_id}/graph", response_model=GraphPage)
async def get_system_graph_page(
    snapshot_id: str,
    root: str | None = Query(default=None),
    direction: Literal["in", "out", "both"] = Query(default="both"),
    depth: int = Query(default=2, ge=0, le=6),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    kinds: list[str] = Query(default=[]),
    states: list[str] = Query(default=[]),
    repository: GraphRepository = Depends(get_graph_repository),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
) -> GraphPage:
    _require_plan_reader(principal)
    try:
        snapshot = await repository.get_snapshot(snapshot_id)
        return graph_page(
            snapshot,
            root=root,
            direction=direction,
            depth=depth,
            cursor=cursor,
            limit=limit,
            kinds=set(kinds),
            states=set(states),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "snapshot_or_root_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.get("/search", response_model=GraphSearchPage)
async def search_system_graph(
    q: str = Query(min_length=1, max_length=200),
    snapshot_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    repository: GraphRepository = Depends(get_graph_repository),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
) -> GraphSearchPage:
    _require_plan_reader(principal)
    try:
        snapshot = (
            await repository.get_snapshot(snapshot_id)
            if snapshot_id
            else await repository.latest_snapshot()
        )
        if snapshot is None:
            raise KeyError("latest")
        return search_page(snapshot, query=q, cursor=cursor, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "snapshot_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.get("/diff", response_model=GraphDiff)
async def get_system_graph_diff(
    from_snapshot: str = Query(alias="from"),
    to_snapshot: str = Query(alias="to"),
    repository: GraphRepository = Depends(get_graph_repository),
    principal: ApprovalPrincipal = Depends(get_approval_principal),
) -> GraphDiff:
    _require_plan_reader(principal)
    try:
        before = await repository.get_snapshot(from_snapshot)
        after = await repository.get_snapshot(to_snapshot)
        return diff_snapshots(before, after)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "snapshot_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "incompatible_schema"}) from exc
