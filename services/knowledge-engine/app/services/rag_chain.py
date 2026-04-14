"""RAG + GraphRAG fused pipeline built on LangGraph StateGraph.

Graph: parse_query → retrieve → rerank → assemble_context → generate → route_output

Advanced optimizations integrated:
  - Query Enhancement: rewriting, HyDE, sub-query decomposition
  - Hybrid Retrieval: vector + fulltext + HyPE, fused with RRF
  - Graph Search: entity matching + relation traversal (GraphRAG)
  - Cross-Encoder Reranking: LLM-based relevance scoring
  - Context Window Enrichment: neighboring chunk expansion
  - Contextual Compression: extract only relevant portions
  - CRAG: corrective retrieval with quality self-check
  - Continuation Intent: detects "继续"/"continue" and resumes from session history
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import TypedDict

import httpx
from langgraph.graph import END, StateGraph

import re

from app.config import settings
from app.services.context_compressor import compress_chunks
from app.services.crag import CRAGResult, evaluate_retrieval
from app.services.embedding_client import embed_texts
from app.services.graph_search import graph_search
from app.services.hybrid_search import enrich_with_context_window, hybrid_search
from app.services.intent_router import classify_intent
from app.services.ingestion import browse_kb
from app.services.query_enhancer import enhance_query
from app.services.reranker import cross_encoder_rerank
from app.services.session_store import append_turn, get_history

# Patterns indicating the user wants to continue a previous response
_CONTINUE_RE = re.compile(
    r"^(继续|continue|接着说|接上文|接着写|继续写|继续输出|继续生成|接着|往下|下一段|go\s*on|keep\s*going)[\s\.。！!]*$",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """你是 Omni-Vibe OS 的智能助手。基于以下参考资料和知识图谱关系回答用户问题。
如果参考资料不足以回答，请明确说明，并尽你所知给出建议。

---参考资料---
{context}

---知识图谱关系---
{graph_context}

请综合参考资料和知识图谱关系给出准确、有条理、详尽的回答。
- 当实体关系有助于解释跨文档联系或全局脉络时，请优先利用图谱关系进行推理。
- 在适当位置标注引用来源编号 [1] [2] 等。
- 如果知识图谱关系为空，仅基于参考资料回答即可。
- 如果多条参考资料包含互补信息，请综合整理后给出完整回答，不要遗漏要点。
- 对于复杂问题，请使用清晰的结构（如标题、列表、分段）组织回答。

准确性与知识库结合（重要）：
- 产品功能名、操作路径、指标口径、政策规则等可核对信息，须优先严格依据「参考资料」表述；引用对应编号。勿编造参考资料中未出现的具体参数、链接或官方表述。
- 若某一部分在参考资料中无直接依据，须明确标注为「知识库未直接覆盖，以下为通用经验/推断」，并与有据内容分开写。

输出长度（重要）：
- 不要以「单次回答字数上限」「物理限制」「无法生成一万五千字」等理由拒绝用户的合理长文需求；在模型与接口允许的最大输出范围内，尽量完整、分章节撰写。
- 若用户需求远超单次可生成规模，先输出大纲与第一部分正文，并明确提示用户可再发「继续」以承接下一部分，且后续内容仍须与参考资料一致并继续标注引用。"""

_CRAG_AUGMENT_PROMPT = """（注意：检索系统认为以上参考资料可能不完全覆盖问题，请结合你的知识谨慎补充。
检索系统备注：{reason}）
"""

# ═══ Persona Sandwich Helper ═══

_RAG_INSERT_MARKER = "<!-- RAG_INSERT -->"


def _split_persona_prompt(persona_prompt: str) -> tuple[str, str]:
    """Split persona prompt at the RAG_INSERT marker.

    Returns (identity_part, framework_part).
    - identity_part: role declaration & core principles — placed BEFORE RAG context
    - framework_part: detailed methodology & constraints — placed AFTER RAG context
    If no marker is found, returns (full_prompt, "") for backward compatibility.
    """
    if _RAG_INSERT_MARKER in persona_prompt:
        parts = persona_prompt.split(_RAG_INSERT_MARKER, 1)
        return parts[0].strip(), parts[1].strip()
    return persona_prompt.strip(), ""


_NO_RESULT_NOTE = (
    "知识库检索未找到与您问题直接相关的文档。"
    "请明确说明知识库中未找到直接依据，并基于你的角色专业视角给出分析与建议。"
)


def _build_persona_system_prompt(
    persona_prompt: str,
    rag_prompt: str,
) -> str:
    """Build system prompt with sandwich structure: Identity → RAG → Framework.

    When persona contains the RAG_INSERT marker the prompt is structured as:
        [Identity & Core Principles]
        ---
        [RAG reference material]
        ---
        [Detailed methodology & role-specific instructions]

    This exploits the primacy effect (identity anchored first) and recency
    effect (detailed instructions closest to generation) while keeping factual
    RAG content in the high-attention middle zone.
    """
    identity, framework = _split_persona_prompt(persona_prompt)
    if framework:
        return (
            f"{identity}\n\n"
            f"---\n\n"
            f"以下是你在回答时需要参考的资料和规则：\n\n"
            f"{rag_prompt}\n\n"
            f"---\n\n"
            f"{framework}"
        )
    # Legacy / custom personas without marker: identity first, then RAG
    return (
        f"{identity}\n\n"
        f"---\n\n"
        f"以下是你在回答时需要参考的资料和规则：\n\n"
        f"{rag_prompt}"
    )


def _build_persona_no_result_prompt(persona_prompt: str) -> str:
    """Build system prompt for the no-retrieval-result case (sandwich-aware)."""
    identity, framework = _split_persona_prompt(persona_prompt)
    if framework:
        return (
            f"{identity}\n\n"
            f"---\n\n"
            f"{_NO_RESULT_NOTE}\n\n"
            f"---\n\n"
            f"{framework}"
        )
    return f"{identity}\n\n---\n\n{_NO_RESULT_NOTE}"


# ═══ State ═══

class RAGState(TypedDict, total=False):
    # Input
    query: str
    kb_id: str
    kb_ids: list[str]
    kb_embedding_map: dict[str, dict]
    top_k: int
    model: str | None
    provider: str | None
    embedding_model: str | None
    embedding_provider: str | None
    session_id: str | None
    target_chars_continue: int
    # Pipeline
    intent: str
    query_enhanced: dict
    query_embedding: list[float]
    query_embeddings: dict[str, list[float]]
    hyde_embedding: list[float] | None
    retrieved_chunks: list[dict]
    reranked_chunks: list[dict]
    graph_context: str
    crag_result: dict
    context: str
    system_prompt: str
    chat_history: list[dict]
    persona_prompt: str | None
    # Output
    answer: str
    sources: list[dict]


# ═══ Nodes ═══

async def parse_query(state: RAGState) -> dict:
    """Classify intent, enhance query, and embed once per unique embedding model."""
    intent = classify_intent(state["query"])
    if intent == "browse":
        return {"intent": intent, "query_embedding": [], "query_embeddings": {}, "query_enhanced": {}}

    enhanced = await enhance_query(state["query"])
    search_query = enhanced.get("rewritten", state["query"])

    kb_emb_map: dict[str, dict] = state.get("kb_embedding_map") or {}
    unique_models: dict[str, tuple[str, str]] = {}
    for _kb_id, info in kb_emb_map.items():
        m = info.get("embedding_model") or settings.embedding_model
        p = info.get("embedding_provider") or settings.embedding_provider
        key = f"{p}/{m}"
        if key not in unique_models:
            unique_models[key] = (m, p)

    if not unique_models:
        m = state.get("embedding_model") or settings.embedding_model
        p = state.get("embedding_provider") or settings.embedding_provider
        unique_models[f"{p}/{m}"] = (m, p)

    texts_to_embed: dict[str, list[str]] = {}
    for key, (model, prov) in unique_models.items():
        texts_to_embed[key] = [search_query]
        hypo = enhanced.get("hypothetical_answer", "")
        if hypo:
            texts_to_embed[key].append(hypo)

    embed_tasks = {
        key: embed_texts(texts, model=model, provider=prov)
        for key, (model, prov) in unique_models.items()
        for texts in [texts_to_embed[key]]
    }
    results = await asyncio.gather(*embed_tasks.values())

    query_embeddings: dict[str, list[float]] = {}
    hyde_embedding: list[float] | None = None
    for key, vecs in zip(embed_tasks.keys(), results):
        query_embeddings[key] = vecs[0]
        if len(vecs) > 1:
            hyde_embedding = vecs[1]

    first_embedding = next(iter(query_embeddings.values()))
    return {
        "intent": intent,
        "query_enhanced": enhanced,
        "query_embedding": first_embedding,
        "query_embeddings": query_embeddings,
        "hyde_embedding": hyde_embedding,
    }


def _resolve_kb_ids(state: RAGState) -> list[str]:
    kb_ids = state.get("kb_ids") or []
    if not kb_ids and state.get("kb_id"):
        kb_ids = [state["kb_id"]]
    return kb_ids


def _embedding_for_kb(state: RAGState, kb_id: str) -> list[float]:
    kb_emb_map: dict[str, dict] = state.get("kb_embedding_map") or {}
    info = kb_emb_map.get(kb_id, {})
    m = info.get("embedding_model") or settings.embedding_model
    p = info.get("embedding_provider") or settings.embedding_provider
    key = f"{p}/{m}"
    embeddings = state.get("query_embeddings") or {}
    return embeddings.get(key, state.get("query_embedding", []))


async def retrieve(state: RAGState) -> dict:
    """Run hybrid search (vector+fulltext+HyPE) and graph search, with sub-query support."""
    if state.get("intent") == "browse":
        return {"retrieved_chunks": [], "graph_context": ""}

    top_k = state.get("top_k") or settings.rag_top_k
    kb_ids = _resolve_kb_ids(state)
    enhanced = state.get("query_enhanced") or {}
    sub_queries = enhanced.get("sub_queries", [state["query"]])

    tasks: list = []
    task_labels: list[str] = []

    for kid in kb_ids:
        emb = _embedding_for_kb(state, kid)
        hyde_emb = state.get("hyde_embedding")

        for sq in sub_queries:
            search_emb = hyde_emb if hyde_emb else emb
            tasks.append(hybrid_search(kid, sq, search_emb, top_k=top_k * 3))
            task_labels.append(f"hybrid:{kid[:8]}")

        if hyde_emb and hyde_emb != emb:
            tasks.append(hybrid_search(kid, state["query"], emb, top_k=top_k * 2))
            task_labels.append(f"hybrid-orig:{kid[:8]}")

        tasks.append(graph_search(kid, state["query"]))
        task_labels.append(f"graph:{kid[:8]}")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_chunks: list[dict] = []
    graph_entities_total = 0
    graph_relations_total = 0
    graph_chunks_total: list[dict] = []
    all_graph_contexts: list[str] = []

    for i, res in enumerate(results):
        label = task_labels[i]
        if isinstance(res, BaseException):
            logger.error("%s failed: %s", label, res)
            continue
        if label.startswith("hybrid"):
            all_chunks.extend(res)
        else:
            graph_entities_total += len(res.get("entities", []))
            graph_relations_total += len(res.get("relations", []))
            graph_chunks_total.extend(res.get("graph_chunks", []))
            ctx = res.get("graph_context", "")
            if ctx:
                all_graph_contexts.append(ctx)

    logger.info(
        "Retrieve (%d KBs, %d sub-queries): hybrid=%d chunks, graph=%d entities / %d relations / %d chunks",
        len(kb_ids), len(sub_queries), len(all_chunks),
        graph_entities_total, graph_relations_total, len(graph_chunks_total),
    )

    seen_ids = {c["id"] for c in all_chunks}
    for gc in graph_chunks_total:
        if gc["id"] not in seen_ids:
            seen_ids.add(gc["id"])
            all_chunks.append(gc)

    # Deduplicate by content fingerprint
    deduped: list[dict] = []
    seen_fp: set[str] = set()
    for c in all_chunks:
        fp = c["content"][:200]
        if fp not in seen_fp:
            seen_fp.add(fp)
            deduped.append(c)

    merged_graph_context = "\n\n".join(all_graph_contexts) if all_graph_contexts else ""

    return {
        "retrieved_chunks": deduped,
        "graph_context": merged_graph_context,
    }


async def rerank(state: RAGState) -> dict:
    """Cross-encoder reranking with context window enrichment."""
    if state.get("intent") == "browse":
        return {"reranked_chunks": [], "crag_result": {}}

    top_k = state.get("top_k") or settings.rag_top_k
    chunks = state.get("retrieved_chunks", [])
    query = state.get("query_enhanced", {}).get("rewritten", state["query"])

    reranked = await cross_encoder_rerank(query, chunks, top_n=top_k)

    enriched = await enrich_with_context_window(reranked)

    if settings.rag_crag_enabled:
        crag_result_obj = await evaluate_retrieval(state["query"], enriched)
    else:
        crag_result_obj = CRAGResult(verdict="CORRECT", confidence=1.0, reason="", suggested_keywords=[])
    crag_dict = {
        "verdict": crag_result_obj.verdict,
        "confidence": crag_result_obj.confidence,
        "reason": crag_result_obj.reason,
        "suggested_keywords": crag_result_obj.suggested_keywords,
    }

    # Apply score threshold — filter out low-relevance chunks before context assembly
    threshold = settings.rag_score_threshold
    if threshold > 0 and enriched:
        filtered = [c for c in enriched if c.get("score", 0) >= threshold]
        # Keep at least 1 chunk even if all are below threshold
        enriched = filtered if filtered else enriched[:1]

    if crag_result_obj.verdict in ("INCORRECT", "AMBIGUOUS") and crag_result_obj.suggested_keywords:
        logger.info("CRAG: retrieval %s, attempting broader search with: %s", crag_result_obj.verdict, crag_result_obj.suggested_keywords)
        kb_ids = _resolve_kb_ids(state)
        for kid in kb_ids:
            for kw in crag_result_obj.suggested_keywords[:3]:
                emb = _embedding_for_kb(state, kid)
                try:
                    extra = await hybrid_search(kid, kw, emb, top_k=5)
                    enriched.extend(extra)
                except Exception:
                    pass
        seen: set[str] = set()
        unique: list[dict] = []
        for c in enriched:
            if c["id"] not in seen:
                seen.add(c["id"])
                unique.append(c)
        enriched = unique

    return {"reranked_chunks": enriched, "crag_result": crag_dict}


async def assemble_context(state: RAGState) -> dict:
    """Compress chunks and build the final prompt context."""
    chunks = state.get("reranked_chunks", [])
    query = state.get("query_enhanced", {}).get("rewritten", state["query"])

    compressed = await compress_chunks(query, chunks)

    context = _build_context(compressed)
    graph_ctx = state.get("graph_context", "")

    crag = state.get("crag_result", {})
    crag_note = ""
    if crag.get("verdict") in ("AMBIGUOUS", "INCORRECT"):
        crag_note = _CRAG_AUGMENT_PROMPT.format(reason=crag.get("reason", ""))

    rag_prompt = RAG_SYSTEM_PROMPT.format(
        context=context,
        graph_context=graph_ctx or "（无图谱数据）",
    ) + crag_note

    persona_prompt = (state.get("persona_prompt") or "").strip()
    if persona_prompt:
        system_prompt = _build_persona_system_prompt(persona_prompt, rag_prompt)
    else:
        system_prompt = rag_prompt

    return {"context": context, "system_prompt": system_prompt, "graph_context": graph_ctx}


async def generate(state: RAGState) -> dict:
    """Call LLM via ai-provider-hub to produce the answer."""
    chunks = state.get("reranked_chunks", [])
    if not chunks:
        persona_prompt = (state.get("persona_prompt") or "").strip()
        if persona_prompt:
            sys_p = _build_persona_no_result_prompt(persona_prompt)
            answer = await _call_llm(
                state["query"],
                sys_p,
                model=state.get("model"),
                provider=state.get("provider"),
                history=state.get("chat_history", []),
            )
            return {"answer": answer, "sources": []}
        return {
            "answer": "抱歉，在知识库中没有找到与您问题相关的内容。请尝试换一种问法，或检查知识库中是否已导入相关文档。",
            "sources": [],
        }

    sources = _build_sources(chunks)
    tc = int(state.get("target_chars_continue") or 0)
    if tc > 0:
        # 多轮续写在 rag_query / rag_stream 中完成，避免浪费一次完整生成
        return {"answer": "", "sources": sources}

    answer = await _call_llm(
        state["query"], state["system_prompt"],
        model=state.get("model"), provider=state.get("provider"),
        history=state.get("chat_history", []),
    )
    return {"answer": answer, "sources": sources}


async def route_output(state: RAGState) -> dict:
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
    kb = overview.get("kb") or {}
    docs = overview.get("documents", [])
    stats = overview.get("stats", {})

    lines: list[str] = []
    kb_name = kb.get("name", "当前知识库")
    lines.append(f"## 📚 {kb_name} 概览\n")

    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
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
    cap = settings.rag_source_snippet_max_chars
    return [
        {
            "index": i + 1,
            "chunk_id": doc["id"],
            "content": (doc.get("preview") or "")[:cap],
            "title": doc.get("title"),
            "source_url": None,
            "score": 1.0,
        }
        for i, doc in enumerate(docs[:10])
    ]


# ═══ Public API ═══

def _clamp_rag_target_chars(raw: int | None) -> int:
    if raw is None or raw <= 0:
        return 0
    return min(int(raw), settings.rag_continue_max_target_chars)


def _first_round_user_with_target(query: str, target: int) -> str:
    return (
        f"{query}\n\n"
        f"【系统指令】全文目标约 {target} 个字符；服务端将自动多轮续写直至接近此规模。"
        f"请务必开始撰写，勿以单次字数上限为由拒绝开篇；单轮未写完时可自然收笔，下一轮会自动接续。"
        f"仍须严格依据参考资料使用 [1][2] 等引用。"
    )


def _continue_round_user_message(target: int, written: int, round_one_based: int) -> str:
    return (
        f"请直接接续上文输出（第 {round_one_based} 段），不要重复已写段落。"
        f"仍须严格依据系统提示中的参考资料使用 [1][2] 等引用。"
        f"当前累计约 {written} 字符，目标全文约 {target} 字符；本段请尽量充实展开。"
    )


def _messages_from_thread(
    system_prompt: str,
    history: list[dict] | None,
    local_thread: list[dict[str, str]],
    user_content: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for turn in history or []:
        messages.append({"role": str(turn["role"]), "content": str(turn.get("content", ""))})
    for turn in local_thread:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_content})
    return messages


def _messages_single_turn(
    system_prompt: str,
    history: list[dict] | None,
    user_content: str,
) -> list[dict[str, str]]:
    return _messages_from_thread(system_prompt, history, [], user_content)


async def rag_query(
    kb_ids: list[str],
    query: str,
    top_k: int | None = None,
    model: str | None = None,
    provider: str | None = None,
    kb_embedding_map: dict[str, dict] | None = None,
    session_id: str | None = None,
    target_chars: int | None = None,
    continue_max_rounds: int | None = None,
    persona_prompt: str | None = None,
) -> dict:
    """Full RAG pipeline via LangGraph (non-streaming). Supports multi-KB."""
    # ── Continuation intent: skip retrieval, resume from session history ──
    if _CONTINUE_RE.match(query.strip()) and session_id:
        history = await get_history(session_id)
        if history:
            await append_turn(session_id, "user", query)
            continue_prompt = (
                "请直接接续上文输出，不要重复已写内容。"
                "继续依据系统提示中的参考资料使用 [1][2] 等引用。"
            )
            messages: list[dict[str, str]] = [{"role": "system", "content": continue_prompt}]
            for turn in history:
                messages.append({"role": str(turn["role"]), "content": str(turn.get("content", ""))})
            messages.append({"role": "user", "content": "继续"})
            answer = await _call_llm_messages(messages, model=model, provider=provider)
            await append_turn(session_id, "assistant", answer)
            return {
                "answer": answer,
                "sources": [],
                "model": model or "",
                "intent": "continue",
                "continue_rounds_used": 1,
                "target_chars": 0,
            }

    intent = classify_intent(query)
    history = await get_history(session_id) if session_id else []
    if session_id:
        await append_turn(session_id, "user", query)

    if intent == "browse":
        overview = await browse_kb(kb_ids[0])
        answer = _format_browse_response(overview)
        sources = _build_browse_sources(overview.get("documents", []))
        if session_id:
            await append_turn(session_id, "assistant", answer)
        return {
            "answer": answer,
            "sources": sources,
            "model": "",
            "intent": "browse",
            "continue_rounds_used": 1,
            "target_chars": 0,
        }

    tgt = _clamp_rag_target_chars(target_chars)
    state: RAGState = {
        "query": query,
        "kb_id": kb_ids[0],
        "kb_ids": kb_ids,
        "kb_embedding_map": kb_embedding_map or {},
        "top_k": top_k or settings.rag_top_k,
        "model": model,
        "provider": provider,
        "session_id": session_id,
        "chat_history": history,
        "target_chars_continue": tgt,
        "persona_prompt": persona_prompt,
    }
    result = await _rag_app.ainvoke(state)
    answer = result.get("answer", "")
    graph_ctx = result.get("graph_context", "")
    crag = result.get("crag_result", {})
    max_rounds = continue_max_rounds or settings.rag_continue_max_rounds
    ratio = settings.rag_continue_target_ratio
    rounds_used = 1

    if tgt > 0 and result.get("system_prompt") and result.get("sources"):
        system_prompt = str(result["system_prompt"])
        hist = list(history)
        local: list[dict[str, str]] = []
        written = 0
        answer = ""
        rounds_used = 0
        for r in range(max_rounds):
            rounds_used = r + 1
            u = _first_round_user_with_target(query, tgt) if r == 0 else _continue_round_user_message(tgt, written, r + 1)
            messages = _messages_from_thread(system_prompt, hist, local, u)
            piece = await _call_llm_messages(messages, model=model, provider=provider)
            local.append({"role": "user", "content": u})
            local.append({"role": "assistant", "content": piece})
            answer += piece
            written += len(piece)
            if written >= tgt * ratio:
                break
            if r > 0 and len(piece.strip()) < 40:
                break

    if session_id:
        await append_turn(session_id, "assistant", answer)

    return {
        "answer": answer,
        "sources": result.get("sources", []),
        "model": model or "",
        "intent": "generate",
        "graph_rag_used": bool(graph_ctx),
        "graph_context_preview": graph_ctx[:500] if graph_ctx else "",
        "kb_count": len(kb_ids),
        "crag_verdict": crag.get("verdict", ""),
        "continue_rounds_used": rounds_used,
        "target_chars": tgt,
    }


async def rag_stream(
    kb_ids: list[str],
    query: str,
    top_k: int | None = None,
    model: str | None = None,
    provider: str | None = None,
    kb_embedding_map: dict[str, dict] | None = None,
    session_id: str | None = None,
    target_chars: int | None = None,
    continue_max_rounds: int | None = None,
    persona_prompt: str | None = None,
) -> AsyncIterator[dict]:
    """Streaming RAG: runs full retrieval pipeline, then streams LLM."""
    # ── Continuation intent: skip retrieval, stream from session history ──
    if _CONTINUE_RE.match(query.strip()) and session_id:
        history = await get_history(session_id)
        if history:
            await append_turn(session_id, "user", query)
            continue_prompt = (
                "请直接接续上文输出，不要重复已写内容。"
                "继续依据系统提示中的参考资料使用 [1][2] 等引用。"
            )
            messages: list[dict[str, str]] = [{"role": "system", "content": continue_prompt}]
            for turn in history:
                messages.append({"role": str(turn["role"]), "content": str(turn.get("content", ""))})
            messages.append({"role": "user", "content": "继续"})
            collected: list[str] = []
            async for token in _stream_llm_messages(messages, model=model, provider=provider):
                collected.append(token)
                yield {"type": "text", "content": token}
            await append_turn(session_id, "assistant", "".join(collected))
            yield {"type": "done", "sources": [], "intent": "continue", "continue_rounds_used": 1, "target_chars": 0}
            return

    intent = classify_intent(query)
    logger.info("Query intent: %s — %s (KBs: %d)", intent, query[:60], len(kb_ids))

    history = await get_history(session_id) if session_id else []

    if session_id:
        await append_turn(session_id, "user", query)

    if intent == "browse":
        overview = await browse_kb(kb_ids[0])
        answer = _format_browse_response(overview)
        sources = _build_browse_sources(overview.get("documents", []))
        yield {"type": "text", "content": answer}
        yield {"type": "done", "sources": sources}
        if session_id:
            await append_turn(session_id, "assistant", answer)
        return

    state: RAGState = {
        "query": query,
        "kb_id": kb_ids[0],
        "kb_ids": kb_ids,
        "kb_embedding_map": kb_embedding_map or {},
        "top_k": top_k or settings.rag_top_k,
        "model": model,
        "provider": provider,
        "session_id": session_id,
        "chat_history": history,
        "persona_prompt": persona_prompt,
    }

    s: dict = dict(state)
    s.update(await parse_query(s))
    s.update(await retrieve(s))
    s.update(await rerank(s))
    s.update(await assemble_context(s))

    chunks = s.get("reranked_chunks", [])
    graph_ctx = s.get("graph_context", "")
    crag = s.get("crag_result", {})
    retrieval_meta = {
        "graph_rag_used": bool(graph_ctx),
        "graph_context_preview": graph_ctx[:300] if graph_ctx else "",
        "kb_count": len(kb_ids),
        "crag_verdict": crag.get("verdict", ""),
    }

    if not chunks:
        persona_p = (persona_prompt or "").strip()
        if persona_p:
            sys_p = _build_persona_no_result_prompt(persona_p)
            collected_nb: list[str] = []
            async for token in _stream_llm(
                query,
                sys_p,
                model=model,
                provider=provider,
                history=history,
            ):
                collected_nb.append(token)
                yield {"type": "text", "content": token}
            if session_id:
                await append_turn(session_id, "assistant", "".join(collected_nb))
            yield {
                "type": "done",
                "sources": [],
                **retrieval_meta,
                "continue_rounds_used": 1,
                "target_chars": 0,
            }
            return
        no_result = "抱歉，在知识库中没有找到与您问题相关的内容。"
        yield {"type": "text", "content": no_result}
        yield {"type": "done", "sources": [], **retrieval_meta}
        if session_id:
            await append_turn(session_id, "assistant", no_result)
        return

    tgt = _clamp_rag_target_chars(target_chars)
    max_rounds = continue_max_rounds or settings.rag_continue_max_rounds
    ratio = settings.rag_continue_target_ratio
    collected_answer: list[str] = []
    rounds_used = 1

    if tgt <= 0:
        async for token in _stream_llm(
            query, s["system_prompt"], model=model, provider=provider, history=history,
        ):
            collected_answer.append(token)
            yield {"type": "text", "content": token}
    else:
        system_prompt = s["system_prompt"]
        local: list[dict[str, str]] = []
        written = 0
        rounds_used = 0
        for r in range(max_rounds):
            rounds_used = r + 1
            u = _first_round_user_with_target(query, tgt) if r == 0 else _continue_round_user_message(tgt, written, r + 1)
            messages = _messages_from_thread(system_prompt, history, local, u)
            piece_parts: list[str] = []
            async for token in _stream_llm_messages(messages, model=model, provider=provider):
                piece_parts.append(token)
                collected_answer.append(token)
                yield {"type": "text", "content": token}
            piece = "".join(piece_parts)
            local.append({"role": "user", "content": u})
            local.append({"role": "assistant", "content": piece})
            written += len(piece)
            yield {"type": "continue_meta", "round": rounds_used, "chars_so_far": written, "target": tgt}
            if written >= tgt * ratio:
                break
            if r > 0 and len(piece.strip()) < 40:
                break

    if session_id:
        await append_turn(session_id, "assistant", "".join(collected_answer))

    done_payload = {
        "type": "done",
        "sources": _build_sources(chunks),
        **retrieval_meta,
        "continue_rounds_used": rounds_used,
        "target_chars": tgt,
    }
    yield done_payload


# ═══ Helpers ═══

def _build_context(chunks: list[dict]) -> str:
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        source = chunk.get("title") or chunk.get("source_url") or "unknown"
        parts.append(f"[{i}] {chunk['content']}\n    (来源: {source})")
    return "\n\n".join(parts)


def _build_sources(chunks: list[dict]) -> list[dict]:
    cap = settings.rag_source_snippet_max_chars
    return [
        {
            "index": i + 1,
            "chunk_id": c["id"],
            "content": (c.get("content") or "")[:cap],
            "title": c.get("title"),
            "source_url": c.get("source_url"),
            "score": c.get("score", 0),
        }
        for i, c in enumerate(chunks)
    ]


async def _call_llm_messages(
    messages: list[dict[str, str]],
    model: str | None = None,
    provider: str | None = None,
) -> str:
    url = f"{settings.ai_provider_hub_url}/api/v1/ai/chat"
    payload: dict = {
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": settings.rag_max_output_tokens,
    }
    if model:
        payload["model"] = model
    if provider:
        payload["provider"] = provider

    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("content", "")


async def _stream_llm_messages(
    messages: list[dict[str, str]],
    model: str | None = None,
    provider: str | None = None,
) -> AsyncIterator[str]:
    url = f"{settings.ai_provider_hub_url}/api/v1/ai/chat/stream"
    payload: dict = {
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": settings.rag_max_output_tokens,
    }
    if model:
        payload["model"] = model
    if provider:
        payload["provider"] = provider

    async with httpx.AsyncClient(timeout=900.0) as client:
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


async def _call_llm(
    user_query: str,
    system_prompt: str,
    model: str | None = None,
    provider: str | None = None,
    history: list[dict] | None = None,
) -> str:
    messages = _messages_single_turn(system_prompt, history, user_query)
    return await _call_llm_messages(messages, model=model, provider=provider)


async def _stream_llm(
    user_query: str,
    system_prompt: str,
    model: str | None = None,
    provider: str | None = None,
    history: list[dict] | None = None,
) -> AsyncIterator[str]:
    messages = _messages_single_turn(system_prompt, history, user_query)
    async for token in _stream_llm_messages(messages, model=model, provider=provider):
        yield token
