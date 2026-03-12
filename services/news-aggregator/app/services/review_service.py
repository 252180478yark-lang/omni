from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.schemas.archive import ArchiveSearchFilters, BatchArchiveResponse
from app.schemas.article import ArticlePatch
from app.services.archive_service import ArchiveService


class ReviewService:
    def __init__(self, db: AsyncSession, archive_service: ArchiveService) -> None:
        self.db = db
        self.archive_service = archive_service

    async def query_articles(
        self,
        *,
        status: str = "pending",
        source: str = "all",
        language: str = "all",
        tag: str | None = None,
        search: str | None = None,
        sort_by: str = "fetched_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Article], int]:
        query = select(Article)
        query = self._apply_common_filters(
            query,
            status=status,
            source=source,
            language=language,
            tag=tag,
            search=search,
            is_starred=None,
            date_from=None,
            date_to=None,
            archived_only=False,
        )
        query = self._apply_sorting(query, sort_by=sort_by, sort_order=sort_order, archived_mode=False)
        return await self._paginate(query, page=page, page_size=page_size)

    async def query_archive(self, filters: ArchiveSearchFilters) -> tuple[list[Article], int]:
        query = select(Article).where(Article.status == "archived")
        query = self._apply_common_filters(
            query,
            status="archived",
            source=filters.source,
            language=filters.language,
            tag=None,
            search=filters.search,
            is_starred=filters.is_starred,
            date_from=filters.date_from,
            date_to=filters.date_to,
            archived_only=True,
        )
        for tag in filters.tags:
            cleaned = tag.strip()
            if cleaned:
                query = query.where(Article.ai_tags.contains([cleaned]))

        query = self._apply_sorting(
            query,
            sort_by=filters.sort_by,
            sort_order=filters.sort_order,
            archived_mode=True,
        )
        return await self._paginate(query, page=filters.page, page_size=filters.page_size)

    async def update_article(self, article_id: UUID, patch: ArticlePatch) -> Article | None:
        article = await self.db.get(Article, article_id)
        if article is None:
            return None
        if patch.status is not None:
            article.status = patch.status
            if patch.status == "archived" and article.archived_at is None:
                article.archived_at = datetime.now(tz=timezone.utc)
            if patch.status != "archived":
                article.archived_at = None
        if patch.is_starred is not None:
            article.is_starred = patch.is_starred
        await self.db.commit()
        await self.db.refresh(article)
        return article

    async def batch_action(self, article_ids: list[UUID], action: str) -> BatchArchiveResponse:
        if action == "archive":
            return await self.archive_service.batch_archive(article_ids)

        updated = 0
        failed_ids: list[str] = []
        for article_id in article_ids:
            article = await self.db.get(Article, article_id)
            if article is None:
                failed_ids.append(str(article_id))
                continue
            article.status = "dismissed"
            article.archived_at = None
            updated += 1

        await self.db.commit()
        return BatchArchiveResponse(updated_count=updated, archived_to_kb=0, failed_ids=failed_ids)

    async def get_available_tags(self) -> list[dict[str, int | str]]:
        rows = (await self.db.scalars(select(Article.ai_tags).where(Article.status == "archived"))).all()
        counter: dict[str, int] = {}
        for tags in rows:
            if not isinstance(tags, list):
                continue
            for tag in tags:
                value = str(tag).strip()
                if not value:
                    continue
                counter[value] = counter.get(value, 0) + 1
        return [
            {"tag": tag, "count": count}
            for tag, count in sorted(counter.items(), key=lambda item: item[1], reverse=True)
        ]

    def _apply_common_filters(
        self,
        query,
        *,
        status: str,
        source: str,
        language: str,
        tag: str | None,
        search: str | None,
        is_starred: bool | None,
        date_from,
        date_to,
        archived_only: bool,
    ):
        if status != "all":
            query = query.where(Article.status == status)
        if source != "all":
            query = query.where(Article.source == source)
        if language != "all":
            query = query.where(Article.language == language)
        if tag:
            query = query.where(Article.ai_tags.contains([tag]))
        if search:
            pattern = f"%{search}%"
            query = query.where(or_(
                Article.title.ilike(pattern),
                Article.ai_summary.ilike(pattern),
                Article.raw_snippet.ilike(pattern),
            ))
        if is_starred is not None:
            query = query.where(Article.is_starred == is_starred)

        if archived_only and date_from:
            start_dt = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            query = query.where(Article.archived_at >= start_dt)
        if archived_only and date_to:
            end_dt = datetime.combine(date_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
            query = query.where(Article.archived_at < end_dt)
        return query

    @staticmethod
    def _apply_sorting(query, *, sort_by: str, sort_order: str, archived_mode: bool):
        allowed = {"fetched_at", "ai_relevance_score", "published_at", "archived_at"}
        chosen = sort_by if sort_by in allowed else ("archived_at" if archived_mode else "fetched_at")
        order_col = getattr(Article, chosen)
        if sort_order == "asc":
            return query.order_by(order_col.asc())
        return query.order_by(order_col.desc())

    async def _paginate(self, query, *, page: int, page_size: int) -> tuple[list[Article], int]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 50)
        total = int((await self.db.scalar(select(func.count()).select_from(query.subquery()))) or 0)
        items = (
            await self.db.scalars(
                query.offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        return list(items), total
