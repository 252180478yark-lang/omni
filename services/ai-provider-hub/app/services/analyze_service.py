from __future__ import annotations

from app.providers.base import ProviderCapability
from app.providers.registry import ProviderRegistry
from app.schemas.ai import AnalyzeRequest, AnalyzeResponse, Message, TokenUsage
from app.utils.fallback import FallbackChain, call_with_retry


class AnalyzeService:
    def __init__(self, registry: ProviderRegistry, fallback: FallbackChain) -> None:
        self.registry = registry
        self.fallback = fallback

    async def analyze(self, payload: AnalyzeRequest) -> AnalyzeResponse:
        providers = self.fallback.get_chain_for_capability(
            payload.provider, self.registry, ProviderCapability.ANALYSIS,
        )
        if not providers:
            providers = self.fallback.get_chain(payload.provider, self.registry)

        last_error: Exception | None = None
        for name in providers:
            provider = self.registry.get(name)
            model = payload.model or provider.default_chat_model
            try:
                result = await call_with_retry(
                    provider.analyze,
                    content=payload.content, prompt=payload.prompt, model=model,
                    content_type=payload.type,
                )
                return AnalyzeResponse(
                    analysis=result.get("analysis", ""),
                    structured_data=result.get("structured_data", {}),
                    provider=name,
                    model=model,
                    usage=TokenUsage(**result["usage"]) if "usage" in result else TokenUsage(),
                )
            except NotImplementedError:
                try:
                    messages = [
                        Message(role="system", content=f"You are analyzing {payload.type} content. Provide detailed analysis."),
                        Message(role="user", content=f"{payload.prompt}\n\nContent: {payload.content}"),
                    ]
                    chat_result = await call_with_retry(provider.chat, messages, model)
                    return AnalyzeResponse(
                        analysis=chat_result.content,
                        structured_data={},
                        provider=name,
                        model=model,
                        usage=chat_result.usage,
                    )
                except Exception as exc:
                    last_error = exc
                    continue
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"No analysis provider available: {last_error}")
