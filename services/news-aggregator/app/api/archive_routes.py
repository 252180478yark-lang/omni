from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_archive_service, get_review_service
from app.schemas.archive import (
    ArchiveSearchFilters,
    ArchiveStatsResponse,
    RetryKbRequest,
    RetryKbResponse,
    TagListResponse,
)
from app.schemas.article import ArticleListResponse, ArticleResponse
from app.services.archive_service import ArchiveService
from app.services.review_service import ReviewService

router = APIRouter(tags=["news-archive"])


def _to_article_response(item) -> ArticleResponse:
    return ArticleResponse.model_validate(item, from_attributes=True)


@router.get("/archive", response_model=ArticleListResponse)
async def get_archive(
    source: str = Query(default="all"),
    language: str = Query(default="all"),
    tags: str | None = Query(default=None),
    search: str | None = Query(default=None),
    is_starred: bool | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    sort_by: str = Query(default="archived_at"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    service: ReviewService = Depends(get_review_service),
) -> ArticleListResponse:
    filters = ArchiveSearchFilters(
        source=source,
        language=language,
        tags=[tag.strip() for tag in (tags or "").split(",") if tag.strip()],
        search=search,
        is_starred=is_starred,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,  # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
    )
    items, total = await service.query_archive(filters)
    return ArticleListResponse(
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        items=[_to_article_response(item) for item in items],
    )


@router.get("/archive/tags", response_model=TagListResponse)
async def get_archive_tags(
    service: ReviewService = Depends(get_review_service),
) -> TagListResponse:
    return TagListResponse(tags=await service.get_available_tags())


@router.get("/archive/stats", response_model=ArchiveStatsResponse)
async def get_archive_stats(
    service: ArchiveService = Depends(get_archive_service),
) -> ArchiveStatsResponse:
    return await service.get_archive_stats()


@router.post("/archive/retry-kb", response_model=RetryKbResponse)
async def retry_kb_push(
    request: RetryKbRequest,
    service: ArchiveService = Depends(get_archive_service),
) -> RetryKbResponse:
    if not request.article_ids:
        return RetryKbResponse(retried=0, success=0, failed_ids=[])
    ids: list[UUID] = []
    for item in request.article_ids:
        try:
            ids.append(UUID(item))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid UUID: {item}",
            ) from exc
    return await service.retry_kb_push(ids)
