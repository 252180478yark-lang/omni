from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.dependencies import get_fetch_service
from app.schemas.fetch import FetchRequest, FetchResponse, JobStatusResponse, JobListResponse
from app.services.fetch_service import FetchService

router = APIRouter(tags=["news-fetch"])


@router.get("/fetch", response_model=JobListResponse)
async def list_fetch_jobs(
    limit: int = 10,
    service: FetchService = Depends(get_fetch_service),
) -> JobListResponse:
    jobs = await service.list_recent_jobs(limit=limit)
    return JobListResponse(jobs=jobs)


@router.post("/fetch", response_model=FetchResponse)
async def trigger_fetch(
    request: FetchRequest,
    service: FetchService = Depends(get_fetch_service),
) -> FetchResponse | JSONResponse:
    result = await service.trigger_fetch(request=request)
    if result.message == "\u5df2\u6709\u8fd0\u884c\u4e2d\u7684\u62c9\u53d6\u4efb\u52a1":
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=result.model_dump(mode="json"))
    return result


@router.get("/fetch/{job_id}", response_model=JobStatusResponse)
async def get_fetch_job_status(
    job_id: UUID,
    service: FetchService = Depends(get_fetch_service),
) -> JobStatusResponse:
    try:
        return await service.get_job_status(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
