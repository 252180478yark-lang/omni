"""Compatibility adapter for the historical ``/mcp/exec/{tool_name}`` family."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.routers.tool_execution import failure_response, request_args
from app.services.tool_execution import ToolExecutionFailure, execute_registered_tool

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-exec-compatibility"])


class GenerateCharacterSheetsRequest(BaseModel):
    script_id: str
    role_ids: list[str] | None = None
    aspect_ratio: str = "1:1"
    experiment_arm_id: str | None = None


class GenerateVideoSegmentsRequest(BaseModel):
    script_id: str
    scene_nums: list[int] | None = None
    face_refs: list[str] | None = None
    product_refs: list[str] | None = None
    product_ref_asset_ids: list[str] | None = None
    aspect_ratio: str = "9:16"
    duration_s: int = 8
    use_last_frame: bool = False
    extra_prompt_suffix: str | None = None
    dry_run: bool = False
    legacy_mode: bool = False
    force_t2v: bool = False
    character_anchor: str | None = None
    model_override: str | None = None
    skip_first_frame_scene_nums: list[int] | None = None
    experiment_arm_id: str | None = None
    allow_no_product: bool = False


async def exec_generate_character_sheets(payload: GenerateCharacterSheetsRequest) -> Any:
    return await execute_registered_tool(
        tool_name="generate_character_sheets",
        args=payload.model_dump(),
        route_family="legacy_python_adapter",
    )


async def exec_generate_video_segments(payload: GenerateVideoSegmentsRequest) -> Any:
    return await execute_registered_tool(
        tool_name="generate_video_segments",
        args=payload.model_dump(),
        route_family="legacy_python_adapter",
    )


@router.post("/exec/{tool_name}")
async def exec_tool_compatibility(tool_name: str, request: Request) -> Any:
    """Deprecated adapter. The registry remains a whitelist, never arbitrary import."""

    try:
        return await execute_registered_tool(
            tool_name=tool_name,
            args=await request_args(request),
            route_family="legacy_exec",
        )
    except ToolExecutionFailure as exc:
        return failure_response(exc)
