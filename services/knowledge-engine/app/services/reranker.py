"""Cross-encoder reranking and post-retrieval enhancement.

Uses LLM as a cross-encoder to score (query, chunk) relevance, replacing
simple threshold-based filtering with more accurate semantic matching.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_RERANK_MODEL = "gemini-3.1-flash-lite-preview"

_RERANK_PROMPT = """\
你是一个相关性评分专家。请对以下每个文档片段与用户问题的相关性进行评分。

评分标准（0-10）：
- 10: 直接且完整地回答了问题
- 7-9: 高度相关，包含关键信息
- 4-6: 部分相关，可作为参考
- 1-3: 勉强相关
- 0: 完全不相关

用户问题：{query}

文档片段：
{chunks}

请严格按 JSON 格式返回：{{"scores": [score1, score2, ...]}}
只输出 JSON，不要其他内容。"""


async def cross_encoder_rerank(
    query: str,
    chunks: list[dict],
    top_n: int | None = None,
) -> list[dict]:
    """Use LLM as cross-encoder to rerank chunks by relevance."""
    if not settings.rag_cross_encoder_rerank or not chunks:
        return chunks

    top_n = top_n or settings.rag_rerank_top_n
    batch_size = 20

    scored: list[tuple[dict, float]] = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        scores = await _score_batch(query, batch)
        for chunk, score in zip(batch, scores):
            scored.append((chunk, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    result = []
    for chunk, score in scored[:top_n]:
        c = dict(chunk)
        c["rerank_score"] = score
        c["score"] = round(score / 10.0, 4)
        result.append(c)

    logger.info(
        "Cross-encoder reranked %d → %d chunks, top score=%.1f",
        len(chunks), len(result), scored[0][1] if scored else 0,
    )
    return result


async def _score_batch(query: str, chunks: list[dict]) -> list[float]:
    """Score a batch of chunks against the query using LLM."""
    chunk_texts = "\n\n".join(
        f"[片段{i+1}] {c['content'][:800]}" for i, c in enumerate(chunks)
    )
    prompt = _RERANK_PROMPT.format(query=query, chunks=chunk_texts)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.ai_provider_hub_url}/api/v1/ai/chat",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 800,
                    "model": _RERANK_MODEL,
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("content", "")

        cleaned = raw.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start != -1 and end > start:
            parsed = json.loads(cleaned[start:end])
            scores = parsed.get("scores", [])
            if len(scores) >= len(chunks):
                return [float(s) for s in scores[: len(chunks)]]

    except Exception:
        logger.debug("Cross-encoder scoring failed, falling back to original scores", exc_info=True)

    return [c.get("score", 0) * 10 for c in chunks]
