from __future__ import annotations

from app.providers.base import ProviderCapability
from app.providers.registry import ProviderRegistry
from app.schemas.ai import EmbeddingRequest, EmbeddingResponse
from app.services.usage_tracker import record_usage
from app.utils.fallback import FallbackChain, call_with_retry


class EmbeddingService:
    def __init__(self, registry: ProviderRegistry, fallback: FallbackChain) -> None:
        self.registry = registry
        self.fallback = fallback

    async def embedding(self, payload: EmbeddingRequest) -> EmbeddingResponse:
        providers = self.fallback.get_chain_for_capability(
            payload.provider, self.registry, ProviderCapability.EMBEDDING,
        )
        if not providers:
            providers = self.fallback.get_chain(payload.provider, self.registry)

        last_error: Exception | None = None
        for name in providers:
            provider = self.registry.get(name)
            model = payload.model or provider.default_embedding_model
            if not model:
                continue
            try:
                embeddings, usage = await call_with_retry(
                    provider.embedding, payload.texts, model,
                )
                record_usage(name, model, usage)
                return EmbeddingResponse(embeddings=embeddings, provider=name, model=model, usage=usage)
            except NotImplementedError:
                continue
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"all embedding providers failed: {last_error}")
