from __future__ import annotations

from app.providers.base import ProviderCapability
from app.providers.registry import ProviderRegistry
from app.schemas.ai import ImageGenerateRequest, ImageGenerateResponse
from app.utils.fallback import FallbackChain, call_with_retry


class ImageService:
    def __init__(self, registry: ProviderRegistry, fallback: FallbackChain) -> None:
        self.registry = registry
        self.fallback = fallback

    async def generate(self, payload: ImageGenerateRequest) -> ImageGenerateResponse:
        providers = self.fallback.get_chain_for_capability(
            payload.provider, self.registry, ProviderCapability.IMAGE_GENERATION,
        )
        last_error: Exception | None = None
        for name in providers:
            provider = self.registry.get(name)
            model = payload.model or "dall-e-3"
            try:
                result = await call_with_retry(
                    provider.generate_image,
                    prompt=payload.prompt, model=model,
                    size=payload.size, quality=payload.quality, n=payload.n,
                )
                return ImageGenerateResponse(
                    images=result.get("images", []),
                    provider=name,
                    model=model,
                    usage=result.get("usage", {}),
                )
            except NotImplementedError:
                continue
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"No image generation provider available: {last_error}")
