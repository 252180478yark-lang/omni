from __future__ import annotations

import asyncio

from app.sources.base import BaseFetcher, RawArticle, handle_fetch_errors


class SerperFetcher(BaseFetcher):
    source_type = "serper"
    language = "en"
    endpoint = "https://google.serper.dev/news"

    @handle_fetch_errors(source_type)
    async def fetch(
        self,
        keywords: list[str],
        freshness: str = "oneDay",
        max_results: int = 10,
    ) -> list[RawArticle]:
        if not self.api_key:
            return []
        if not keywords:
            return []

        tasks = [self._fetch_keyword(keyword=keyword, max_results=max_results) for keyword in keywords]
        chunks = await asyncio.gather(*tasks)
        merged: list[RawArticle] = []
        for chunk in chunks:
            merged.extend(chunk)
        return merged

    async def _fetch_keyword(self, keyword: str, max_results: int) -> list[RawArticle]:
        response = await self.client.post(
            self.endpoint,
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            json={"q": keyword, "num": max_results},
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("news", [])
        if not isinstance(items, list):
            raise ValueError("invalid serper payload: news is not a list")

        articles: list[RawArticle] = []
        for item in items:
            title = (item.get("title") or "").strip()
            url = (item.get("link") or "").strip()
            if not title or not url:
                continue
            articles.append(
                RawArticle(
                    title=title,
                    url=url,
                    snippet=(item.get("snippet") or "").strip(),
                    source_type=self.source_type,
                    source_name=item.get("source"),
                    language=self.language,
                    published_at=self.parse_datetime(item.get("date")),
                )
            )
        return articles
