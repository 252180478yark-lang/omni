"""CRAG — Corrective Retrieval Augmented Generation.

After initial retrieval + reranking, evaluates whether the retrieved context
is sufficient to answer the query. If not, triggers a refined retrieval
or falls back to direct LLM generation with a warning.

Three verdicts:
  - CORRECT: context is sufficient → proceed normally
  - AMBIGUOUS: some relevant info but gaps → augment with broader search
  - INCORRECT: context is off-topic → warn user, try broader search
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_JUDGE_MODEL = "gemini-3.1-flash-lite-preview"

_JUDGE_PROMPT = """\
你是一个检索质量评估专家。请判断以下检索结果是否能充分回答用户的问题。

用户问题：{query}

检索到的内容摘要：
{context_summary}

请返回一个评估结果（严格 JSON 格式）：
{{
  "verdict": "CORRECT" | "AMBIGUOUS" | "INCORRECT",
  "confidence": 0.0-1.0,
  "reason": "一句话说明判断理由",
  "suggested_keywords": ["如果需要补充检索，建议搜索的关键词"]
}}"""


class CRAGResult:
    __slots__ = ("verdict", "confidence", "reason", "suggested_keywords")

    def __init__(
        self,
        verdict: str = "CORRECT",
        confidence: float = 1.0,
        reason: str = "",
        suggested_keywords: list[str] | None = None,
    ):
        self.verdict = verdict
        self.confidence = confidence
        self.reason = reason
        self.suggested_keywords = suggested_keywords or []


async def evaluate_retrieval(
    query: str,
    chunks: list[dict],
) -> CRAGResult:
    """Judge whether retrieved chunks adequately answer the query."""
    if not settings.rag_crag_enabled or not chunks:
        return CRAGResult()

    context_summary = "\n".join(
        f"- {c['content'][:300]}" for c in chunks[:5]
    )

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{settings.ai_provider_hub_url}/api/v1/ai/chat",
                json={
                    "messages": [{
                        "role": "user",
                        "content": _JUDGE_PROMPT.format(
                            query=query, context_summary=context_summary,
                        ),
                    }],
                    "temperature": 0.1,
                    "max_tokens": 500,
                    "model": _JUDGE_MODEL,
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("content", "")

        cleaned = raw.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start != -1 and end > start:
            parsed = json.loads(cleaned[start:end])
            result = CRAGResult(
                verdict=parsed.get("verdict", "CORRECT"),
                confidence=float(parsed.get("confidence", 1.0)),
                reason=parsed.get("reason", ""),
                suggested_keywords=parsed.get("suggested_keywords", []),
            )
            logger.info(
                "CRAG verdict=%s confidence=%.2f reason=%s",
                result.verdict, result.confidence, result.reason[:80],
            )
            return result

    except Exception:
        logger.debug("CRAG evaluation failed, assuming CORRECT", exc_info=True)

    return CRAGResult()
