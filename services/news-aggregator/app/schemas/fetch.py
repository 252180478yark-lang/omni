from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FetchRequest(BaseModel):
    sources: list[str] | None = None
    keywords_override: list[str] | None = None
    freshness_override: str | None = None


class FetchResponse(BaseModel):
    job_id: UUID
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    sources_used: list[str] = Field(default_factory=list)
    total_fetched: int = 0
    after_dedup: int = 0
    after_enrich: int = 0
    started_at: datetime
    finished_at: datetime | None = None
    error_log: str | None = None


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse] = Field(default_factory=list)
