"""Query enhancement strategies for RAG retrieval.

Three strategies that can be combined:
  1. Query Rewriting — rephrase user query into a better search query
  2. HyDE — generate a hypothetical answer, embed that instead of the query
  3. Sub-query Decomposition — break complex questions into simpler sub-queries
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_FAST_MODEL = "gemini-3.1-flash-lite-preview"


async def _llm_call(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    url = f"{settings.ai_provider_hub_url}/api/v1/ai/chat"
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json={
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 1500,
            "model": _FAST_MODEL,
        })
        resp.raise_for_status()
        return resp.json().get("content", "")


# ═══ Query Rewriting ═══

_REWRITE_PROMPT = """\
你是搜索查询优化专家。请将用户的原始问题改写为更适合知识库搜索的查询。
要求：
- 补充隐含的关键词和同义词/近义词
- 移除口语化表达
- 保持原始意图
- 如有专业术语，同时补充其常见别名
- 只输出改写后的查询，不要解释

原始问题：{query}"""


async def rewrite_query(query: str) -> str:
    """Rewrite user query for better retrieval."""
    if not settings.rag_query_rewrite:
        return query
    try:
        result = await _llm_call(_REWRITE_PROMPT.format(query=query))
        rewritten = result.strip().strip('"\'')
        if rewritten and len(rewritten) > 3:
            logger.info("Query rewrite: '%s' → '%s'", query[:50], rewritten[:50])
            return rewritten
    except Exception:
        logger.debug("Query rewrite failed, using original", exc_info=True)
    return query


# ═══ HyDE — Hypothetical Document Embedding ═══

_HYDE_PROMPT = """\
请针对以下问题，写一段可能出现在文档中的回答内容（200-400字）。
不需要真实准确，但要尽量覆盖相关的关键词、专业术语和多种表述方式。
包含该领域常见的概念和关联信息。
只输出这段假设性内容，不要加前缀说明。

问题：{query}"""


async def generate_hypothetical_answer(query: str) -> str:
    """Generate a hypothetical answer for HyDE embedding."""
    if not settings.rag_hyde:
        return ""
    try:
        result = await _llm_call(_HYDE_PROMPT.format(query=query), temperature=0.7)
        hypo = result.strip()
        if hypo and len(hypo) > 20:
            logger.info("HyDE generated %d chars for query: %s", len(hypo), query[:40])
            return hypo
    except Exception:
        logger.debug("HyDE generation failed", exc_info=True)
    return ""


# ═══ Sub-query Decomposition ═══

_SUBQUERY_PROMPT = """\
判断以下问题是否是一个复合问题（包含多个不同的子问题或多个并列的查询意图）。
如果是复合问题，请将其分解为 {max_n} 个以内的独立子问题。
如果是简单问题，只输出原问题。

请严格按 JSON 格式返回：{{"queries": ["问题1", "问题2"]}}

用户问题：{query}"""


async def decompose_query(query: str) -> list[str]:
    """Decompose complex queries into simpler sub-queries."""
    if not settings.rag_subquery:
        return [query]
    try:
        result = await _llm_call(
            _SUBQUERY_PROMPT.format(query=query, max_n=settings.rag_subquery_max),
        )
        cleaned = result.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start != -1 and end > start:
            parsed = json.loads(cleaned[start:end])
            queries = parsed.get("queries", [query])
            if queries and all(isinstance(q, str) and len(q) > 3 for q in queries):
                logger.info("Sub-query decomposition: %d queries from '%s'", len(queries), query[:40])
                return queries[:settings.rag_subquery_max]
    except Exception:
        logger.debug("Sub-query decomposition failed", exc_info=True)
    return [query]


async def enhance_query(query: str) -> dict:
    """Run all query enhancement strategies and return enhanced query data.

    Returns:
        {
            "original": str,
            "rewritten": str,
            "hypothetical_answer": str,
            "sub_queries": [str, ...],
        }
    """
    import asyncio

    rewrite_task = rewrite_query(query)
    hyde_task = generate_hypothetical_answer(query)
    subquery_task = decompose_query(query)

    rewritten, hypo_answer, sub_queries = await asyncio.gather(
        rewrite_task, hyde_task, subquery_task,
    )

    return {
        "original": query,
        "rewritten": rewritten,
        "hypothetical_answer": hypo_answer,
        "sub_queries": sub_queries,
    }
