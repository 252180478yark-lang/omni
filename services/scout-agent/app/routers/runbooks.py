import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.runbook import RunbookSummary
from app.services.runbook_loader import list_summaries, load_one
from app.services.runbook_executor import RunbookExecutor

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/runbooks", response_model=list[RunbookSummary])
async def list_runbooks():
    return list_summaries()


@router.post("/runbooks/{rb_id:path}/run")
async def trigger_runbook(rb_id: str, background_tasks: BackgroundTasks):
    try:
        rb = load_one(rb_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Runbook not found: {rb_id}")

    executor = RunbookExecutor(rb, rb_id)
    background_tasks.add_task(executor.run)
    return {"run_id": executor.run_id, "runbook": rb_id, "status": "started"}
