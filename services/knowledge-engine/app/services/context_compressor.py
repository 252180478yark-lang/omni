"""Contextual compression — extract only query-relevant portions from chunks.

Reduces noise in the LLM context window by asking a fast model to extract
the sentences most relevant to the user's question.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_COMPRESS_MODEL = "gemini-3.1-flash-lite-preview"

_COMPRESS_PROMPT = """\
请从以下文本中提取与用户问题直接相关的内容。
只保留能帮助回答问题的关键句子和信息，删除不相关的内容。
保持原文措辞，不要改写。如果整段都相关，原样返回。
如果完全不相关，返回空字符串。

用户问题：{query}

文本：
{text}"""


async def compress_chunks(
    query: str,
    chunks: list[dict],
) -> list[dict]:
    """Compress each chunk to only include query-relevant content."""
    if not settings.rag_contextual_compression or not chunks:
        return chunks

    compressed: list[dict] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for chunk in chunks:
            original_content = chunk["content"]
            if len(original_content) < 200:
                compressed.append(chunk)
                continue

            try:
                resp = await client.post(
                    f"{settings.ai_provider_hub_url}/api/v1/ai/chat",
                    json={
                        "messages": [{
                            "role": "user",
                            "content": _COMPRESS_PROMPT.format(
                                query=query, text=original_content[:3000],
                            ),
                        }],
                        "temperature": 0.1,
                        "max_tokens": 1500,
                        "model": _COMPRESS_MODEL,
                    },
                )
                resp.raise_for_status()
                result = resp.json().get("content", "").strip()

                if result and len(result) > 20:
                    c = dict(chunk)
                    c["content"] = result
                    c["metadata"] = {
                        **chunk.get("metadata", {}),
                        "compressed": True,
                        "original_length": len(original_content),
                    }
                    compressed.append(c)
                    continue
            except Exception:
                logger.debug("Chunk compression failed, using original", exc_info=True)

            compressed.append(chunk)

    logger.info(
        "Compressed %d chunks, avg reduction %.0f%%",
        len(compressed),
        _avg_reduction(chunks, compressed),
    )
    return compressed


def _avg_reduction(original: list[dict], compressed: list[dict]) -> float:
    if not original:
        return 0
    orig_len = sum(len(c["content"]) for c in original)
    comp_len = sum(len(c["content"]) for c in compressed)
    if orig_len == 0:
        return 0
    return (1 - comp_len / orig_len) * 100
