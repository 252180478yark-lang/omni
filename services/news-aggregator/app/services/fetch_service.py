from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import SessionLocal
from app.models.article import Article
from app.models.fetch_job import FetchJob
from app.models.source_config import SourceConfig
from app.pipeline.dedup import ArticleDeduplicator
from app.pipeline.enricher import ArticleEnricher
from app.schemas.fetch import FetchRequest, FetchResponse, JobStatusResponse
from app.sources.base import BaseFetcher, RawArticle
from app.sources.bocha_fetcher import BochaFetcher
from app.sources.serper_fetcher import SerperFetcher
from app.sources.tianapi_fetcher import TianapiFetcher

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_ORDER = ["serper", "bocha", "tianapi"]


class FetchService:
    def __init__(
        self,
        db: AsyncSession,
        redis_client: redis.Redis,
        settings: Settings,
        sp3_client: httpx.AsyncClient,
    ):
        self.db = db
        self.redis = redis_client
        self.settings = settings
        self.sp3_client = sp3_client

    async def trigger_fetch(self, request: FetchRequest) -> FetchResponse:
        running_job = await self.db.scalar(
            select(FetchJob).where(FetchJob.status == "running").order_by(FetchJob.started_at.desc())
        )
        if running_job is not None:
            return FetchResponse(
                job_id=running_job.id,
                status="running",
                message="已有运行中的拉取任务",
            )

        selected_sources = request.sources or DEFAULT_SOURCE_ORDER
        selected_sources = [source for source in selected_sources if source in DEFAULT_SOURCE_ORDER]
        if not selected_sources:
            selected_sources = DEFAULT_SOURCE_ORDER

        default_keywords = await self._load_default_keywords(selected_sources)
        keywords = request.keywords_override or default_keywords
        keywords = [keyword.strip() for keyword in keywords if keyword.strip()]

        job = FetchJob(
            triggered_by="local-owner",
            status="running",
            sources_used=selected_sources,
            keywords_used=keywords,
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        asyncio.create_task(
            self._run_pipeline_in_background(
                job_id=job.id,
                sources=selected_sources,
                keywords=keywords,
                freshness=request.freshness_override or self.settings.sp5_default_freshness,
            )
        )
        return FetchResponse(
            job_id=job.id,
            status="running",
            message="拉取任务已启动，预计 15-30 秒完成",
        )

    async def _run_pipeline_in_background(
        self,
        job_id: UUID,
        sources: list[str],
        keywords: list[str],
        freshness: str,
    ) -> None:
        async with (
            SessionLocal() as session,
            httpx.AsyncClient(base_url=self.settings.sp3_base_url, timeout=30.0) as sp3_client,
        ):
            redis_client = redis.from_url(self.settings.redis_url, decode_responses=True)
            service = FetchService(
                db=session,
                redis_client=redis_client,
                settings=self.settings,
                sp3_client=sp3_client,
            )
            try:
                await service._run_pipeline(job_id=job_id, sources=sources, keywords=keywords, freshness=freshness)
            finally:
                await redis_client.aclose()

    async def get_job_status(self, job_id: UUID) -> JobStatusResponse:
        job = await self.db.get(FetchJob, job_id)
        if job is None:
            raise ValueError(f"fetch job not found: {job_id}")
        return JobStatusResponse(
            job_id=job.id,
            status=job.status,
            sources_used=job.sources_used,
            total_fetched=job.total_fetched,
            after_dedup=job.after_dedup,
            after_enrich=job.after_enrich,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_log=job.error_log,
        )

    async def _run_pipeline(
        self,
        job_id: UUID,
        sources: list[str],
        keywords: list[str],
        freshness: str,
    ) -> None:
        job = await self.db.get(FetchJob, job_id)
        if job is None:
            return

        try:
            raw_articles = await self._fetch_from_sources(sources=sources, keywords=keywords, freshness=freshness)
            job.total_fetched = len(raw_articles)
            await self.db.commit()

            deduplicator = ArticleDeduplicator(redis_client=self.redis, db=self.db)
            deduped = await deduplicator.deduplicate(raw_articles)
            job.after_dedup = len(deduped)
            await self.db.commit()

            enricher = ArticleEnricher(sp3_client=self.sp3_client, settings=self.settings)
            enriched = await enricher.enrich(deduped)
            filtered = enricher.filter_by_relevance(enriched)
            job.after_enrich = len(filtered)
            await self.db.commit()

            for item in filtered:
                self.db.add(
                    Article(
                        title=item.raw.title,
                        url=item.raw.url,
                        source=item.raw.source_type,
                        source_name=item.raw.source_name,
                        raw_snippet=item.raw.snippet,
                        ai_summary=item.summary_zh,
                        ai_tags=item.tags,
                        ai_relevance_score=item.relevance_score if item.relevance_score is not None else 0.0,
                        status="pending",
                        is_starred=False,
                        language=item.raw.language,
                        published_at=item.raw.published_at,
                        fetch_job_id=job.id,
                    )
                )

            job.status = "completed"
            job.finished_at = datetime.now(tz=timezone.utc)
            await self.db.commit()
        except Exception as exc:
            logger.exception("fetch pipeline failed for job=%s", job_id)
            job.status = "failed"
            job.error_log = str(exc)
            job.finished_at = datetime.now(tz=timezone.utc)
            await self.db.commit()

    async def _fetch_from_sources(self, sources: list[str], keywords: list[str], freshness: str) -> list[RawArticle]:
        source_configs = await self._load_source_configs(sources)
        if not source_configs:
            return []

        async with httpx.AsyncClient() as external_client:
            fetchers: list[BaseFetcher] = []
            for config in source_configs:
                fetcher = self._build_fetcher(external_client, config.source_type)
                if fetcher is None:
                    continue
                fetchers.append(fetcher)

            tasks = [
                fetcher.fetch(
                    keywords=keywords if fetcher.source_type != "tianapi" else [],
                    freshness=freshness,
                    max_results=self._source_max_results(fetcher.source_type, source_configs),
                )
                for fetcher in fetchers
            ]
            if not tasks:
                return []

            chunks = await asyncio.gather(*tasks, return_exceptions=True)
            results: list[RawArticle] = []
            for chunk in chunks:
                if isinstance(chunk, Exception):
                    logger.warning("single source fetch failed but pipeline keeps running: %s", str(chunk))
                    continue
                results.extend(chunk)
            return results

    async def _load_source_configs(self, sources: list[str]) -> list[SourceConfig]:
        query = select(SourceConfig).where(
            SourceConfig.is_enabled.is_(True),
            SourceConfig.source_type.in_(sources),
        )
        configs = list((await self.db.scalars(query)).all())
        order_map = {value: idx for idx, value in enumerate(DEFAULT_SOURCE_ORDER)}
        configs.sort(key=lambda item: order_map.get(item.source_type, 99))
        return configs

    async def _load_default_keywords(self, sources: list[str]) -> list[str]:
        configs = await self._load_source_configs(sources)
        all_keywords: list[str] = []
        for config in configs:
            if config.source_type == "tianapi":
                continue
            all_keywords.extend(config.keywords)

        seen: set[str] = set()
        result: list[str] = []
        for keyword in all_keywords:
            if keyword in seen:
                continue
            seen.add(keyword)
            result.append(keyword)
        return result

    def _build_fetcher(self, client: httpx.AsyncClient, source_type: str) -> BaseFetcher | None:
        if source_type == "serper":
            return SerperFetcher(client=client, api_key=self.settings.serper_api_key)
        if source_type == "bocha":
            return BochaFetcher(client=client, api_key=self.settings.bocha_api_key)
        if source_type == "tianapi":
            return TianapiFetcher(client=client, api_key=self.settings.tianapi_key)
        return None

    @staticmethod
    def _source_max_results(source_type: str, configs: list[SourceConfig]) -> int:
        for config in configs:
            if config.source_type == source_type:
                return int(config.max_results or 10)
        return 10
