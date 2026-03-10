from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.article import Article
from app.schemas.archive import ArchiveStatsResponse, BatchArchiveResponse, RetryKbResponse

logger = logging.getLogger(__name__)


class ArchiveService:
    def __init__(
        self,
        db: AsyncSession,
        sp4_client: httpx.AsyncClient,
        settings: Settings,
    ):
        self.db = db
        self.sp4_client = sp4_client
        self.target_kb_id = settings.sp5_target_kb_id

    async def batch_archive(self, article_ids: list[UUID]) -> BatchArchiveResponse:
        updated = 0
        kb_pushed = 0
        failed_ids: list[str] = []

        for article_id in article_ids:
            article = await self.db.get(Article, article_id)
            if article is None:
                failed_ids.append(str(article_id))
                continue

            article.status = "archived"
            article.archived_at = datetime.now(tz=timezone.utc)
            updated += 1

            try:
                doc_id = await self._push_to_sp4(article)
                article.kb_doc_id = doc_id
                kb_pushed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("sp4 push failed for article=%s: %s", article_id, str(exc))

        await self.db.commit()
        return BatchArchiveResponse(updated_count=updated, archived_to_kb=kb_pushed, failed_ids=failed_ids)

    async def retry_kb_push(self, article_ids: list[UUID]) -> RetryKbResponse:
        retried = 0
        success = 0
        failed_ids: list[str] = []

        for article_id in article_ids:
            article = await self.db.get(Article, article_id)
            if article is None or article.status != "archived":
                failed_ids.append(str(article_id))
                continue
            retried += 1
            try:
                doc_id = await self._push_to_sp4(article)
                article.kb_doc_id = doc_id
                success += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("retry sp4 push failed for article=%s: %s", article_id, str(exc))
                failed_ids.append(str(article_id))

        await self.db.commit()
        return RetryKbResponse(retried=retried, success=success, failed_ids=failed_ids)

    async def get_archive_stats(self) -> ArchiveStatsResponse:
        total_archived = (
            await self.db.scalar(select(func.count()).select_from(Article).where(Article.status == "archived"))
        ) or 0
        recent_7d_count = (
            await self.db.scalar(
                select(func.count())
                .select_from(Article)
                .where(
                    Article.status == "archived",
                    Article.archived_at >= datetime.now(tz=timezone.utc) - timedelta(days=7),
                )
            )
        ) or 0
        kb_synced_count = (
            await self.db.scalar(
                select(func.count())
                .select_from(Article)
                .where(Article.status == "archived", Article.kb_doc_id.is_not(None))
            )
        ) or 0
        kb_pending_count = (
            await self.db.scalar(
                select(func.count())
                .select_from(Article)
                .where(Article.status == "archived", Article.kb_doc_id.is_(None))
            )
        ) or 0

        by_source_rows = (
            await self.db.execute(
                select(Article.source, func.count())
                .where(Article.status == "archived")
                .group_by(Article.source)
            )
        ).all()
        by_source = {str(source): int(count) for source, count in by_source_rows}

        top_tags = await self._get_top_tags(limit=10)
        return ArchiveStatsResponse(
            total_archived=int(total_archived),
            by_source=by_source,
            top_tags=top_tags,
            recent_7d_count=int(recent_7d_count),
            kb_synced_count=int(kb_synced_count),
            kb_pending_count=int(kb_pending_count),
        )

    async def _push_to_sp4(self, article: Article) -> str:
        text_parts = [article.ai_summary or "", article.raw_snippet or ""]
        tag_text = ", ".join(article.ai_tags or [])
        if tag_text:
            text_parts.append(f"Tags: {tag_text}")
        text_parts.append(f"Source: {article.url}")
        text = "\n\n".join(part for part in text_parts if part)

        response = await self.sp4_client.post(
            "/api/v1/knowledge/ingest",
            json={
                "kb_id": self.target_kb_id,
                "title": article.title,
                "text": text,
                "source_url": article.url,
                "metadata": {
                    "source": "news-aggregator",
                    "article_id": str(article.id),
                    "source_type": article.source,
                    "tags": article.ai_tags,
                    "published_at": article.published_at.isoformat() if article.published_at else None,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        document_id = payload.get("data", {}).get("document_id")
        if not document_id:
            raise ValueError("sp4 response missing data.document_id")
        return str(document_id)

    async def _get_top_tags(self, limit: int) -> list[dict[str, int | str]]:
        rows = (
            await self.db.scalars(select(Article.ai_tags).where(Article.status == "archived", Article.ai_tags.is_not(None)))
        ).all()
        counter: Counter[str] = Counter()
        for row in rows:
            for tag in row or []:
                if isinstance(tag, str) and tag.strip():
                    counter[tag.strip()] += 1
        return [{"tag": tag, "count": count} for tag, count in counter.most_common(limit)]
