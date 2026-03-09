from app.providers import GeminiProvider, OllamaProvider, OpenAIProvider, ProviderRegistry
from app.services.chat_service import ChatService
from app.services.embedding_service import EmbeddingService
from app.utils.fallback import FallbackChain

registry = ProviderRegistry()
fallback = FallbackChain()
chat_service = ChatService(registry=registry, fallback=fallback)
embedding_service = EmbeddingService(registry=registry, fallback=fallback)


def bootstrap_providers() -> None:
    registry.register("gemini", GeminiProvider())
    registry.register("openai", OpenAIProvider())
    registry.register("ollama", OllamaProvider())
