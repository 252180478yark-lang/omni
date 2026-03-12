import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.runtime import (
    analyze_service,
    chat_service,
    embedding_service,
    image_service,
    registry,
    video_service,
)
from app.schemas.ai import (
    AnalyzeRequest,
    ChatRequest,
    EmbeddingRequest,
    ImageGenerateRequest,
    VideoGenerateRequest,
)
from app.services.provider_config_store import persist_provider_config, read_provider_config
from app.services.redis_client import check_rate_limit, get_daily_cost
from app.services.usage_tracker import latest_usage

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


async def _rate_limit_guard(request: Request) -> None:
    """Dependency that enforces per-provider rate limiting (60 req/min)."""
    body_bytes = await request.body()
    provider = "global"
    try:
        body = json.loads(body_bytes)
        provider = body.get("provider") or "global"
    except Exception:
        pass
    allowed = await check_rate_limit(provider, window_seconds=60, max_requests=60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded for provider '{provider}'")


# ═══ Chat ═══

class ProviderConfigUpdateRequest(BaseModel):
    provider: str
    api_key: str | None = None
    default_chat_model: str | None = None
    default_embedding_model: str | None = None


class ProviderConnectionTestRequest(BaseModel):
    provider: str
    api_key: str | None = None


@router.post("/chat", dependencies=[Depends(_rate_limit_guard)])
async def chat(payload: ChatRequest):
    return (await chat_service.chat(payload)).model_dump()


@router.post("/chat/stream", dependencies=[Depends(_rate_limit_guard)])
async def chat_stream(payload: ChatRequest):
    async def event_gen() -> AsyncGenerator[dict[str, str], None]:
        async for chunk in chat_service.stream(payload):
            yield {"event": "message", "data": json.dumps(chunk, ensure_ascii=False)}

    return EventSourceResponse(event_gen())


# ═══ Embedding ═══

@router.post("/embedding", dependencies=[Depends(_rate_limit_guard)])
async def embedding(payload: EmbeddingRequest):
    return (await embedding_service.embedding(payload)).model_dump()


@router.post("/embeddings", dependencies=[Depends(_rate_limit_guard)])
async def embeddings_alias(payload: EmbeddingRequest):
    """Alias: /embeddings (plural) for spec compliance."""
    return (await embedding_service.embedding(payload)).model_dump()


# ═══ Image Generation (MOD-04) ═══

@router.post("/images/generate", dependencies=[Depends(_rate_limit_guard)])
async def generate_image(payload: ImageGenerateRequest):
    try:
        result = await image_service.generate(payload)
        return result.model_dump()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ═══ Video Generation (MOD-04) ═══

@router.post("/videos/generate", dependencies=[Depends(_rate_limit_guard)])
async def generate_video(payload: VideoGenerateRequest):
    try:
        result = await video_service.generate(payload)
        return result.model_dump()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/videos/status/{task_id}")
async def video_status(task_id: str):
    try:
        result = await video_service.get_status(task_id)
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ═══ Multimodal Analysis (MOD-04) ═══

@router.post("/analyze", dependencies=[Depends(_rate_limit_guard)])
async def analyze(payload: AnalyzeRequest):
    try:
        result = await analyze_service.analyze(payload)
        return result.model_dump()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ═══ Provider Management ═══

@router.get("/providers")
async def providers() -> dict:
    data = registry.list_providers()
    key_check = {
        "openai": lambda: bool(settings.openai_api_key),
        "gemini": lambda: bool(settings.gemini_api_key),
        "anthropic": lambda: bool(settings.anthropic_api_key),
        "deepseek": lambda: bool(settings.deepseek_api_key),
    }
    for name, item in data.items():
        checker = key_check.get(name)
        item["api_key_set"] = checker() if checker else True
    return {"providers": data}


@router.get("/models")
async def models() -> dict:
    data = []
    for name, item in registry.list_providers().items():
        provider = registry.get(name)
        model_list: list[str] = []
        list_models = getattr(provider, "list_models", None)
        if callable(list_models):
            try:
                listed = await list_models()
                if isinstance(listed, list):
                    model_list.extend(m for m in listed if isinstance(m, str) and m)
            except Exception:
                pass
        for fallback_model in [item["default_chat_model"], item["default_embedding_model"]]:
            if isinstance(fallback_model, str) and fallback_model:
                model_list.append(fallback_model)
        data.append({"provider": name, "models": list(dict.fromkeys(model_list))})
    return {"models": data}


@router.post("/config")
async def update_provider_config(payload: ProviderConfigUpdateRequest) -> dict:
    try:
        provider = registry.get(payload.provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    normalized_api_key: str | None = None
    if payload.api_key is not None:
        value = payload.api_key.strip()
        normalized_api_key = value
        key_setters = {"openai": "openai_api_key", "gemini": "gemini_api_key", "anthropic": "anthropic_api_key", "deepseek": "deepseek_api_key"}
        attr = key_setters.get(payload.provider)
        if attr:
            setattr(settings, attr, value)

    if payload.default_chat_model and payload.default_chat_model.strip():
        provider.default_chat_model = payload.default_chat_model.strip()
    if payload.default_embedding_model and payload.default_embedding_model.strip():
        provider.default_embedding_model = payload.default_embedding_model.strip()

    persist_provider_config(
        provider=payload.provider,
        api_key=normalized_api_key,
        default_chat_model=payload.default_chat_model,
        default_embedding_model=payload.default_embedding_model,
    )

    key_check = {"openai": "openai_api_key", "gemini": "gemini_api_key", "anthropic": "anthropic_api_key", "deepseek": "deepseek_api_key"}
    attr = key_check.get(payload.provider)
    api_key_set = bool(getattr(settings, attr)) if attr else True

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

    ok, message, model_list = await tester(api_key=payload.api_key)
    return {"success": ok, "provider": payload.provider, "message": message, "models": model_list}


# ═══ Cost / Usage (MOD-07) ═══

@router.get("/usage")
async def usage(limit: int = 20) -> dict:
    return {"usage": latest_usage(limit)}


@router.get("/cost/daily/{provider}")
async def cost_daily(provider: str, date: str | None = None) -> dict:
    date_str = date or datetime.now(UTC).strftime("%Y-%m-%d")
    data = await get_daily_cost(provider, date_str)
    return {"provider": provider, "date": date_str, "cost": data}


@router.get("/provider-secrets/{provider}")
async def provider_secrets(provider: str) -> dict:
    try:
        registry.get(provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    persisted = read_provider_config(provider)
    key_map = {"openai": "openai_api_key", "gemini": "gemini_api_key", "anthropic": "anthropic_api_key", "deepseek": "deepseek_api_key"}
    attr = key_map.get(provider)
    api_key = getattr(settings, attr, "") if attr else ""

    if isinstance(persisted.get("api_key"), str) and persisted["api_key"].strip():
        api_key = persisted["api_key"].strip()

    return {
        "provider": provider,
        "api_key": (api_key or "").strip(),
        "default_chat_model": persisted.get("default_chat_model"),
        "default_embedding_model": persisted.get("default_embedding_model"),
    }
