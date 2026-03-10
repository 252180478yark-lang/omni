from __future__ import annotations

import asyncio

from app.sources.base import BaseFetcher, RawArticle, handle_fetch_errors


class BochaFetcher(BaseFetcher):
    source_type = "bocha"
    language = "zh"
    endpoint = "https://api.bochaai.com/v1/web-search"

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

        tasks = [
            self._fetch_keyword(keyword=keyword, freshness=freshness, max_results=max_results) for keyword in keywords
        ]
        chunks = await asyncio.gather(*tasks)
        merged: list[RawArticle] = []
        for chunk in chunks:
            merged.extend(chunk)
        return merged

    async def _fetch_keyword(self, keyword: str, freshness: str, max_results: int) -> list[RawArticle]:
        response = await self.client.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "query": keyword,
                "freshness": freshness,
                "summary": True,
                "count": max_results,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()

        data = payload.get("data", payload)
        items = (((data.get("webPages") or {}).get("value")) if isinstance(data, dict) else None) or []
        if not isinstance(items, list):
            raise ValueError("invalid bocha payload: webPages.value is not a list")

        articles: list[RawArticle] = []
        for item in items:
            title = (item.get("name") or "").strip()
            url = (item.get("url") or "").strip()
            if not title or not url:
                continue
            articles.append(
                RawArticle(
                    title=title,
                    url=url,
                    snippet=(item.get("summary") or "").strip(),
                    source_type=self.source_type,
                    source_name=item.get("siteName"),
                    language=self.language,
                    published_at=self.parse_datetime(item.get("datePublished")),
                )
            )
        return articles
