from __future__ import annotations

from app.providers.registry import ProviderRegistry


class FallbackChain:
    def __init__(self, ordered: list[str] | None = None) -> None:
        self.ordered = ordered or ["gemini", "openai", "ollama"]

    def get_chain(self, preferred: str | None, registry: ProviderRegistry) -> list[str]:
        names = [name for name in self.ordered if name in registry.list_providers()]
        if preferred and preferred in names:
            names.remove(preferred)
            return [preferred, *names]
        return names
