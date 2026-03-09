from __future__ import annotations

import asyncio

import httpx

from app.config import settings


async def embed_texts(texts: list[str], model: str, provider: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    provider_name = provider or settings.embedding_provider
    all_vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for start in range(0, len(texts), settings.embedding_batch_size):
            batch = texts[start : start + settings.embedding_batch_size]
            vectors = await _embed_batch_with_retry(client, batch, model, provider_name)
            all_vectors.extend(vectors)
    return all_vectors


async def _embed_batch_with_retry(client: httpx.AsyncClient, texts: list[str], model: str, provider: str) -> list[list[float]]:
    delay = 0.4
    last_error: Exception | None = None
    for _ in range(3):
        try:
            resp = await client.post(
                f"{settings.ai_provider_hub_url}/api/v1/ai/embedding",
                json={"texts": texts, "model": model, "provider": provider},
            )
            resp.raise_for_status()
            return resp.json()["embeddings"]
        except Exception as exc:  # pragma: no cover
            last_error = exc
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError(f"embedding request failed after retries: {last_error}")
