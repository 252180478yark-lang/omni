"""Authenticated S10 session and attachment metadata API."""

from fastapi import APIRouter, Depends, HTTPException

from app.routers.runtime_traces import require_trace_access
from app.schemas.runtime_trace import AgentAttachmentInput, AgentAttachmentRecord, AgentSessionContractRecord, ProviderSessionContract
from app.services.agent_contracts import AgentContractStore, DatabaseAgentContractStore

router = APIRouter(prefix="/api/v1/agent-contracts", tags=["agent-contracts"], dependencies=[Depends(require_trace_access)])


def get_agent_contract_store() -> AgentContractStore:
    return DatabaseAgentContractStore()


def _conflict(exc: ValueError) -> HTTPException:
    code = str(exc)
    status = 404 if code == "agent_session_not_found" else 409
    return HTTPException(status_code=status, detail={"code": code})


@router.post("/sessions", response_model=AgentSessionContractRecord)
async def upsert_session(payload: ProviderSessionContract, store: AgentContractStore = Depends(get_agent_contract_store)):
    try:
        return await store.upsert_session(payload)
    except ValueError as exc:
        raise _conflict(exc) from exc


@router.get("/sessions/{session_id}", response_model=AgentSessionContractRecord)
async def get_session(session_id: str, store: AgentContractStore = Depends(get_agent_contract_store)):
    value = await store.get_session(session_id)
    if value is None:
        raise HTTPException(status_code=404, detail={"code": "agent_session_not_found"})
    return value


@router.post("/sessions/{session_id}/attachments", response_model=AgentAttachmentRecord)
async def record_attachment(session_id: str, payload: AgentAttachmentInput, store: AgentContractStore = Depends(get_agent_contract_store)):
    if session_id != payload.session_id:
        raise HTTPException(status_code=409, detail={"code": "agent_session_path_body_mismatch"})
    try:
        return await store.record_attachment(payload)
    except ValueError as exc:
        raise _conflict(exc) from exc
