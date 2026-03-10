from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.models.fetch_job import FetchJob
from app.schemas.fetch import FetchRequest
from app.services.fetch_service import FetchService
from app.sources.base import RawArticle


def _raw(title: str, url: str) -> RawArticle:
    return RawArticle(
        title=title,
        url=url,
        snippet="snippet",
        source_type="serper",
        source_name="TechCrunch",
        language="en",
        published_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_trigger_fetch_returns_existing_running_job() -> None:
    existing_job = FetchJob(
        id=uuid4(),
        triggered_by="u1",
        status="running",
        sources_used=["serper"],
        keywords_used=["AI"],
    )
    db = AsyncMock()
    db.scalar.return_value = existing_job

    service = FetchService(
        db=db,
        redis_client=AsyncMock(),
        settings=Settings(),
        sp3_client=AsyncMock(),
    )
    response = await service.trigger_fetch(
        request=FetchRequest(),
        current_user={"sub": "u1"},
    )

    assert response.job_id == existing_job.id
    assert response.status == "running"


@pytest.mark.asyncio
async def test_run_pipeline_marks_completed_and_adds_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    job = FetchJob(
        id=job_id,
        triggered_by="u1",
        status="running",
        sources_used=["serper"],
        keywords_used=["AI"],
    )

    class FakeDB:
        def __init__(self) -> None:
            self.added = []
            self._job = job
            self.commits = 0

        async def get(self, model, value):  # noqa: ANN001
            if model is FetchJob and value == job_id:
                return self._job
            return None

        def add(self, obj):  # noqa: ANN001
            self.added.append(obj)

        async def commit(self) -> None:
            self.commits += 1

    db = FakeDB()
    service = FetchService(
        db=db,  # type: ignore[arg-type]
        redis_client=AsyncMock(),
        settings=Settings(sp5_relevance_threshold=0.3),
        sp3_client=AsyncMock(),
    )

    async def fake_fetch_from_sources(**kwargs):  # noqa: ANN003
        return [_raw("A", "https://a.com/1"), _raw("B", "https://a.com/2")]

    async def fake_dedup(self, articles):  # noqa: ANN001, ANN201
        return articles

    async def fake_enrich(self, articles):  # noqa: ANN001, ANN201
        return [
            SimpleNamespace(raw=articles[0], summary_zh="ok", tags=["LLM"], relevance_score=0.9),
            SimpleNamespace(raw=articles[1], summary_zh="low", tags=["Other"], relevance_score=0.1),
        ]

    def fake_filter(self, enriched):  # noqa: ANN001, ANN201
        return [item for item in enriched if item.relevance_score >= 0.3]

    monkeypatch.setattr(service, "_fetch_from_sources", fake_fetch_from_sources)
    monkeypatch.setattr("app.pipeline.dedup.ArticleDeduplicator.deduplicate", fake_dedup)
    monkeypatch.setattr("app.pipeline.enricher.ArticleEnricher.enrich", fake_enrich)
    monkeypatch.setattr("app.pipeline.enricher.ArticleEnricher.filter_by_relevance", fake_filter)

    await service._run_pipeline(
        job_id=job_id,
        sources=["serper"],
        keywords=["AI"],
        freshness="oneDay",
    )

    assert job.status == "completed"
    assert job.total_fetched == 2
    assert job.after_dedup == 2
    assert job.after_enrich == 1
    assert any(getattr(item, "url", "") == "https://a.com/1" for item in db.added)
