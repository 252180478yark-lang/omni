"""RAG pipeline built on LangGraph StateGraph.

Graph: parse_query → retrieve → rerank → assemble_context → generate → route_output

For streaming, the graph runs up to assemble_context, then the LLM is streamed
token-by-token outside the graph to support SSE.

Intent routing: browse-type queries skip vector search and return structured
KB overview directly; generate-type queries go through the full RAG pipeline.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import TypedDict

import httpx
from langgraph.graph import END, StateGraph

from app.config import settings
from app.services.embedding_client import embed_texts
from app.services.hybrid_search import hybrid_search
from app.services.intent_router import classify_intent
from app.services.ingestion import browse_kb
from app.services.session_store import append_turn, get_history

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """你是 Omni-Vibe OS 的智能助手。基于以下参考资料回答用户问题。
如果参考资料不足以回答，请明确说明，并尽你所知给出建议。

---参考资料---
{context}

请基于参考资料给出准确、有条理的回答，并在适当位置标注引用来源编号 [1] [2] 等。"""


# ═══ State ═══

class RAGState(TypedDict, total=False):
    # Input
    query: str
    kb_id: str
    top_k: int
    model: str | None
    provider: str | None
    embedding_model: str | None
    embedding_provider: str | None
    session_id: str | None
    # Pipeline
    intent: str
    query_embedding: list[float]
    retrieved_chunks: list[dict]
    reranked_chunks: list[dict]
    context: str
    system_prompt: str
    chat_history: list[dict]
    # Output
    answer: str
    sources: list[dict]


# ═══ Nodes ═══

async def parse_query(state: RAGState) -> dict:
    """Classify intent and embed the user query (skip embedding for browse)."""
    intent = classify_intent(state["query"])
    if intent == "browse":
        return {"intent": intent, "query_embedding": []}

    emb_model = state.get("embedding_model") or settings.embedding_model
    emb_provider = state.get("embedding_provider") or settings.embedding_provider
    vecs = await embed_texts([state["query"]], model=emb_model, provider=emb_provider)
    return {"intent": intent, "query_embedding": vecs[0]}


async def retrieve(state: RAGState) -> dict:
    """Hybrid search (vector + fulltext + RRF fusion). Skip for browse intent."""
    if state.get("intent") == "browse":
        return {"retrieved_chunks": []}

    top_k = state.get("top_k") or settings.rag_top_k
    chunks = await hybrid_search(
        state["kb_id"], state["query"], state["query_embedding"], top_k=top_k * 3,
    )
    return {"retrieved_chunks": chunks}


async def rerank(state: RAGState) -> dict:
    """Score-based reranking: filter by threshold, deduplicate, cap to top_k."""
    if state.get("intent") == "browse":
        return {"reranked_chunks": []}

    top_k = state.get("top_k") or settings.rag_top_k
    threshold = settings.rag_score_threshold
    chunks = state.get("retrieved_chunks", [])

    above = [c for c in chunks if c.get("score", 0) >= threshold]
    result = above if above else chunks

    seen_content: set[str] = set()
    deduped: list[dict] = []
    for c in result:
        fingerprint = c["content"][:200]
        if fingerprint not in seen_content:
            seen_content.add(fingerprint)
            deduped.append(c)

    return {"reranked_chunks": deduped[:top_k]}


async def assemble_context(state: RAGState) -> dict:
    """Build the reference context string for the LLM prompt."""
    chunks = state.get("reranked_chunks", [])
    context = _build_context(chunks)
    system_prompt = RAG_SYSTEM_PROMPT.format(context=context)
    return {"context": context, "system_prompt": system_prompt}


async def generate(state: RAGState) -> dict:
    """Call LLM via ai-provider-hub to produce the answer."""
    chunks = state.get("reranked_chunks", [])
    if not chunks:
        return {
            "answer": "抱歉，在知识库中没有找到与您问题相关的内容。请尝试换一种问法，或检查知识库中是否已导入相关文档。",
            "sources": [],
        }

    answer = await _call_llm(
        state["query"], state["system_prompt"],
        model=state.get("model"), provider=state.get("provider"),
        history=state.get("chat_history", []),
    )
    sources = _build_sources(chunks)
    return {"answer": answer, "sources": sources}


async def route_output(state: RAGState) -> dict:
    """Terminal node — pass through (extensible for multi-modal routing)."""
    return {}


# ═══ Graph Construction ═══

def _build_rag_graph() -> StateGraph:
    graph = StateGraph(RAGState)
    graph.add_node("parse_query", parse_query)
    graph.add_node("retrieve", retrieve)
    graph.add_node("rerank", rerank)
    graph.add_node("assemble_context", assemble_context)
    graph.add_node("generate", generate)
    graph.add_node("route_output", route_output)

    graph.set_entry_point("parse_query")
    graph.add_edge("parse_query", "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "assemble_context")
    graph.add_edge("assemble_context", "generate")
    graph.add_edge("generate", "route_output")
    graph.add_edge("route_output", END)
    return graph


_rag_app = _build_rag_graph().compile()


# ═══ Browse Handler ═══

def _format_browse_response(overview: dict) -> str:
    """Format a browse_kb result into a human-readable Markdown answer."""
    kb = overview.get("kb") or {}
    docs = overview.get("documents", [])
    stats = overview.get("stats", {})

    lines: list[str] = []
    kb_name = kb.get("name", "当前知识库")
    lines.append(f"## 📚 {kb_name} 概览\n")

    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 文档数 | **{stats.get('document_count', 0)}** |")
    lines.append(f"| 文本块 (Chunks) | **{stats.get('chunk_count', 0)}** |")
    lines.append(f"| 向量模型 | {stats.get('embedding_provider', '')}/{stats.get('embedding_model', '')} |")
    lines.append(f"| 向量维度 | {stats.get('dimension', 0)} |")
    lines.append("")

    if docs:
        lines.append(f"### 文档列表 ({len(docs)} 个)\n")
        for i, doc in enumerate(docs, 1):
            title = doc.get("title", "未命名")
            chunks = doc.get("chunk_count", 0)
            src = doc.get("source_type", "")
            created = doc.get("created_at", "")[:10]
            lines.append(f"**{i}. {title}**")
            lines.append(f"   - Chunks: {chunks} · 来源: {src or '手动'} · 入库: {created}")
            preview = doc.get("preview", "")
            if preview:
                short = preview.replace("\n", " ")[:150]
                lines.append(f"   - 内容预览: {short}...")
            lines.append("")
    else:
        lines.append("该知识库暂无文档。\n")

    return "\n".join(lines)


def _build_browse_sources(docs: list[dict]) -> list[dict]:
    """Build source references for browse results."""
    return [
        {
            "index": i + 1,
            "chunk_id": doc["id"],
            "content": doc.get("preview", "")[:200],
            "title": doc.get("title"),
            "source_url": None,
            "score": 1.0,
        }
        for i, doc in enumerate(docs[:10])
    ]


# ═══ Public API ═══

async def rag_query(
    kb_id: str,
    query: str,
    top_k: int | None = None,
    model: str | None = None,
    provider: str | None = None,
    embedding_model: str | None = None,
    embedding_provider: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Full RAG pipeline via LangGraph (non-streaming)."""
    intent = classify_intent(query)
    history = await get_history(session_id) if session_id else []
    if session_id:
        await append_turn(session_id, "user", query)

    if intent == "browse":
        overview = await browse_kb(kb_id)
        answer = _format_browse_response(overview)
        sources = _build_browse_sources(overview.get("documents", []))
        if session_id:
            await append_turn(session_id, "assistant", answer)
        return {"answer": answer, "sources": sources, "model": "", "intent": "browse"}

    state: RAGState = {
        "query": query,
        "kb_id": kb_id,
        "top_k": top_k or settings.rag_top_k,
        "model": model,
        "provider": provider,
        "embedding_model": embedding_model,
        "embedding_provider": embedding_provider,
        "session_id": session_id,
        "chat_history": history,
    }
    result = await _rag_app.ainvoke(state)
    answer = result.get("answer", "")

    if session_id:
        await append_turn(session_id, "assistant", answer)

    return {
        "answer": answer,
        "sources": result.get("sources", []),
        "model": model or "",
        "intent": "generate",
    }


async def rag_stream(
    kb_id: str,
    query: str,
    top_k: int | None = None,
    model: str | None = None,
    provider: str | None = None,
    embedding_model: str | None = None,
    embedding_provider: str | None = None,
    session_id: str | None = None,
) -> AsyncIterator[dict]:
    """Streaming RAG: runs retrieval graph, then streams LLM token-by-token."""
    intent = classify_intent(query)
    logger.info("Query intent: %s — %s", intent, query[:60])

    if session_id:
        await append_turn(session_id, "user", query)

    # ── Browse path: instant DB lookup, no vector search / LLM ──
    if intent == "browse":
        overview = await browse_kb(kb_id)
        answer = _format_browse_response(overview)
        sources = _build_browse_sources(overview.get("documents", []))
        yield {"type": "text", "content": answer}
        yield {"type": "done", "sources": sources}
        if session_id:
            await append_turn(session_id, "assistant", answer)
        return

    # ── Generate path: full RAG pipeline ──
    history = await get_history(session_id) if session_id else []

    state: RAGState = {
        "query": query,
        "kb_id": kb_id,
        "top_k": top_k or settings.rag_top_k,
        "model": model,
        "provider": provider,
        "embedding_model": embedding_model,
        "embedding_provider": embedding_provider,
        "session_id": session_id,
        "chat_history": history,
    }

    s: dict = dict(state)
    s.update(await parse_query(s))
    s.update(await retrieve(s))
    s.update(await rerank(s))
    s.update(await assemble_context(s))

    chunks = s.get("reranked_chunks", [])
    if not chunks:
        no_result = "抱歉，在知识库中没有找到与您问题相关的内容。"
        yield {"type": "text", "content": no_result}
        yield {"type": "done", "sources": []}
        if session_id:
            await append_turn(session_id, "assistant", no_result)
        return

    collected_answer: list[str] = []
    async for token in _stream_llm(
        query, s["system_prompt"], model=model, provider=provider, history=history,
    ):
        collected_answer.append(token)
        yield {"type": "text", "content": token}

    if session_id:
        await append_turn(session_id, "assistant", "".join(collected_answer))

    yield {"type": "done", "sources": _build_sources(chunks)}


# ═══ Helpers ═══

def _build_context(chunks: list[dict]) -> str:
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        source = chunk.get("title") or chunk.get("source_url") or "unknown"
        parts.append(f"[{i}] {chunk['content']}\n    (来源: {source})")
    return "\n\n".join(parts)


def _build_sources(chunks: list[dict]) -> list[dict]:
    return [
        {
            "index": i + 1,
            "chunk_id": c["id"],
            "content": c["content"][:200],
            "title": c.get("title"),
            "source_url": c.get("source_url"),
            "score": c.get("score", 0),
        }
        for i, c in enumerate(chunks)
    ]


async def _call_llm(
    user_query: str,
    system_prompt: str,
    model: str | None = None,
    provider: str | None = None,
    history: list[dict] | None = None,
) -> str:
    url = f"{settings.ai_provider_hub_url}/api/v1/ai/chat"
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for turn in (history or []):
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_query})

    payload: dict = {
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 8000,
    }
    if model:
        payload["model"] = model
    if provider:
        payload["provider"] = provider

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("content", "")


async def _stream_llm(
    user_query: str,
    system_prompt: str,
    model: str | None = None,
    provider: str | None = None,
    history: list[dict] | None = None,
) -> AsyncIterator[str]:
    url = f"{settings.ai_provider_hub_url}/api/v1/ai/chat/stream"
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for turn in (history or []):
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_query})

    payload: dict = {
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 8000,
    }
    if model:
        payload["model"] = model
    if provider:
        payload["provider"] = provider

    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                    content = chunk.get("content", "")
                    if content and not chunk.get("done"):
                        yield content
                except json.JSONDecodeError:
                    continue
