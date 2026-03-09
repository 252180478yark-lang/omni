import json
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.schemas.openai_compat import ChatCompletionRequest, EmbeddingItem, EmbeddingRequest
from app.schemas.ai import ChatRequest, EmbeddingRequest as NativeEmbeddingRequest, Message
from app.runtime import chat_service, embedding_service

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


async def _stream_chunks(payload: ChatCompletionRequest) -> AsyncGenerator[dict, None]:
    req = ChatRequest(
        messages=[Message(role=m.role, content=m.content) for m in payload.messages],
        provider=None,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    async for chunk in chat_service.stream(req):
        if chunk.get("done"):
            yield {
                "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                "usage": chunk.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
            }
        else:
            yield {"choices": [{"delta": {"content": chunk.get("content", "")}, "index": 0, "finish_reason": None}]}


@router.post("/chat/completions")
async def chat_completions(payload: ChatCompletionRequest, response: Response):
    # Keep global buffering on; disable buffering only for streaming endpoint.
    if payload.stream:
        response.headers["X-Accel-Buffering"] = "no"

        async def event_gen() -> AsyncGenerator[dict[str, str], None]:
            async for chunk in _stream_chunks(payload):
                yield {"event": "message", "data": json.dumps(chunk, ensure_ascii=False)}
            yield {"event": "message", "data": "[DONE]"}

        return EventSourceResponse(event_gen())

    req = ChatRequest(
        messages=[Message(role=m.role, content=m.content) for m in payload.messages],
        provider=None,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    result = await chat_service.chat(req)
    return JSONResponse(
        {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": result.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": result.content}, "finish_reason": "stop"}],
            "usage": result.usage.model_dump(),
        }
    )


@router.post("/embeddings")
async def embeddings(payload: EmbeddingRequest):
    texts = [payload.input] if isinstance(payload.input, str) else payload.input
    result = await embedding_service.embedding(NativeEmbeddingRequest(texts=texts, model=payload.model))
    data = [EmbeddingItem(index=idx, embedding=embedding).model_dump() for idx, embedding in enumerate(result.embeddings)]
    return {"object": "list", "model": result.model, "data": data, "usage": result.usage.model_dump()}
