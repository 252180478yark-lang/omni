from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.providers.registry import ProviderRegistry


def _config_path() -> Path:
    return Path(settings.provider_config_path)


def _read_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_config(data: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def apply_persisted_provider_config(registry: ProviderRegistry) -> None:
    data = _read_config()
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        return

    for provider_name, provider_data in providers.items():
        if not isinstance(provider_data, dict):
            continue
        try:
            provider = registry.get(provider_name)
        except KeyError:
            continue

        api_key = provider_data.get("api_key")
        if isinstance(api_key, str):
            key_attr = {
                "openai": "openai_api_key",
                "gemini": "gemini_api_key",
                "anthropic": "anthropic_api_key",
                "deepseek": "deepseek_api_key",
                "seedance": "ark_api_key",
                "kling": "kling_api_key",
            }.get(provider_name)
            if key_attr:
                setattr(settings, key_attr, api_key.strip())

        default_chat_model = provider_data.get("default_chat_model")
        if isinstance(default_chat_model, str) and default_chat_model.strip():
            provider.default_chat_model = default_chat_model.strip()

        default_embedding_model = provider_data.get("default_embedding_model")
        if isinstance(default_embedding_model, str) and default_embedding_model.strip():
            provider.default_embedding_model = default_embedding_model.strip()


def persist_provider_config(
    *,
    provider: str,
    api_key: str | None = None,
    default_chat_model: str | None = None,
    default_embedding_model: str | None = None,
) -> None:
    data = _read_config()
    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        data["providers"] = providers

    provider_data = providers.get(provider)
    if not isinstance(provider_data, dict):
        provider_data = {}

    if api_key is not None:
        provider_data["api_key"] = api_key.strip()
    if default_chat_model is not None and default_chat_model.strip():
        provider_data["default_chat_model"] = default_chat_model.strip()
    if default_embedding_model is not None and default_embedding_model.strip():
        provider_data["default_embedding_model"] = default_embedding_model.strip()

    providers[provider] = provider_data
    _write_config(data)


def read_provider_config(provider: str) -> dict[str, Any]:
    data = _read_config()
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return {}
    value = providers.get(provider)
    return value if isinstance(value, dict) else {}
