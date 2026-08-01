"""S9 one-click entry that creates only an unconfirmed candidate-plan draft."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.routers.runtime_traces import require_trace_access
from app.schemas.runtime_trace import RuntimePlanDraft, RuntimePlanDraftCreate
from app.services.runtime_plan_drafts import DatabaseRuntimePlanDraftStore, RuntimePlanDraftStore

router = APIRouter(prefix="/api/v1/runtime-plan-drafts", tags=["runtime-radar"])


def get_plan_draft_store() -> RuntimePlanDraftStore:
    return DatabaseRuntimePlanDraftStore()


@router.post("", response_model=RuntimePlanDraft, dependencies=[Depends(require_trace_access)])
async def create_runtime_plan_draft(
    payload: RuntimePlanDraftCreate,
    store: RuntimePlanDraftStore = Depends(get_plan_draft_store),
) -> RuntimePlanDraft:
    try:
        return await store.create(payload)
    except ValueError as exc:
        if str(exc) == "runtime_plan_version_conflict":
            raise HTTPException(status_code=409, detail={"code": "runtime_plan_version_conflict"}) from exc
        raise
