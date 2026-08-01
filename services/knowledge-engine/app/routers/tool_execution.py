"""Closed canonical operation API over the shared registered-tool executor."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.tool_execution import ToolExecutionFailure, execute_registered_tool, operation_tool

router = APIRouter(prefix="/api/v1/mcp/execute", tags=["tool-execution"])


async def request_args(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return None


def failure_response(exc: ToolExecutionFailure) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.body())


@router.post("/{operation_id}")
async def execute_operation(operation_id: str, request: Request) -> Any:
    try:
        tool_name = operation_tool(operation_id)
        return await execute_registered_tool(
            tool_name=tool_name,
            args=await request_args(request),
            route_family="canonical_operation",
        )
    except ToolExecutionFailure as exc:
        return failure_response(exc)
