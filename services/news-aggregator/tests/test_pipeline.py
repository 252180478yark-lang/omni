from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.config import Settings
from app.pipeline.dedup import ArticleDeduplicator
from app.pipeline.enricher import ArticleEnricher
from app.sources.base import RawArticle


def _raw(
    *,
    title: str,
    url: str,
    snippet: str,
    language: str = "zh",
    source_type: str = "bocha",
) -> RawArticle:
    return RawArticle(
        title=title,
        url=url,
        snippet=snippet,
        source_type=source_type,
        source_name="src",
        language=language,
        published_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_dedup_url_and_title_and_cross_language() -> None:
    redis_client = AsyncMock()
    redis_client.sismember.side_effect = [False, False, False, False]

    db = AsyncMock()
    db.scalar.return_value = None

    deduplicator = ArticleDeduplicator(redis_client=redis_client, db=db)
    items = [
        _raw(title="OpenAI releases new model today", url="https://a.com/1", snippet="short"),
        _raw(title="OpenAI releases new model", url="https://a.com/2", snippet="a much longer summary text"),
        _raw(title="OpenAI releases new model", url="https://a.com/3", snippet="English version", language="en"),
        _raw(title="重复 URL", url="https://a.com/1", snippet="will be removed"),
    ]

    output = await deduplicator.deduplicate(items)

    assert len(output) == 2
    urls = {item.url for item in output}
    assert "https://a.com/2" in urls  # 保留更长摘要版本
    assert "https://a.com/3" in urls  # 跨语言保留


@pytest.mark.asyncio
async def test_enricher_parse_and_relevance_filter() -> None:
    settings = Settings(
        sp5_enrich_batch_size=5,
        sp5_relevance_threshold=0.3,
        enricher_provider="gemini",
        enricher_model="gemini-2.0-flash",
        enricher_max_tokens=2000,
    )
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 200,
        "data": {
            "content": '{"articles":[{"index":0,"summary_zh":"摘要A","tags":["LLM"],"relevance_score":0.91},{"index":1,"summary_zh":"摘要B","tags":["Other"],"relevance_score":0.2}]}'
        },
    }
    sp3 = AsyncMock()
    sp3.post.return_value = response
    enricher = ArticleEnricher(sp3_client=sp3, settings=settings)

    enriched = await enricher.enrich(
        [
            _raw(title="A", url="https://a.com/1", snippet="a"),
            _raw(title="B", url="https://a.com/2", snippet="b"),
        ]
    )
    filtered = enricher.filter_by_relevance(enriched)

    assert len(enriched) == 2
    assert len(filtered) == 1
    assert filtered[0].summary_zh == "摘要A"


@pytest.mark.asyncio
async def test_enricher_retry_fallback_to_raw() -> None:
    settings = Settings(sp5_enrich_batch_size=5)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"code": 200, "data": {"content": "not json"}}
    sp3 = AsyncMock()
    sp3.post.return_value = response
    enricher = ArticleEnricher(sp3_client=sp3, settings=settings)

    enriched = await enricher.enrich([_raw(title="A", url="https://a.com/1", snippet="a")])

    assert len(enriched) == 1
    assert enriched[0].summary_zh is None
    assert enriched[0].relevance_score is None
