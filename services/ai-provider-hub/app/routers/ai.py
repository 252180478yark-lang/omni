import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.runtime import chat_service, embedding_service, registry
from app.schemas.ai import ChatRequest, EmbeddingRequest

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


class ProviderConfigUpdateRequest(BaseModel):
    provider: str
    api_key: str | None = None
    default_chat_model: str | None = None
    default_embedding_model: str | None = None


class ProviderConnectionTestRequest(BaseModel):
    provider: str
    api_key: str | None = None


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
    data = registry.list_providers()
    for name, item in data.items():
        if name == "openai":
            item["api_key_set"] = bool(settings.openai_api_key)
        elif name == "gemini":
            item["api_key_set"] = bool(settings.gemini_api_key)
        else:
            item["api_key_set"] = True
    return {"providers": data}


@router.get("/models")
async def models() -> dict:
    data = []
    for name, item in registry.list_providers().items():
        provider = registry.get(name)
        models: list[str] = []
        list_models = getattr(provider, "list_models", None)
        if callable(list_models):
            try:
                listed = await list_models()
                if isinstance(listed, list):
                    models.extend([m for m in listed if isinstance(m, str) and m])
            except Exception:
                pass
        for fallback_model in [item["default_chat_model"], item["default_embedding_model"]]:
            if isinstance(fallback_model, str) and fallback_model:
                models.append(fallback_model)
        # keep order while removing duplicates
        deduped = list(dict.fromkeys(models))
        models = deduped
        data.append({"provider": name, "models": models})
    return {"models": data}


@router.post("/config")
async def update_provider_config(payload: ProviderConfigUpdateRequest) -> dict:
    try:
        provider = registry.get(payload.provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.api_key is not None:
        value = payload.api_key.strip()
        if payload.provider == "openai":
            settings.openai_api_key = value
        elif payload.provider == "gemini":
            settings.gemini_api_key = value

    if payload.default_chat_model is not None and payload.default_chat_model.strip():
        provider.default_chat_model = payload.default_chat_model.strip()
    if payload.default_embedding_model is not None and payload.default_embedding_model.strip():
        provider.default_embedding_model = payload.default_embedding_model.strip()

    api_key_set = True
    if payload.provider == "openai":
        api_key_set = bool(settings.openai_api_key)
    elif payload.provider == "gemini":
        api_key_set = bool(settings.gemini_api_key)

    return {
        "success": True,
        "provider": payload.provider,
        "default_chat_model": provider.default_chat_model,
        "default_embedding_model": provider.default_embedding_model,
        "api_key_set": api_key_set,
    }


@router.post("/test-connection")
async def test_provider_connection(payload: ProviderConnectionTestRequest) -> dict:
    try:
        provider = registry.get(payload.provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    tester = getattr(provider, "test_connection", None)
    if not callable(tester):
        return {"success": False, "provider": payload.provider, "message": "provider does not support connection test", "models": []}

    ok, message, models = await tester(api_key=payload.api_key)
    return {"success": ok, "provider": payload.provider, "message": message, "models": models}

