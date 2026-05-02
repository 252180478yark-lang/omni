from fastapi import APIRouter, HTTPException

from app.database import get_pool

router = APIRouter()


@router.get("/runs")
async def list_runs(limit: int = 50):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, runbook_name, started_at, ended_at, status, error
            FROM mvp_runbook_run
            ORDER BY started_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM mvp_runbook_run WHERE id=$1", run_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str):
    from fastapi import BackgroundTasks
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT runbook_name FROM mvp_runbook_run WHERE id=$1", run_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")

    from app.services.runbook_loader import load_one
    from app.services.runbook_executor import RunbookExecutor
    rb_id = row["runbook_name"]
    try:
        rb = load_one(rb_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Runbook not found: {rb_id}")

    executor = RunbookExecutor(rb, rb_id)
    import asyncio
    asyncio.create_task(executor.run())
    return {"new_run_id": executor.run_id, "original_run_id": run_id}
