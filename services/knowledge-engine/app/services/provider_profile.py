from __future__ import annotations

import httpx

from app.config import settings

_PREFERRED_ORDER = ["openai", "gemini", "ollama"]


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
    candidates = [name for name in _PREFERRED_ORDER if name in providers]
    for name in candidates:
        info = providers.get(name, {})
        if not isinstance(info, dict):
            continue
        capabilities = info.get("capabilities", [])
        if not isinstance(capabilities, list) or "embedding" not in capabilities:
            continue
        if bool(info.get("api_key_set")):
            return name
    for name in candidates:
        info = providers.get(name, {})
        if not isinstance(info, dict):
            continue
        capabilities = info.get("capabilities", [])
        if isinstance(capabilities, list) and "embedding" in capabilities:
            return name
    return None
