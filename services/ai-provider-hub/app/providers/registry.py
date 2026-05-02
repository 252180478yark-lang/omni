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
        # 媒体类 provider 没有传统的 chat 模型；用 settings 里的实际默认模型回填
        # default_chat_model 字段，前端 UI 会按 capabilities 改成"默认图像/视频模型"显示。
        media_default_overrides = {
            "seedream": (settings.seedream_model or "").strip(),
            "seedance": (settings.seedance_model or "").strip(),
        }
        data: dict[str, dict[str, object]] = {}
        for name, provider in self._providers.items():
            chat_default = provider.default_chat_model
            if not chat_default:
                chat_default = media_default_overrides.get(name, "") or ""
            data[name] = {
                "capabilities": sorted([cap.value for cap in provider.capabilities]),
                "default_chat_model": chat_default,
                "default_embedding_model": provider.default_embedding_model,
            }
        return data
