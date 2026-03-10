from __future__ import annotations

from difflib import SequenceMatcher

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.sources.base import RawArticle


class ArticleDeduplicator:
    REDIS_KEY = "news:seen_urls"
    REDIS_TTL_SECONDS = 7 * 24 * 3600
    TITLE_SIMILARITY_THRESHOLD = 0.85

    def __init__(self, redis_client: redis.Redis, db: AsyncSession):
        self.redis = redis_client
        self.db = db

    async def deduplicate(self, articles: list[RawArticle]) -> list[RawArticle]:
        unique_by_url: list[RawArticle] = []
        seen_urls_in_batch: set[str] = set()
        for article in articles:
            if not article.url:
                continue
            if article.url in seen_urls_in_batch:
                continue
            if await self.redis.sismember(self.REDIS_KEY, article.url):
                continue
            exists = await self.db.scalar(select(Article.id).where(Article.url == article.url))
            if exists:
                await self.redis.sadd(self.REDIS_KEY, article.url)
                continue
            unique_by_url.append(article)
            seen_urls_in_batch.add(article.url)

        deduped = self._dedup_by_title(unique_by_url)

        if deduped:
            urls = [item.url for item in deduped]
            await self.redis.sadd(self.REDIS_KEY, *urls)
            await self.redis.expire(self.REDIS_KEY, self.REDIS_TTL_SECONDS)

        return deduped

    def _dedup_by_title(self, articles: list[RawArticle]) -> list[RawArticle]:
        result: list[RawArticle] = []
        for article in articles:
            duplicate_index: int | None = None
            for idx, existing in enumerate(result):
                if article.language != existing.language:
                    continue
                similarity = SequenceMatcher(None, article.title, existing.title).ratio()
                if similarity > self.TITLE_SIMILARITY_THRESHOLD:
                    duplicate_index = idx
                    break

            if duplicate_index is None:
                result.append(article)
                continue

            existing = result[duplicate_index]
            current_len = len(article.snippet or "")
            existing_len = len(existing.snippet or "")
            if current_len > existing_len:
                result[duplicate_index] = article
        return result
