from __future__ import annotations

from app.config import settings
from app.providers.base import BaseProvider


class ProviderRegistry:
    _instance: "ProviderRegistry | None" = None

    def __new__(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
        return cls._instance

    def register(self, name: str, provider: BaseProvider) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> BaseProvider:
        if name not in self._providers:
            raise KeyError(f"provider not found: {name}")
        return self._providers[name]

    def get_default(self, task: str) -> BaseProvider:
        if task == "chat":
            return self.get(settings.default_chat_provider)
        return self.get(settings.default_embedding_provider)

    def list_providers(self) -> dict[str, dict[str, object]]:
        data: dict[str, dict[str, object]] = {}
        for name, provider in self._providers.items():
            data[name] = {
                "capabilities": sorted([cap.value for cap in provider.capabilities]),
                "default_chat_model": provider.default_chat_model,
                "default_embedding_model": provider.default_embedding_model,
            }
        return data
