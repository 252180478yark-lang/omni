from __future__ import annotations

import httpx

from app.config import settings

_FALLBACK_ORDER = ["gemini", "openai", "ollama"]


async def resolve_embedding_profile(
    *,
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
) -> tuple[str, str]:
    provider_name = (preferred_provider or "").strip()
    model_name = (preferred_model or "").strip()
    if provider_name and model_name:
        return provider_name, model_name

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.ai_provider_hub_url}/api/v1/ai/providers")
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return provider_name or settings.embedding_provider, model_name or settings.embedding_model

    providers = payload.get("providers", {})
    if not isinstance(providers, dict):
        return provider_name or settings.embedding_provider, model_name or settings.embedding_model

    if not provider_name:
        provider_name = _pick_provider(providers) or settings.embedding_provider

    info = providers.get(provider_name, {}) if isinstance(providers.get(provider_name, {}), dict) else {}
    if not model_name:
        default_model = info.get("default_embedding_model")
        if isinstance(default_model, str) and default_model.strip():
            model_name = default_model.strip()
        else:
            model_name = settings.embedding_model
    return provider_name, model_name


def _pick_provider(providers: dict) -> str | None:
    """Pick the best embedding provider.

    Priority:
    1. settings.embedding_provider (knowledge-engine config / env) if available
    2. Fallback order with api_key_set
    3. Fallback order without api_key_set
    """
    configured = settings.embedding_provider.strip()
    if configured and configured in providers:
        info = providers.get(configured, {})
        if isinstance(info, dict):
            caps = info.get("capabilities", [])
            if isinstance(caps, list) and "embedding" in caps and bool(info.get("api_key_set")):
                return configured

    candidates = [name for name in _FALLBACK_ORDER if name in providers]
    for name in candidates:
        info = providers.get(name, {})
        if not isinstance(info, dict):
            continue
        caps = info.get("capabilities", [])
        if not isinstance(caps, list) or "embedding" not in caps:
            continue
        if bool(info.get("api_key_set")):
            return name
    for name in candidates:
        info = providers.get(name, {})
        if not isinstance(info, dict):
            continue
        caps = info.get("capabilities", [])
        if isinstance(caps, list) and "embedding" in caps:
            return name
    return None
