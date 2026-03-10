from __future__ import annotations

import os

import httpx
import pytest

from app.sources.bocha_fetcher import BochaFetcher
from app.sources.serper_fetcher import SerperFetcher
from app.sources.tianapi_fetcher import TianapiFetcher


@pytest.mark.asyncio
async def test_fetchers_live_api_call() -> None:
    serper_key = os.getenv("SERPER_API_KEY", "")
    bocha_key = os.getenv("BOCHA_API_KEY", "")
    tianapi_key = os.getenv("TIANAPI_KEY", "")
    if not (serper_key and bocha_key and tianapi_key):
        pytest.skip("missing live API keys for fetcher integration test")

    async with httpx.AsyncClient(timeout=15.0) as client:
        serper_items = await SerperFetcher(client=client, api_key=serper_key).fetch(
            keywords=["AI news today"], max_results=10
        )
        bocha_items = await BochaFetcher(client=client, api_key=bocha_key).fetch(
            keywords=["AI 人工智能 最新"], freshness="oneDay", max_results=10
        )
        tianapi_items = await TianapiFetcher(client=client, api_key=tianapi_key).fetch(
            keywords=[], max_results=10
        )

    assert len(serper_items) > 0
    assert len(bocha_items) > 0
    assert len(tianapi_items) > 0
    assert serper_items[0].source_type == "serper"
    assert bocha_items[0].source_type == "bocha"
    assert tianapi_items[0].source_type == "tianapi"
