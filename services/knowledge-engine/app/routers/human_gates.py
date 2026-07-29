"""REST router for mcp.human_gates (W4-B 切片 2).

3 endpoint：
- GET  /api/v1/mcp/human-gates                      列待批
- POST /api/v1/mcp/human-gates/{id}/approve         批（含 short_id 解析）
- POST /api/v1/mcp/human-gates/{id}/reject          驳

错误格式（gate_not_found / ambiguous_short_id / already_decided）由 service layer
返 {ok:false, error:..., hint:...}；router 直接 JSONResponse 透传。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.schemas.human_gates import ApproveRequest
from app.routers.approval_operations import get_approval_principal
from app.services.approval_operations import ApprovalOperationException, ApprovalPrincipal
from app.services.inbox_service import (
    approve_gate,
    list_pending,
    reject_gate,
)

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-human-gates"])


@router.get("/human-gates")
async def list_gates(principal: ApprovalPrincipal = Depends(get_approval_principal)):
    if not principal.can("approval:read:any"):
        raise HTTPException(status_code=403, detail={"code": "approval_read_forbidden"})
    try:
        return await list_pending()
    except ApprovalOperationException as exc:
        return JSONResponse(
            status_code=exc.status,
            content={"ok": False, "error": exc.code, "retryable": exc.retryable},
        )


@router.post("/human-gates/{gate_id}/approve")
async def approve_endpoint(
    gate_id: str,
    payload: ApproveRequest,
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    if not principal.can("approval:decide"):
        raise HTTPException(status_code=403, detail={"code": "approval_decide_forbidden"})
    result = await approve_gate(gate_id, payload.note, actor_id=principal.principal_id)
    if not result.get("ok"):
        code = _error_to_status(result.get("error"))
        return JSONResponse(content=result, status_code=code)
    return result


# W5-B 切片 1.10: /approved alias（前端 ws-handler 用 POST .../approved）
@router.post("/human-gates/{gate_id}/approved")
async def approved_endpoint(
    gate_id: str,
    payload: ApproveRequest,
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    if not principal.can("approval:decide"):
        raise HTTPException(status_code=403, detail={"code": "approval_decide_forbidden"})
    result = await approve_gate(gate_id, payload.note, actor_id=principal.principal_id)
    if not result.get("ok"):
        code = _error_to_status(result.get("error"))
        return JSONResponse(content=result, status_code=code)
    return result


@router.post("/human-gates/{gate_id}/reject")
async def reject_endpoint(
    gate_id: str,
    payload: ApproveRequest,
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    if not principal.can("approval:decide"):
        raise HTTPException(status_code=403, detail={"code": "approval_decide_forbidden"})
    result = await reject_gate(gate_id, payload.note, actor_id=principal.principal_id)
    if not result.get("ok"):
        code = _error_to_status(result.get("error"))
        return JSONResponse(content=result, status_code=code)
    return result


# W5-B 切片 1.10: /rejected alias（前端 ws-handler 用 POST .../rejected）
@router.post("/human-gates/{gate_id}/rejected")
async def rejected_endpoint(
    gate_id: str,
    payload: ApproveRequest,
    principal: ApprovalPrincipal = Depends(get_approval_principal),
):
    if not principal.can("approval:decide"):
        raise HTTPException(status_code=403, detail={"code": "approval_decide_forbidden"})
    result = await reject_gate(gate_id, payload.note, actor_id=principal.principal_id)
    if not result.get("ok"):
        code = _error_to_status(result.get("error"))
        return JSONResponse(content=result, status_code=code)
    return result


def _error_to_status(err: str | None) -> int:
    if err == "gate_not_found":
        return 404
    if err == "ambiguous_short_id":
        return 400
    if err == "already_decided":
        return 409
    return 400
