from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import feedparser

from app.sources.base import BaseFetcher, RawArticle, handle_fetch_errors

logger = logging.getLogger(__name__)


class RssFetcher(BaseFetcher):
    """从 RSS/Atom feed 抓取文章，不需要 API Key。

    feed_urls 通过 settings.rss_feed_urls 传入，格式为逗号分隔的 URL 列表。
    keywords 用于对 title/summary 做简单过滤（空列表时不过滤）。
    """

    source_type = "rss"
    language = "zh"

    def __init__(self, client, api_key: str, feed_urls: list[str] | None = None):
        super().__init__(client, api_key)
        self.feed_urls: list[str] = feed_urls or []

    @handle_fetch_errors(source_type)
    async def fetch(
        self,
        keywords: list[str],
        freshness: str = "oneDay",
        max_results: int = 10,
    ) -> list[RawArticle]:
        if not self.feed_urls:
            return []

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, self._parse_feed, url)
            for url in self.feed_urls
        ]
        chunks = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[RawArticle] = []
        for chunk in chunks:
            if isinstance(chunk, Exception):
                logger.warning("RSS parse error: %s", chunk)
                continue
            articles.extend(chunk)

        # 关键词过滤（不区分大小写，有一个匹配即保留）
        if keywords:
            kw_lower = [k.lower() for k in keywords]
            articles = [
                a for a in articles
                if any(kw in (a.title + " " + a.snippet).lower() for kw in kw_lower)
            ]

        return articles[:max_results]

    def _parse_feed(self, url: str) -> list[RawArticle]:
        feed = feedparser.parse(url)
        results: list[RawArticle] = []
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            source_name = feed.feed.get("title", url)
            published_at = self._parse_feed_date(entry)

            if not title or not link:
                continue

            results.append(
                RawArticle(
                    title=title,
                    url=link,
                    snippet=summary[:500],
                    source_type="rss",
                    source_name=source_name,
                    language="zh",
                    published_at=published_at,
                )
            )
        return results

    @staticmethod
    def _parse_feed_date(entry) -> datetime | None:
        import time as _time
        raw = entry.get("published_parsed") or entry.get("updated_parsed")
        if raw:
            try:
                ts = _time.mktime(raw)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass
        raw_str = entry.get("published") or entry.get("updated")
        if raw_str:
            return BaseFetcher.parse_datetime(raw_str)
        return None
