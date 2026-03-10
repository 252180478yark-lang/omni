from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class BatchArchiveRequest(BaseModel):
    article_ids: list[str] = Field(default_factory=list)
    action: Literal["archive", "dismiss"]


class BatchArchiveResponse(BaseModel):
    updated_count: int
    archived_to_kb: int
    failed_ids: list[str] = Field(default_factory=list)


class ArchiveStatsResponse(BaseModel):
    total_archived: int
    by_source: dict[str, int] = Field(default_factory=dict)
    top_tags: list[dict[str, int | str]] = Field(default_factory=list)
    recent_7d_count: int
    kb_synced_count: int = 0
    kb_pending_count: int = 0


class ArchiveSearchFilters(BaseModel):
    source: str = "all"
    language: str = "all"
    tags: list[str] = Field(default_factory=list)
    search: str | None = None
    is_starred: bool | None = None
    date_from: date | None = None
    date_to: date | None = None
    sort_by: Literal["archived_at", "published_at", "ai_relevance_score"] = "archived_at"
    sort_order: Literal["asc", "desc"] = "desc"
    page: int = 1
    page_size: int = 20


class TagListResponse(BaseModel):
    tags: list[dict[str, int | str]] = Field(default_factory=list)


class RetryKbRequest(BaseModel):
    article_ids: list[str] = Field(default_factory=list)


class RetryKbResponse(BaseModel):
    retried: int
    success: int
    failed_ids: list[str] = Field(default_factory=list)
