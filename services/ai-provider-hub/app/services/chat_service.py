from __future__ import annotations

from collections.abc import AsyncGenerator

from app.providers.base import ProviderCapability
from app.providers.registry import ProviderRegistry
from app.schemas.ai import ChatRequest, ChatResponse, TokenUsage
from app.services.usage_tracker import record_usage
from app.utils.fallback import FallbackChain, call_with_retry


class ChatService:
    def __init__(self, registry: ProviderRegistry, fallback: FallbackChain) -> None:
        self.registry = registry
        self.fallback = fallback

    async def chat(self, payload: ChatRequest) -> ChatResponse:
        providers = self.fallback.get_chain_for_capability(
            payload.provider, self.registry, ProviderCapability.CHAT,
        )
        last_error: Exception | None = None
        for name in providers:
            provider = self.registry.get(name)
            model = payload.model or provider.default_chat_model
            try:
                result = await call_with_retry(
                    provider.chat, payload.messages, model,
                    temperature=payload.temperature, max_tokens=payload.max_tokens,
                )
                record_usage(name, model, result.usage)
                return result
            except NotImplementedError:
                continue
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"all chat providers failed: {last_error}")

    async def stream(self, payload: ChatRequest) -> AsyncGenerator[dict[str, object], None]:
        providers = self.fallback.get_chain_for_capability(
            payload.provider, self.registry, ProviderCapability.CHAT,
        )
        for name in providers:
            provider = self.registry.get(name)
            model = payload.model or provider.default_chat_model
            try:
                completion_tokens = 0
                async for chunk in provider.chat_stream(
                    payload.messages, model,
                    temperature=payload.temperature, max_tokens=payload.max_tokens,
                ):
                    completion_tokens += max(1, len(chunk) // 4)
                    yield {"content": chunk, "done": False}
                usage = TokenUsage(
                    prompt_tokens=1, completion_tokens=completion_tokens,
                    total_tokens=1 + completion_tokens,
                )
                record_usage(name, model, usage)
                yield {"content": "", "done": True, "usage": usage.model_dump()}
                return
            except Exception:
                continue
        yield {"content": "", "done": True, "usage": TokenUsage().model_dump()}
