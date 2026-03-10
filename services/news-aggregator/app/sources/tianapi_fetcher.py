from __future__ import annotations

from app.sources.base import BaseFetcher, RawArticle, handle_fetch_errors


class TianapiFetcher(BaseFetcher):
    source_type = "tianapi"
    language = "zh"
    endpoint = "https://apis.tianapi.com/keji/index"

    @handle_fetch_errors(source_type)
    async def fetch(
        self,
        keywords: list[str],
        freshness: str = "oneDay",
        max_results: int = 10,
    ) -> list[RawArticle]:
        if not self.api_key:
            return []

        # Tianapi does not support keyword filtering in this endpoint.
        response = await self.client.get(
            self.endpoint,
            params={"key": self.api_key, "num": max_results},
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()

        result = payload.get("result", payload)
        items = (result.get("newslist") if isinstance(result, dict) else None) or []
        if not isinstance(items, list):
            raise ValueError("invalid tianapi payload: result.newslist is not a list")

        articles: list[RawArticle] = []
        for item in items:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            if not title or not url:
                continue
            articles.append(
                RawArticle(
                    title=title,
                    url=url,
                    snippet=(item.get("description") or "").strip(),
                    source_type=self.source_type,
                    source_name=item.get("source"),
                    language=self.language,
                    published_at=self.parse_datetime(item.get("ctime")),
                )
            )
        return articles
