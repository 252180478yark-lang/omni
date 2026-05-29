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
    """rating 不用 Literal——FastAPI Pydantic 422 会绕过 service 层的 invalid_rating 报错格式。

    2026-05-28 migration 031：加 category（向后兼容，不传 = None）。
    """

    rating: str
    note: str = Field(default="", max_length=500)
    category: str | None = None


class RateRecentRequest(BaseModel):
    """按 tool_name 评"最近一条"调用（桌面工具块 👍👎 用）。

    桌面只有 Claude 的 tool_use_id，跟 mcp.tool_calls.id 不是一回事且无链，
    所以按 tool_name 取最近一条解析 call_id（单人场景：评的就是刚看到那条）。
    """

    tool_name: str
    rating: str
    note: str = Field(default="", max_length=500)
    category: str | None = None
    within_minutes: int = Field(default=120, ge=1, le=1440)


class RateResponse(BaseModel):
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    hint: str | None = None


class MessageRateRequest(BaseModel):
    """POST /api/v1/mcp/messages/rate body — 对应 rate_message tool。

    rating/category 不用 Literal — service 层会返 {ok:false, error:invalid_rating}
    走错误透传协议，比 Pydantic 422 更易前端解析。
    """

    session_id: str
    message_id: str
    rating: str
    category: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    message_text_snapshot: str | None = None
    tool_use_ids: list[str] | None = None
    client: str = "desktop"
