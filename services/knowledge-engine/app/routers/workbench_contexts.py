"""Authenticated API for immutable Workbench context creation and CAS rebind."""

from fastapi import APIRouter, Depends, HTTPException

from app.routers.runtime_traces import require_trace_access
from app.schemas.workbench_contexts import (
    WorkbenchContextResolveRequest,
    WorkbenchContextResult,
)
from app.services.workbench_contexts import (
    DatabaseWorkbenchContextStore,
    WorkbenchContextConflict,
    WorkbenchContextStore,
    local_owner_permission_scope_hash,
)

router = APIRouter(
    prefix="/api/v1/workbench-contexts",
    tags=["workbench-contexts"],
    dependencies=[Depends(require_trace_access)],
)


def get_workbench_context_store() -> WorkbenchContextStore:
    return DatabaseWorkbenchContextStore()


async def _resolve(
    payload: WorkbenchContextResolveRequest,
    store: WorkbenchContextStore,
) -> WorkbenchContextResult:
    try:
        return await store.resolve(
            payload,
            permission_scope_hash=local_owner_permission_scope_hash(),
        )
    except WorkbenchContextConflict as exc:
        code = str(exc)
        raise HTTPException(status_code=409, detail={"code": code}) from exc


@router.post("", response_model=WorkbenchContextResult)
async def resolve_workbench_context(
    payload: WorkbenchContextResolveRequest,
    store: WorkbenchContextStore = Depends(get_workbench_context_store),
) -> WorkbenchContextResult:
    return await _resolve(payload, store)


@router.post("/rebind", response_model=WorkbenchContextResult)
async def rebind_workbench_context(
    payload: WorkbenchContextResolveRequest,
    store: WorkbenchContextStore = Depends(get_workbench_context_store),
) -> WorkbenchContextResult:
    if payload.expected_snapshot_id is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "context_expected_pair_required"},
        )
    return await _resolve(payload, store)
