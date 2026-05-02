from __future__ import annotations

from app.config import settings
from app.providers.base import ProviderCapability
from app.providers.registry import ProviderRegistry
from app.schemas.ai import ImageGenerateRequest, ImageGenerateResponse
from app.utils.fallback import FallbackChain, call_with_retry


class ImageService:
    def __init__(self, registry: ProviderRegistry, fallback: FallbackChain) -> None:
        self.registry = registry
        self.fallback = fallback

    async def generate(self, payload: ImageGenerateRequest) -> ImageGenerateResponse:
        if payload.provider:
            # Explicit provider selection is used for acceptance testing. Do not
            # silently fall back to a mock-capable provider and mask real failures.
            providers = [payload.provider]
        else:
            providers = [
                name.strip()
                for name in settings.image_provider_chain.split(",")
                if name.strip()
            ]
        last_error: Exception | None = None
        for name in providers:
            try:
                provider = self.registry.get(name)
            except KeyError:
                continue
            model = payload.model
            if not model or model == "gpt-image-2":
                model = provider.default_chat_model or "gpt-image-2"
            try:
                result = await call_with_retry(
                    provider.generate_image,
                    prompt=payload.prompt, model=model,
                    size=payload.size, quality=payload.quality, n=payload.n,
                    reference_images=payload.reference_images,
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
