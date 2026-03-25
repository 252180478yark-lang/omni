"""Embedding client with Redis caching (MOD-07).

Cache key: embed:cache:{sha256(model + ":" + text)}
TTL: 7 days
Saves ~60-80% of embedding API calls for repeated text.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_CACHE_TTL = 7 * 24 * 3600  # 7 days
_redis_client = None


def _get_redis():
    """Lazy-init async Redis client."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
        return _redis_client
    except Exception:
        logger.warning("Redis unavailable, embedding cache disabled", exc_info=True)
        return None


def _cache_key(text: str, model: str) -> str:
    raw = f"{model}:{text}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"embed:cache:{h}"


async def _get_cached(keys: list[str]) -> dict[str, list[float] | None]:
    """Batch-get cached embeddings from Redis."""
    r = _get_redis()
    if r is None:
        return {k: None for k in keys}
    try:
        values = await r.mget(keys)
        result: dict[str, list[float] | None] = {}
        for k, v in zip(keys, values):
            if v is not None:
                result[k] = json.loads(v)
            else:
                result[k] = None
        return result
    except Exception:
        logger.debug("Redis cache read failed", exc_info=True)
        return {k: None for k in keys}


async def _set_cached(mapping: dict[str, list[float]]) -> None:
    """Batch-set embeddings into Redis cache."""
    r = _get_redis()
    if r is None or not mapping:
        return
    try:
        pipe = r.pipeline(transaction=False)
        for key, vec in mapping.items():
            pipe.setex(key, _CACHE_TTL, json.dumps(vec))
        await pipe.execute()
    except Exception:
        logger.debug("Redis cache write failed", exc_info=True)


async def embed_texts(texts: list[str], model: str, provider: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    provider_name = provider or settings.embedding_provider

    # Check cache
    cache_keys = [_cache_key(t, model) for t in texts]
    cached = await _get_cached(cache_keys)

    # Split into cached hits and misses
    results: list[list[float] | None] = [None] * len(texts)
    miss_indices: list[int] = []
    miss_texts: list[str] = []
    cache_hits = 0

    for i, (t, ck) in enumerate(zip(texts, cache_keys)):
        vec = cached.get(ck)
        if vec is not None:
            results[i] = vec
            cache_hits += 1
        else:
            miss_indices.append(i)
            miss_texts.append(t)

    if cache_hits > 0:
        logger.debug("Embedding cache: %d hits, %d misses", cache_hits, len(miss_texts))

    # Fetch missing embeddings from ai-provider-hub
    if miss_texts:
        all_miss_vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for start in range(0, len(miss_texts), settings.embedding_batch_size):
                batch = miss_texts[start : start + settings.embedding_batch_size]
                vectors = await _embed_batch_with_retry(client, batch, model, provider_name)
                all_miss_vectors.extend(vectors)

        # Fill results and prepare cache writes
        to_cache: dict[str, list[float]] = {}
        for idx_in_miss, orig_idx in enumerate(miss_indices):
            vec = all_miss_vectors[idx_in_miss]
            results[orig_idx] = vec
            to_cache[cache_keys[orig_idx]] = vec

        await _set_cached(to_cache)

    return [v for v in results if v is not None]


_EMBED_SEMAPHORE = asyncio.Semaphore(3)


async def _embed_batch_with_retry(
    client: httpx.AsyncClient, texts: list[str], model: str, provider: str,
) -> list[list[float]]:
    delay = 2.0
    last_error: Exception | None = None
    for attempt in range(6):
        async with _EMBED_SEMAPHORE:
            try:
                resp = await client.post(
                    f"{settings.ai_provider_hub_url}/api/v1/ai/embeddings",
                    json={"texts": texts, "model": model, "provider": provider},
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("retry-after", delay))
                    logger.warning("Embedding 429, backing off %.1fs (attempt %d/6)", retry_after, attempt + 1)
                    await asyncio.sleep(max(retry_after, delay))
                    delay = min(delay * 2, 60)
                    continue
                resp.raise_for_status()
                return resp.json()["embeddings"]
            except Exception as exc:
                last_error = exc
                logger.warning("Embedding attempt %d/6 failed: %s", attempt + 1, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
    raise RuntimeError(f"embedding request failed after 6 retries: {last_error}")
