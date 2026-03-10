from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_review_service
from app.schemas.archive import BatchArchiveRequest, BatchArchiveResponse
from app.schemas.article import ArticleListResponse, ArticlePatch, ArticleResponse
from app.services.review_service import ReviewService

router = APIRouter(tags=["news-articles"])


def _to_article_response(item) -> ArticleResponse:
    return ArticleResponse.model_validate(item, from_attributes=True)


@router.get("/articles", response_model=ArticleListResponse)
async def list_articles(
    status_filter: str = Query(default="pending", alias="status"),
    source: str = Query(default="all"),
    language: str = Query(default="all"),
    tag: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="fetched_at"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    service: ReviewService = Depends(get_review_service),
) -> ArticleListResponse:
    items, total = await service.query_articles(
        status=status_filter,
        source=source,
        language=language,
        tag=tag,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return ArticleListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_article_response(item) for item in items],
    )


@router.patch("/articles/{article_id}", response_model=ArticleResponse)
async def patch_article(
    article_id: UUID,
    patch: ArticlePatch,
    service: ReviewService = Depends(get_review_service),
) -> ArticleResponse:
    updated = await service.update_article(article_id, patch)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="article not found")
    return _to_article_response(updated)


@router.post("/articles/batch", response_model=BatchArchiveResponse)
async def batch_articles(
    request: BatchArchiveRequest,
    service: ReviewService = Depends(get_review_service),
) -> BatchArchiveResponse:
    if not request.article_ids:
        return BatchArchiveResponse(updated_count=0, archived_to_kb=0, failed_ids=[])
    ids: list[UUID] = []
    for item in request.article_ids:
        try:
            ids.append(UUID(item))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid UUID: {item}",
            ) from exc
    return await service.batch_action(ids, request.action)
