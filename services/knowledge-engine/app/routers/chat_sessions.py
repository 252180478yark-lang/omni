"""Chat sessions CRUD router.

Endpoints (prefix /api/v1/chat):
  POST   /sessions                 Create / upsert
  GET    /sessions                 List (paginated, optional search)
  GET    /sessions/{id}            Get session (meta only)
  GET    /sessions/{id}/messages   Get full message list
  PATCH  /sessions/{id}            Rename / update meta
  DELETE /sessions/{id}            Soft delete
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.chat_sessions import (
    append_message,
    delete_session,
    ensure_session,
    get_session,
    list_messages,
    list_sessions,
    maybe_auto_title,
    update_session,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat-sessions"])


class SessionCreateRequest(BaseModel):
    session_id: str = Field(min_length=1)
    title: str | None = None
    kb_ids: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    persona_id: str | None = None


class SessionUpdateRequest(BaseModel):
    title: str | None = None
    kb_ids: list[str] | None = None
    provider: str | None = None
    model: str | None = None
    persona_id: str | None = None


class MessageAppendRequest(BaseModel):
    """前端主动落库单条消息（用于无 KB 直连 AI 路径，RAG 路径已自动落库）。"""
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str = ""
    output_mode: str | None = None
    sources: list | None = None
    retrieval: dict | None = None
    images: list | None = None
    video: dict | None = None
    # 若会话不存在自动创建，用这些初始化 meta
    ensure_kb_ids: list[str] = Field(default_factory=list)
    ensure_provider: str | None = None
    ensure_model: str | None = None
    ensure_persona_id: str | None = None


@router.post("/sessions", status_code=status.HTTP_200_OK)
async def create_or_upsert_session(payload: SessionCreateRequest) -> dict:
    sess = await ensure_session(
        payload.session_id,
        kb_ids=payload.kb_ids,
        provider=payload.provider,
        model=payload.model,
        persona_id=payload.persona_id,
        title=payload.title,
    )
    return {"code": 200, "message": "success", "data": sess}


@router.get("/sessions")
async def list_sessions_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
) -> dict:
    items = await list_sessions(limit=limit, offset=offset, search=search)
    return {"code": 200, "message": "success", "data": items}


@router.get("/sessions/{session_id}")
async def get_session_endpoint(session_id: str) -> dict:
    sess = await get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return {"code": 200, "message": "success", "data": sess}


@router.get("/sessions/{session_id}/messages")
async def list_messages_endpoint(
    session_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict:
    sess = await get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    msgs = await list_messages(session_id, limit=limit)
    return {"code": 200, "message": "success", "data": {"session": sess, "messages": msgs}}


@router.patch("/sessions/{session_id}")
async def update_session_endpoint(session_id: str, payload: SessionUpdateRequest) -> dict:
    sess = await update_session(
        session_id,
        title=payload.title,
        kb_ids=payload.kb_ids,
        provider=payload.provider,
        model=payload.model,
        persona_id=payload.persona_id,
    )
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return {"code": 200, "message": "success", "data": sess}


@router.delete("/sessions/{session_id}")
async def delete_session_endpoint(session_id: str) -> dict:
    ok = await delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return {"code": 200, "message": "success", "data": {"deleted": True}}


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_201_CREATED)
async def append_message_endpoint(session_id: str, payload: MessageAppendRequest) -> dict:
    """主动追加一条消息到会话。会话不存在时自动创建。"""
    await ensure_session(
        session_id,
        kb_ids=payload.ensure_kb_ids,
        provider=payload.ensure_provider,
        model=payload.ensure_model,
        persona_id=payload.ensure_persona_id,
    )
    new_id = await append_message(
        session_id,
        role=payload.role,
        content=payload.content,
        output_mode=payload.output_mode,
        sources=payload.sources,
        retrieval=payload.retrieval,
        images=payload.images,
        video=payload.video,
    )
    if payload.role == "user":
        await maybe_auto_title(session_id, payload.content)
    return {"code": 201, "message": "success", "data": {"id": new_id, "session_id": session_id}}
