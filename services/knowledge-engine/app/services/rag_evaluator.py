"""RAG pipeline evaluation — A/B comparison with and without optimizations.

Provides:
1. Pipeline telemetry: timing + quality metrics at each stage
2. A/B comparison: same query with optimizations enabled vs disabled
3. LLM-based answer quality scoring (faithfulness, relevancy, completeness)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings
from app.services.context_compressor import compress_chunks
from app.services.crag import evaluate_retrieval
from app.services.embedding_client import embed_texts
from app.services.graph_search import graph_search
from app.services.hybrid_search import enrich_with_context_window, hybrid_search
from app.services.intent_router import classify_intent
from app.services.query_enhancer import enhance_query
from app.services.reranker import cross_encoder_rerank

logger = logging.getLogger(__name__)

_EVAL_MODEL = "gemini-3.1-flash-lite-preview"


# ═══ Telemetry Data ═══

@dataclass
class StageMetric:
    name: str
    duration_ms: float = 0
    input_count: int = 0
    output_count: int = 0
    details: dict = field(default_factory=dict)


@dataclass
class PipelineTrace:
    query: str
    mode: str  # "optimized" or "baseline"
    stages: list[StageMetric] = field(default_factory=list)
    total_ms: float = 0
    answer: str = ""
    sources: list[dict] = field(default_factory=list)
    chunk_scores: list[float] = field(default_factory=list)
    quality_scores: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "mode": self.mode,
            "total_ms": round(self.total_ms, 1),
            "stages": [
                {
                    "name": s.name,
                    "duration_ms": round(s.duration_ms, 1),
                    "input_count": s.input_count,
                    "output_count": s.output_count,
                    "details": s.details,
                }
                for s in self.stages
            ],
            "answer_length": len(self.answer),
            "answer_preview": self.answer[:500],
            "source_count": len(self.sources),
            "avg_chunk_score": round(sum(self.chunk_scores) / len(self.chunk_scores), 4) if self.chunk_scores else 0,
            "quality_scores": self.quality_scores,
        }


# ═══ Instrumented Pipeline ═══

async def _run_instrumented_pipeline(
    query: str,
    kb_ids: list[str],
    kb_embedding_map: dict[str, dict],
    top_k: int,
    model: str | None,
    provider: str | None,
    *,
    enable_query_rewrite: bool = True,
    enable_hyde: bool = True,
    enable_subquery: bool = True,
    enable_hype: bool = True,
    enable_rerank: bool = True,
    enable_context_window: bool = True,
    enable_compression: bool = True,
    enable_crag: bool = True,
    mode_label: str = "optimized",
) -> PipelineTrace:
    """Run the RAG pipeline with instrumentation at every stage."""
    trace = PipelineTrace(query=query, mode=mode_label)
    pipeline_start = time.perf_counter()

    # ── Stage 1: Query Enhancement ──
    t0 = time.perf_counter()
    search_query = query
    sub_queries = [query]
    hyde_text = ""

    if enable_query_rewrite or enable_hyde or enable_subquery:
        old_rewrite = settings.rag_query_rewrite
        old_hyde = settings.rag_hyde
        old_subquery = settings.rag_subquery
        settings.rag_query_rewrite = enable_query_rewrite
        settings.rag_hyde = enable_hyde
        settings.rag_subquery = enable_subquery
        try:
            enhanced = await enhance_query(query)
            search_query = enhanced.get("rewritten", query) if enable_query_rewrite else query
            hyde_text = enhanced.get("hypothetical_answer", "") if enable_hyde else ""
            sub_queries = enhanced.get("sub_queries", [query]) if enable_subquery else [query]
        finally:
            settings.rag_query_rewrite = old_rewrite
            settings.rag_hyde = old_hyde
            settings.rag_subquery = old_subquery

    stage1 = StageMetric(
        name="query_enhancement",
        duration_ms=(time.perf_counter() - t0) * 1000,
        details={
            "rewritten": search_query != query,
            "rewritten_query": search_query if search_query != query else "",
            "hyde_generated": bool(hyde_text),
            "hyde_length": len(hyde_text),
            "sub_queries": len(sub_queries),
        },
    )
    trace.stages.append(stage1)

    # ── Stage 2: Embedding ──
    t0 = time.perf_counter()
    unique_models: dict[str, tuple[str, str]] = {}
    for kid in kb_ids:
        info = kb_embedding_map.get(kid, {})
        m = info.get("embedding_model") or settings.embedding_model
        p = info.get("embedding_provider") or settings.embedding_provider
        key = f"{p}/{m}"
        if key not in unique_models:
            unique_models[key] = (m, p)
    if not unique_models:
        unique_models[f"{settings.embedding_provider}/{settings.embedding_model}"] = (
            settings.embedding_model, settings.embedding_provider,
        )

    texts_to_embed = [search_query]
    if hyde_text:
        texts_to_embed.append(hyde_text)

    first_model, first_prov = next(iter(unique_models.values()))
    vecs = await embed_texts(texts_to_embed, model=first_model, provider=first_prov)
    query_embedding = vecs[0]
    hyde_embedding = vecs[1] if len(vecs) > 1 else None

    trace.stages.append(StageMetric(
        name="embedding",
        duration_ms=(time.perf_counter() - t0) * 1000,
        input_count=len(texts_to_embed),
        details={"model": first_model},
    ))

    # ── Stage 3: Retrieval ──
    t0 = time.perf_counter()
    all_chunks: list[dict] = []
    all_graph_contexts: list[str] = []

    retrieval_tasks = []
    for kid in kb_ids:
        for sq in sub_queries:
            emb = hyde_embedding if hyde_embedding else query_embedding
            old_hype = settings.hype_enabled
            settings.hype_enabled = enable_hype
            retrieval_tasks.append(hybrid_search(kid, sq, emb, top_k=top_k * 3, include_hype=enable_hype))
            settings.hype_enabled = old_hype
        retrieval_tasks.append(graph_search(kid, query))

    results = await asyncio.gather(*retrieval_tasks, return_exceptions=True)

    hybrid_count = 0
    graph_entity_count = 0
    for res in results:
        if isinstance(res, BaseException):
            continue
        if isinstance(res, list):
            all_chunks.extend(res)
            hybrid_count += len(res)
        elif isinstance(res, dict):
            graph_entity_count += len(res.get("entities", []))
            for gc in res.get("graph_chunks", []):
                if gc["id"] not in {c["id"] for c in all_chunks}:
                    all_chunks.append(gc)
            ctx = res.get("graph_context", "")
            if ctx:
                all_graph_contexts.append(ctx)

    # Deduplicate
    seen_fp: set[str] = set()
    deduped: list[dict] = []
    for c in all_chunks:
        fp = c["content"][:200]
        if fp not in seen_fp:
            seen_fp.add(fp)
            deduped.append(c)

    trace.stages.append(StageMetric(
        name="retrieval",
        duration_ms=(time.perf_counter() - t0) * 1000,
        input_count=len(sub_queries),
        output_count=len(deduped),
        details={
            "hybrid_raw": hybrid_count,
            "graph_entities": graph_entity_count,
            "after_dedup": len(deduped),
        },
    ))

    # ── Stage 4: Reranking ──
    t0 = time.perf_counter()
    if enable_rerank:
        old_rerank = settings.rag_cross_encoder_rerank
        settings.rag_cross_encoder_rerank = True
        reranked = await cross_encoder_rerank(query, deduped, top_n=top_k)
        settings.rag_cross_encoder_rerank = old_rerank
    else:
        threshold = settings.rag_score_threshold
        above = [c for c in deduped if c.get("score", 0) >= threshold]
        reranked = (above if above else deduped)[:top_k]

    trace.stages.append(StageMetric(
        name="reranking",
        duration_ms=(time.perf_counter() - t0) * 1000,
        input_count=len(deduped),
        output_count=len(reranked),
        details={"method": "cross_encoder" if enable_rerank else "threshold"},
    ))
    trace.chunk_scores = [c.get("score", 0) for c in reranked]

    # ── Stage 5: Context Window ──
    t0 = time.perf_counter()
    if enable_context_window:
        enriched = await enrich_with_context_window(reranked)
    else:
        enriched = reranked

    trace.stages.append(StageMetric(
        name="context_window",
        duration_ms=(time.perf_counter() - t0) * 1000,
        input_count=len(reranked),
        output_count=len(enriched),
        details={"enabled": enable_context_window},
    ))

    # ── Stage 6: CRAG ──
    t0 = time.perf_counter()
    crag_verdict = "SKIPPED"
    if enable_crag:
        old_crag = settings.rag_crag_enabled
        settings.rag_crag_enabled = True
        crag_result = await evaluate_retrieval(query, enriched)
        crag_verdict = crag_result.verdict
        settings.rag_crag_enabled = old_crag
    trace.stages.append(StageMetric(
        name="crag",
        duration_ms=(time.perf_counter() - t0) * 1000,
        details={"verdict": crag_verdict, "enabled": enable_crag},
    ))

    # ── Stage 7: Compression ──
    t0 = time.perf_counter()
    if enable_compression:
        old_comp = settings.rag_contextual_compression
        settings.rag_contextual_compression = True
        compressed = await compress_chunks(query, enriched)
        settings.rag_contextual_compression = old_comp
    else:
        compressed = enriched

    orig_len = sum(len(c["content"]) for c in enriched)
    comp_len = sum(len(c["content"]) for c in compressed)
    trace.stages.append(StageMetric(
        name="compression",
        duration_ms=(time.perf_counter() - t0) * 1000,
        input_count=len(enriched),
        output_count=len(compressed),
        details={
            "enabled": enable_compression,
            "original_chars": orig_len,
            "compressed_chars": comp_len,
            "reduction_pct": round((1 - comp_len / orig_len) * 100, 1) if orig_len else 0,
        },
    ))

    # ── Stage 8: Generation ──
    t0 = time.perf_counter()
    graph_ctx = "\n\n".join(all_graph_contexts) if all_graph_contexts else ""
    context_parts = []
    for i, chunk in enumerate(compressed, start=1):
        source = chunk.get("title") or "unknown"
        context_parts.append(f"[{i}] {chunk['content']}\n    (来源: {source})")
    context_str = "\n\n".join(context_parts)

    from app.services.rag_chain import RAG_SYSTEM_PROMPT, _CRAG_AUGMENT_PROMPT
    system_prompt = RAG_SYSTEM_PROMPT.format(
        context=context_str,
        graph_context=graph_ctx or "（无图谱数据）",
    )
    if crag_verdict in ("AMBIGUOUS", "INCORRECT"):
        system_prompt += _CRAG_AUGMENT_PROMPT.format(reason="检索质量评估为" + crag_verdict)

    answer = await _call_llm_eval(query, system_prompt, model=model, provider=provider)
    trace.stages.append(StageMetric(
        name="generation",
        duration_ms=(time.perf_counter() - t0) * 1000,
        details={"answer_length": len(answer)},
    ))

    trace.answer = answer
    trace.sources = [
        {"chunk_id": c["id"], "title": c.get("title", ""), "score": c.get("score", 0)}
        for c in compressed
    ]
    trace.total_ms = (time.perf_counter() - pipeline_start) * 1000

    return trace


# ═══ A/B Comparison ═══

async def evaluate_ab(
    query: str,
    kb_ids: list[str],
    kb_embedding_map: dict[str, dict] | None = None,
    top_k: int = 5,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """Run same query through optimized and baseline pipelines, compare results."""
    emb_map = kb_embedding_map or {}

    optimized_task = _run_instrumented_pipeline(
        query, kb_ids, emb_map, top_k, model, provider,
        enable_query_rewrite=True,
        enable_hyde=True,
        enable_subquery=True,
        enable_hype=True,
        enable_rerank=True,
        enable_context_window=True,
        enable_compression=True,
        enable_crag=True,
        mode_label="optimized",
    )

    baseline_task = _run_instrumented_pipeline(
        query, kb_ids, emb_map, top_k, model, provider,
        enable_query_rewrite=False,
        enable_hyde=False,
        enable_subquery=False,
        enable_hype=False,
        enable_rerank=False,
        enable_context_window=False,
        enable_compression=False,
        enable_crag=False,
        mode_label="baseline",
    )

    optimized, baseline = await asyncio.gather(optimized_task, baseline_task)

    quality_task_opt = _score_answer_quality(query, optimized.answer, optimized.sources)
    quality_task_base = _score_answer_quality(query, baseline.answer, baseline.sources)
    q_opt, q_base = await asyncio.gather(quality_task_opt, quality_task_base)
    optimized.quality_scores = q_opt
    baseline.quality_scores = q_base

    comparison = _build_comparison(optimized, baseline)

    return {
        "query": query,
        "optimized": optimized.to_dict(),
        "baseline": baseline.to_dict(),
        "comparison": comparison,
    }


async def evaluate_batch(
    queries: list[str],
    kb_ids: list[str],
    kb_embedding_map: dict[str, dict] | None = None,
    top_k: int = 5,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """Run A/B evaluation on multiple queries and aggregate results."""
    results = []
    for q in queries:
        try:
            r = await evaluate_ab(q, kb_ids, kb_embedding_map, top_k, model, provider)
            results.append(r)
        except Exception as exc:
            logger.error("Eval failed for query '%s': %s", q[:50], exc)
            results.append({"query": q, "error": str(exc)})

    successful = [r for r in results if "error" not in r]
    summary = _aggregate_results(successful) if successful else {}

    return {
        "total_queries": len(queries),
        "successful": len(successful),
        "failed": len(results) - len(successful),
        "summary": summary,
        "details": results,
    }


# ═══ LLM-based Quality Scoring ═══

_QUALITY_PROMPT = """\
请对以下 RAG 系统的回答进行质量评估。满分 10 分。

用户问题：{query}

系统回答：{answer}

引用来源数量：{source_count}

请从以下三个维度评分，严格返回 JSON：
{{
  "relevancy": 0-10,
  "completeness": 0-10,
  "coherence": 0-10,
  "overall": 0-10,
  "comment": "一句话评价"
}}

评分标准：
- relevancy: 回答是否紧扣问题
- completeness: 回答是否全面（不遗漏关键点）
- coherence: 回答是否条理清晰、逻辑通顺
- overall: 综合评分"""


async def _score_answer_quality(
    query: str,
    answer: str,
    sources: list[dict],
) -> dict:
    """Use LLM to score answer quality on multiple dimensions."""
    if not answer or len(answer) < 10:
        return {"relevancy": 0, "completeness": 0, "coherence": 0, "overall": 0, "comment": "无回答"}

    import json
    prompt = _QUALITY_PROMPT.format(
        query=query,
        answer=answer[:2000],
        source_count=len(sources),
    )
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{settings.ai_provider_hub_url}/api/v1/ai/chat",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 500,
                    "model": _EVAL_MODEL,
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("content", "")
        cleaned = raw.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(cleaned[start:end])
    except Exception:
        logger.debug("Quality scoring failed", exc_info=True)
    return {"relevancy": -1, "completeness": -1, "coherence": -1, "overall": -1, "comment": "评分失败"}


# ═══ Comparison Builder ═══

def _build_comparison(opt: PipelineTrace, base: PipelineTrace) -> dict:
    """Build human-readable comparison between optimized and baseline."""
    opt_quality = opt.quality_scores.get("overall", 0)
    base_quality = base.quality_scores.get("overall", 0)
    quality_diff = opt_quality - base_quality

    opt_stages = {s.name: s for s in opt.stages}
    base_stages = {s.name: s for s in base.stages}

    stage_comparison = {}
    for name in opt_stages:
        os = opt_stages[name]
        bs = base_stages.get(name)
        stage_comparison[name] = {
            "optimized_ms": round(os.duration_ms, 1),
            "baseline_ms": round(bs.duration_ms, 1) if bs else 0,
            "delta_ms": round(os.duration_ms - (bs.duration_ms if bs else 0), 1),
        }

    return {
        "quality_improvement": {
            "optimized_overall": opt_quality,
            "baseline_overall": base_quality,
            "delta": quality_diff,
            "improved": quality_diff > 0,
            "pct_change": round(quality_diff / base_quality * 100, 1) if base_quality > 0 else 0,
        },
        "latency": {
            "optimized_total_ms": round(opt.total_ms, 1),
            "baseline_total_ms": round(base.total_ms, 1),
            "overhead_ms": round(opt.total_ms - base.total_ms, 1),
            "overhead_pct": round((opt.total_ms - base.total_ms) / base.total_ms * 100, 1) if base.total_ms > 0 else 0,
        },
        "retrieval": {
            "optimized_sources": len(opt.sources),
            "baseline_sources": len(base.sources),
            "optimized_avg_score": round(sum(opt.chunk_scores) / len(opt.chunk_scores), 4) if opt.chunk_scores else 0,
            "baseline_avg_score": round(sum(base.chunk_scores) / len(base.chunk_scores), 4) if base.chunk_scores else 0,
        },
        "stage_timings": stage_comparison,
        "verdict": _verdict(quality_diff, opt.total_ms - base.total_ms),
    }


def _verdict(quality_delta: float, latency_delta: float) -> str:
    if quality_delta > 1:
        if latency_delta < 5000:
            return "显著提升，延迟可接受"
        return "显著提升，但延迟增加较多"
    if quality_delta > 0:
        return "小幅提升"
    if quality_delta == 0:
        return "质量持平"
    return "质量下降，需检查"


def _aggregate_results(results: list[dict]) -> dict:
    """Aggregate multiple A/B results into summary statistics."""
    opt_scores = []
    base_scores = []
    opt_latencies = []
    base_latencies = []
    improved_count = 0

    for r in results:
        comp = r.get("comparison", {})
        qi = comp.get("quality_improvement", {})
        lat = comp.get("latency", {})
        opt_scores.append(qi.get("optimized_overall", 0))
        base_scores.append(qi.get("baseline_overall", 0))
        opt_latencies.append(lat.get("optimized_total_ms", 0))
        base_latencies.append(lat.get("baseline_total_ms", 0))
        if qi.get("improved", False):
            improved_count += 1

    n = len(results)
    return {
        "avg_optimized_score": round(sum(opt_scores) / n, 2) if n else 0,
        "avg_baseline_score": round(sum(base_scores) / n, 2) if n else 0,
        "avg_quality_delta": round((sum(opt_scores) - sum(base_scores)) / n, 2) if n else 0,
        "improvement_rate": f"{improved_count}/{n} ({round(improved_count / n * 100)}%)" if n else "0/0",
        "avg_optimized_latency_ms": round(sum(opt_latencies) / n, 0) if n else 0,
        "avg_baseline_latency_ms": round(sum(base_latencies) / n, 0) if n else 0,
        "avg_overhead_ms": round((sum(opt_latencies) - sum(base_latencies)) / n, 0) if n else 0,
    }


# ═══ Helpers ═══

async def _call_llm_eval(
    user_query: str,
    system_prompt: str,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    url = f"{settings.ai_provider_hub_url}/api/v1/ai/chat"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]
    payload: dict = {"messages": messages, "temperature": 0.3, "max_tokens": 65536}
    if model:
        payload["model"] = model
    if provider:
        payload["provider"] = provider
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json().get("content", "")
