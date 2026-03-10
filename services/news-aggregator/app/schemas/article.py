from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ArticleStatus = Literal["pending", "archived", "dismissed"]


class ArticleResponse(BaseModel):
    id: UUID
    title: str
    url: str
    source: str
    source_name: str | None = None
    raw_snippet: str | None = None
    ai_summary: str | None = None
    ai_tags: list[str] = Field(default_factory=list)
    ai_relevance_score: float
    status: ArticleStatus
    is_starred: bool
    language: str
    published_at: datetime | None = None
    fetched_at: datetime
    archived_at: datetime | None = None
    kb_doc_id: str | None = None
    fetch_job_id: UUID | None = None


class ArticleListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ArticleResponse] = Field(default_factory=list)


class ArticlePatch(BaseModel):
    status: ArticleStatus | None = None
    is_starred: bool | None = None
