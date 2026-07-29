"""Schemas for /api/v1/mcp/human-gates REST router (W4-B 切片 2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GateRow(BaseModel):
    """mcp.human_gates 一行（带 join 出来的 tool_name / args 摘要）。"""
    id: str
    short_id: str  # id[:8] 给前端按钮当展示
    tool_call_id: str | None = None
    operation_id: str | None = None
    operation_state: str | None = None
    tool_name: str | None = None
    summary: str
    args_preview: dict[str, Any] | None = None
    timeout_seconds: int
    created_at: datetime
    age_seconds: int  # NOW() - created_at，前端展示 "X 分钟前"


class ListPendingResponse(BaseModel):
    data: list[GateRow]
    total: int


class ApproveRequest(BaseModel):
    """approve / reject 共用：note 选填，max 500."""
    note: str = Field(default="", max_length=500)


class GateActionResponse(BaseModel):
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    hint: str | None = None
