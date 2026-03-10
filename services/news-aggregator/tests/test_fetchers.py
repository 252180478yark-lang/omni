from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.sources.bocha_fetcher import BochaFetcher
from app.sources.serper_fetcher import SerperFetcher
from app.sources.tianapi_fetcher import TianapiFetcher


def _ok_response(payload: dict) -> AsyncMock:
    response = AsyncMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


@pytest.mark.asyncio
async def test_serper_fetcher_field_mapping_and_error_handling() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    fetcher = SerperFetcher(client=client, api_key="serper-key")

    client.post.side_effect = [
        _ok_response(
            {
                "news": [
                    {
                        "title": "OpenAI ships GPT-5",
                        "link": "https://example.com/a",
                        "snippet": "New reasoning mode.",
                        "source": "TechCrunch",
                        "date": "2026-03-10T09:00:00Z",
                    }
                ]
            }
        ),
        httpx.TimeoutException("timeout"),
    ]

    ok_items = await fetcher.fetch(keywords=["openai"], max_results=10)
    assert len(ok_items) == 1
    article = ok_items[0]
    assert article.title == "OpenAI ships GPT-5"
    assert article.url == "https://example.com/a"
    assert article.snippet == "New reasoning mode."
    assert article.source_name == "TechCrunch"
    assert article.language == "en"
    assert article.source_type == "serper"
    assert article.published_at is not None

    failed_items = await fetcher.fetch(keywords=["anthropic"], max_results=10)
    assert failed_items == []


@pytest.mark.asyncio
async def test_bocha_fetcher_field_mapping() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = _ok_response(
        {
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "大模型新进展",
                            "url": "https://example.cn/a",
                            "summary": "这是摘要",
                            "siteName": "机器之心",
                            "datePublished": "2026-03-10 08:00:00",
                        }
                    ]
                }
            }
        }
    )
    fetcher = BochaFetcher(client=client, api_key="bocha-key")
    items = await fetcher.fetch(keywords=["大模型"], freshness="oneDay", max_results=10)

    assert len(items) == 1
    article = items[0]
    assert article.title == "大模型新进展"
    assert article.url == "https://example.cn/a"
    assert article.snippet == "这是摘要"
    assert article.source_name == "机器之心"
    assert article.language == "zh"
    assert article.source_type == "bocha"
    assert article.published_at is not None


@pytest.mark.asyncio
async def test_tianapi_fetcher_field_mapping() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _ok_response(
        {
            "result": {
                "newslist": [
                    {
                        "title": "AI 芯片发布",
                        "url": "https://example.cn/chip",
                        "description": "芯片相关新闻",
                        "source": "36kr",
                        "ctime": "2026-03-10 10:30:00",
                    }
                ]
            }
        }
    )
    fetcher = TianapiFetcher(client=client, api_key="tianapi-key")
    items = await fetcher.fetch(keywords=[], max_results=10)

    assert len(items) == 1
    article = items[0]
    assert article.title == "AI 芯片发布"
    assert article.url == "https://example.cn/chip"
    assert article.snippet == "芯片相关新闻"
    assert article.source_name == "36kr"
    assert article.language == "zh"
    assert article.source_type == "tianapi"
    assert article.published_at is not None
