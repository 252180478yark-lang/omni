from app.providers import (
    AnthropicProvider,
    DeepSeekProvider,
    GeminiProvider,
    KlingProvider,
    OllamaProvider,
    OpenAIProvider,
    SeedanceProvider,
    ProviderRegistry,
)
from app.services.analyze_service import AnalyzeService
from app.services.chat_service import ChatService
from app.services.embedding_service import EmbeddingService
from app.services.image_service import ImageService
from app.services.provider_config_store import apply_persisted_provider_config
from app.services.video_service import VideoService
from app.utils.fallback import FallbackChain

registry = ProviderRegistry()
fallback = FallbackChain()

chat_service = ChatService(registry=registry, fallback=fallback)
embedding_service = EmbeddingService(registry=registry, fallback=fallback)
image_service = ImageService(registry=registry, fallback=fallback)
video_service = VideoService(registry=registry, fallback=fallback)
analyze_service = AnalyzeService(registry=registry, fallback=fallback)


def bootstrap_providers() -> None:
    registry.register("gemini", GeminiProvider())
    registry.register("openai", OpenAIProvider())
    registry.register("anthropic", AnthropicProvider())
    registry.register("deepseek", DeepSeekProvider())
    registry.register("ollama", OllamaProvider())
    registry.register("seedance", SeedanceProvider())
    registry.register("kling", KlingProvider())
    apply_persisted_provider_config(registry)