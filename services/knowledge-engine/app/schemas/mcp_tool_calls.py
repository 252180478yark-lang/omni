"""Schemas for /api/v1/mcp/tool-calls REST router (W4-B 切片 1)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolCallRow(BaseModel):
    id: str
    tool_name: str
    status: str
    require_approval: bool
    duration_ms: int | None = None
    user_rating: str | None = None
    rating_note: str | None = None
    model_used: str | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class Summary24h(BaseModel):
    total: int
    success_rate: float
    avg_duration_ms: int | None
    pending_count: int
    rating_dist: dict[str, int]


class ToolCallListResponse(BaseModel):
    data: list[ToolCallRow]
    total: int
    summary_24h: Summary24h


class ToolCallDetailResponse(BaseModel):
    data: ToolCallRow


class RateRequest(BaseModel):
    """rating 不用 Literal——FastAPI Pydantic 422 会绕过 service 层的 invalid_rating 报错格式。"""

    rating: str
    note: str = Field(default="", max_length=500)


class RateResponse(BaseModel):
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    hint: str | None = None
