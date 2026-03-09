import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.runtime import chat_service, embedding_service, registry
from app.schemas.ai import ChatRequest, EmbeddingRequest

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@router.post("/chat")
async def chat(payload: ChatRequest):
    return (await chat_service.chat(payload)).model_dump()


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    async def event_gen() -> AsyncGenerator[dict[str, str], None]:
        async for chunk in chat_service.stream(payload):
            yield {"event": "message", "data": json.dumps(chunk, ensure_ascii=False)}

    return EventSourceResponse(event_gen())


@router.post("/embedding")
async def embedding(payload: EmbeddingRequest):
    return (await embedding_service.embedding(payload)).model_dump()


@router.get("/providers")
async def providers() -> dict:
    return {"providers": registry.list_providers()}


@router.get("/models")
async def models() -> dict:
    data = []
    for name, item in registry.list_providers().items():
        models = [m for m in [item["default_chat_model"], item["default_embedding_model"]] if m]
        data.append({"provider": name, "models": models})
    return {"models": data}

