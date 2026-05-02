import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, status
from sse_starlette.sse import EventSourceResponse

from app.schemas import (
    IngestRequest,
    KnowledgeBaseCreateRequest,
    QueryRequest,
    RAGRequest,
    SearchRequest,
)
from app.services.ingestion import (
    batch_delete_tasks,
    batch_retry_failed,
    create_kb_with_profile,
    delete_document,
    delete_kb,
    delete_task,
    get_document,
    get_graph,
    get_kb,
    get_stats,
    get_task,
    list_document_chunks,
    list_documents,
    list_kbs,
    list_tasks,
    rebuild_kb,
    retry_task,
    search_chunks,
    submit_ingestion_task,
)
from app.services.document_parser import extract_text, SUPPORTED_EXTENSIONS

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


# ═══ Knowledge Bases ═══

@router.post("/bases")
async def create_base(payload: KnowledgeBaseCreateRequest) -> dict:
    kb = await create_kb_with_profile(
        name=payload.name,
        description=payload.description,
        embedding_provider=payload.embedding_provider,
        embedding_model=payload.embedding_model,
        dimension=payload.dimension,
    )
    return {"code": 200, "message": "success", "data": kb}


@router.get("/bases")
async def list_bases() -> dict:
    return {"code": 200, "message": "success", "data": await list_kbs()}


@router.delete("/bases/{kb_id}")
async def remove_base(kb_id: str) -> dict:
    ok = await delete_kb(kb_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    return {"code": 200, "message": "success", "data": {"deleted": True}}


# ═══ Ingestion ═══

@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest(payload: IngestRequest) -> dict:
    kb = await get_kb(payload.kb_id)
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    task_id = await submit_ingestion_task(
        payload.kb_id,
        payload.title,
        payload.text,
        payload.source_url,
        payload.source_type,
        metadata=payload.metadata,
        skip_chunking=payload.skip_chunking,
    )
    return {"code": 202, "message": "accepted", "data": {"task_id": task_id}}


@router.post("/documents/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_file(
    file: UploadFile = File(...),
    kb_id: str = Form(...),
    title: str = Form(None),
    source_url: str = Form(None),
    source_type: str = Form("doc"),
) -> dict:
    """Upload and ingest a document file (PDF, DOCX, TXT, MD, HTML)."""
    kb = await get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")

    filename = file.filename or "unknown.txt"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: .{ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    content = await file.read()
    text = extract_text(content, filename)
    if not text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not extract text from file")

    doc_title = title or filename.rsplit(".", 1)[0]
    task_id = await submit_ingestion_task(kb_id, doc_title, text, source_url, source_type, filename)
    return {"code": 202, "message": "accepted", "data": {"task_id": task_id, "filename": filename, "text_length": len(text)}}


# ═══ Tasks ═══

@router.get("/tasks/{task_id}")
async def task_status(task_id: str) -> dict:
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return {"code": 200, "message": "success", "data": task}


@router.get("/tasks")
async def tasks(
    kb_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 50,
) -> dict:
    safe_limit = max(1, min(limit, 200))
    result = await list_tasks(kb_id=kb_id, status=status_filter, limit=safe_limit)
    return {"code": 200, "message": "success", "data": result["items"], "counts": result["counts"]}


@router.post("/tasks/{task_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry(task_id: str) -> dict:
    try:
        new_task_id = await retry_task(task_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "task not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    return {"code": 202, "message": "accepted", "data": {"task_id": new_task_id}}


@router.post("/tasks/batch-retry", status_code=status.HTTP_202_ACCEPTED)
async def batch_retry(payload: dict = {}) -> dict:
    """Retry all failed tasks, optionally filtered by kb_id."""
    kb_id = payload.get("kb_id")
    result = await batch_retry_failed(kb_id=kb_id)
    return {"code": 202, "message": "accepted", "data": result}


@router.delete("/tasks/{task_id}")
async def remove_task(task_id: str) -> dict:
    ok = await delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return {"code": 200, "message": "success", "data": {"deleted": True}}


@router.post("/tasks/batch-delete")
async def batch_delete(payload: dict = {}) -> dict:
    """Delete tasks by status filter, kb_id, or explicit task_ids list."""
    result = await batch_delete_tasks(
        status_filter=payload.get("status"),
        kb_id=payload.get("kb_id"),
        task_ids=payload.get("task_ids"),
    )
    return {"code": 200, "message": "success", "data": result}


# ═══ Search ═══

@router.post("/query")
async def query(payload: QueryRequest) -> dict:
    if not await get_kb(payload.kb_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    ranked = await search_chunks(payload.kb_id, payload.query, payload.top_k)
    return {"code": 200, "message": "success", "data": ranked}


@router.post("/search")
async def search(payload: SearchRequest) -> dict:
    """Enhanced semantic search endpoint with filtering."""
    from app.services.embedding_client import embed_texts
    from app.services.vector_search import search_by_vector
    from app.services.hybrid_search import fulltext_search, hybrid_search
    from app.config import settings

    query_vecs = await embed_texts([payload.query], model=settings.embedding_model, provider=settings.embedding_provider)

    if payload.search_type == "vector":
        results = await search_by_vector(
            payload.kb_id or "", query_vecs[0], top_k=payload.top_k, score_threshold=payload.score_threshold,
        )
    elif payload.search_type == "fulltext":
        results = await fulltext_search(payload.kb_id or "", payload.query, top_k=payload.top_k)
    else:
        results = await hybrid_search(payload.kb_id or "", payload.query, query_vecs[0], top_k=payload.top_k)

    if payload.score_threshold > 0:
        results = [r for r in results if r.get("score", 0) >= payload.score_threshold]

    return {
        "code": 200,
        "message": "success",
        "data": {
            "results": results,
            "search_type": payload.search_type,
            "total_found": len(results),
        },
    }


# ═══ RAG ═══

@router.post("/rag")
async def rag(payload: RAGRequest) -> dict:
    """RAG query: retrieves context from one or more knowledge bases and generates an answer via LLM."""
    from app.services.rag_chain import rag_query, rag_stream

    kb_ids = payload.resolved_kb_ids()
    if not kb_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="at least one kb_id is required")

    kbs: list[dict] = []
    for kid in kb_ids:
        kb = await get_kb(kid)
        if not kb:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"knowledge base {kid} not found")
        kbs.append(kb)

    kb_embedding_map = {
        kb["id"]: {
            "embedding_model": kb.get("embedding_model"),
            "embedding_provider": kb.get("embedding_provider"),
        }
        for kb in kbs
    }

    if payload.stream:
        async def event_gen() -> AsyncGenerator[dict[str, str], None]:
            async for chunk in rag_stream(
                kb_ids=kb_ids,
                query=payload.query,
                top_k=payload.top_k,
                model=payload.model,
                provider=payload.provider,
                kb_embedding_map=kb_embedding_map,
                session_id=payload.session_id,
                target_chars=payload.target_chars,
                continue_max_rounds=payload.continue_max_rounds,
                persona_prompt=payload.persona_prompt,
            ):
                yield {"event": "message", "data": json.dumps(chunk, ensure_ascii=False)}

        return EventSourceResponse(event_gen())

    result = await rag_query(
        kb_ids=kb_ids,
        query=payload.query,
        top_k=payload.top_k,
        model=payload.model,
        provider=payload.provider,
        kb_embedding_map=kb_embedding_map,
        session_id=payload.session_id,
        target_chars=payload.target_chars,
        continue_max_rounds=payload.continue_max_rounds,
        persona_prompt=payload.persona_prompt,
    )
    return {"code": 200, "message": "success", "data": result}


# ═══ Shared retrieval + persona-only generation (for roundtable) ═══

@router.post("/rag/prepare")
async def rag_prepare(payload: dict) -> dict:
    """Run retrieval+rerank+CRAG+compression ONCE, return chunks/sources/context.

    Designed for roundtable: the controller then calls /rag/generate N times
    with different persona prompts but shares this prepared context — saving
    N× of query enhancement, embedding, hybrid search, rerank, and CRAG.
    """
    from app.services.rag_chain import prepare_rag

    kb_ids = payload.get("kb_ids") or []
    if isinstance(kb_ids, str):
        kb_ids = [kb_ids]
    kb_ids = [k for k in kb_ids if k]
    if not kb_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="at least one kb_id is required")

    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="query is required")

    kbs: list[dict] = []
    for kid in kb_ids:
        kb = await get_kb(kid)
        if not kb:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"knowledge base {kid} not found")
        kbs.append(kb)

    kb_embedding_map = {
        kb["id"]: {
            "embedding_model": kb.get("embedding_model"),
            "embedding_provider": kb.get("embedding_provider"),
        }
        for kb in kbs
    }

    top_k = payload.get("top_k")
    if top_k is not None:
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = None

    result = await prepare_rag(
        kb_ids=kb_ids,
        query=query,
        top_k=top_k,
        kb_embedding_map=kb_embedding_map,
    )
    return {"code": 200, "message": "success", "data": result}


@router.post("/rag/generate")
async def rag_generate(payload: dict):
    """Stream LLM answer against a pre-prepared RAG context (no retrieval).

    Frontends should pass the `context` / `sources` / `graph_context` /
    `crag_result` returned from `/rag/prepare` plus `query` and an optional
    `persona_prompt`. Streams SSE events identical in shape to /rag (stream).
    """
    from app.services.rag_chain import generate_with_chunks_stream

    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="query is required")

    context = payload.get("context") or ""
    sources = payload.get("sources") or []
    graph_context = payload.get("graph_context") or ""
    crag_result = payload.get("crag_result") or None
    persona_prompt = payload.get("persona_prompt")
    model = payload.get("model")
    provider = payload.get("provider")
    target_chars = payload.get("target_chars")
    continue_max_rounds = payload.get("continue_max_rounds")

    async def event_gen() -> AsyncGenerator[dict[str, str], None]:
        async for chunk in generate_with_chunks_stream(
            query=query,
            context=context,
            sources=sources,
            graph_context=graph_context,
            crag_result=crag_result,
            persona_prompt=persona_prompt,
            model=model,
            provider=provider,
            target_chars=target_chars,
            continue_max_rounds=continue_max_rounds,
        ):
            yield {"event": "message", "data": json.dumps(chunk, ensure_ascii=False)}

    return EventSourceResponse(event_gen())


# ═══ Retrieve (pure hybrid search, no LLM) ═══

@router.post("/retrieve")
async def retrieve(payload: dict) -> dict:
    """纯检索端点：多 KB hybrid search + 三层融合（保底+过滤+上限），不走 LLM。

    供 ad-review / content-studio / briefs 等跨服务模块消费。相比 /rag 省一次 LLM，
    返回已合并/重排的 snippets，调用方直接用（配合 format_kb_snippets）。

    ## 三层融合策略
    1. **保底** (`min_per_kb`): 每个 KB 至少保留 N 条（不受 score_threshold 约束），
       避免"高分 KB 把其他 KB 完全挤掉"丧失来源多样性。
    2. **过滤** (`score_threshold`): 保底条目之外，低于阈值的丢弃。
    3. **总量上限** (`total_limit`): 合并后按 score 降序截断，防止 token 爆炸。

    ## Payload
        {
          "kb_ids": ["uuid", ...],        # 必填
          "query": "...",                 # 必填
          "top_k_per_kb": 4,              # 每个 KB 的候选条数上限,默认 5
          "min_per_kb": 1,                # 每 KB 保底条数,默认 0（无保底）
          "score_threshold": 0.0,         # 过滤阈值,默认 0
          "total_limit": null,            # 合并后总数上限,null=不限
          "time_decay": false,
          "decay_days": 45.0,

          # 向后兼容
          "top_k": 5                      # 已废弃,等价于 top_k_per_kb
        }

    ## Response
        {
          "code": 200,
          "data": {
            "snippets": [
              {"source":"<kb_name>", "kb_id":"<uuid>", "id":"<chunk_id>",
               "score":0.87, "content":"...", "title":"..."},
              ...
            ],
            "kb_resolved": [{"id":"<uuid>", "name":"<kb_name>"}, ...],
            "stats": {
              "total_raw": 12,            # 所有 KB 候选总数
              "total_after_fusion": 8,    # 融合后返回数
              "per_kb_returned": {"<uuid>": 3, ...}
            }
          }
        }
    """
    from app.services.rag_chain import retrieve_only

    kb_ids = payload.get("kb_ids") or ([payload["kb_id"]] if payload.get("kb_id") else [])
    if not kb_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kb_ids required")
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="query required")

    # Accept both new (top_k_per_kb) and legacy (top_k) parameter names
    top_k_per_kb = int(payload.get("top_k_per_kb") or payload.get("top_k") or 5)
    min_per_kb = max(0, int(payload.get("min_per_kb") or 0))
    score_threshold = float(payload.get("score_threshold") or 0)
    raw_total_limit = payload.get("total_limit")
    total_limit = int(raw_total_limit) if raw_total_limit else None
    time_decay = bool(payload.get("time_decay") or False)
    decay_days = float(payload.get("decay_days") or 45.0)

    # Resolve KB id → name
    kb_resolved: list[dict] = []
    for kid in kb_ids:
        kb = await get_kb(kid)
        if not kb:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"KB {kid} not found")
        kb_resolved.append({"id": kid, "name": kb.get("name") or kid[:8]})

    # Step 1: fetch top_k_per_kb candidates from each KB (no filtering yet)
    per_kb_hits: dict[str, list[dict]] = {}
    total_raw = 0
    for kb in kb_resolved:
        try:
            hits = await retrieve_only(
                query, kb["id"], top_k=top_k_per_kb,
                time_decay=time_decay, decay_days=decay_days,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("retrieve kb=%s failed: %s", kb["id"], exc)
            hits = []
        # Sort each KB's hits by score desc (retrieve_only usually already sorted, but be safe)
        hits = sorted(hits, key=lambda h: float(h.get("score") or 0), reverse=True)
        per_kb_hits[kb["id"]] = hits
        total_raw += len(hits)

    def _mk_snippet(kb: dict, h: dict) -> dict:
        return {
            "source": kb["name"],
            "kb_id": kb["id"],
            "id": str(h.get("id") or ""),
            "score": float(h.get("score") or 0),
            "content": (h.get("content") or ""),
            "title": h.get("title"),
        }

    # Step 2: build "guaranteed" pool (每 KB 保底 min_per_kb 条,不受 threshold 约束)
    # + "candidate" pool (过滤 threshold 后的剩余)
    guaranteed: list[dict] = []
    candidates: list[dict] = []
    for kb in kb_resolved:
        hits = per_kb_hits.get(kb["id"], [])
        for idx, h in enumerate(hits):
            snippet = _mk_snippet(kb, h)
            if idx < min_per_kb:
                guaranteed.append(snippet)
            elif snippet["score"] >= score_threshold:
                candidates.append(snippet)

    # Step 3: dedupe (same chunk id 跨 KB 理论上不会,但保险起见),然后合并
    seen_ids: set[str] = set()
    merged: list[dict] = []
    for s in guaranteed + sorted(candidates, key=lambda x: x["score"], reverse=True):
        key = f'{s["kb_id"]}:{s["id"]}'
        if key in seen_ids:
            continue
        seen_ids.add(key)
        merged.append(s)

    # Step 4: total_limit 按 score 截断(但永远不会砍掉 guaranteed 部分)
    if total_limit and len(merged) > total_limit:
        guaranteed_count = len(guaranteed)
        if guaranteed_count >= total_limit:
            merged = merged[:total_limit]
        else:
            head = merged[:guaranteed_count]
            tail = sorted(merged[guaranteed_count:], key=lambda x: x["score"], reverse=True)
            merged = head + tail[: (total_limit - guaranteed_count)]

    # Stats
    per_kb_returned: dict[str, int] = {kb["id"]: 0 for kb in kb_resolved}
    for s in merged:
        per_kb_returned[s["kb_id"]] = per_kb_returned.get(s["kb_id"], 0) + 1

    return {
        "code": 200,
        "message": "success",
        "data": {
            "snippets": merged,
            "kb_resolved": kb_resolved,
            "stats": {
                "total_raw": total_raw,
                "total_after_fusion": len(merged),
                "per_kb_returned": per_kb_returned,
            },
        },
    }


# ═══ RAG Evaluation ═══

@router.post("/rag/evaluate")
async def rag_evaluate(payload: dict) -> dict:
    """A/B evaluation: compare RAG with all optimizations vs baseline."""
    from app.services.rag_evaluator import evaluate_ab, evaluate_batch

    query = payload.get("query", "")
    queries = payload.get("queries", [])
    kb_ids = payload.get("kb_ids", [])
    if not kb_ids and payload.get("kb_id"):
        kb_ids = [payload["kb_id"]]
    if not kb_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kb_ids required")

    kbs: list[dict] = []
    for kid in kb_ids:
        kb = await get_kb(kid)
        if not kb:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"KB {kid} not found")
        kbs.append(kb)

    kb_embedding_map = {
        kb["id"]: {
            "embedding_model": kb.get("embedding_model"),
            "embedding_provider": kb.get("embedding_provider"),
        }
        for kb in kbs
    }

    top_k = payload.get("top_k", 5)
    model = payload.get("model")
    provider = payload.get("provider")

    if queries:
        result = await evaluate_batch(queries, kb_ids, kb_embedding_map, top_k, model, provider)
    elif query:
        result = await evaluate_ab(query, kb_ids, kb_embedding_map, top_k, model, provider)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="query or queries required")

    return {"code": 200, "message": "success", "data": result}


# ═══ Documents ═══

@router.get("/documents/{document_id}")
async def document_detail(document_id: str) -> dict:
    doc = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return {"code": 200, "message": "success", "data": doc}


@router.get("/documents")
async def documents(
    kb_id: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    result = await list_documents(kb_id=kb_id, search=search, limit=safe_limit, offset=safe_offset)
    return {"code": 200, "message": "success", "data": result["items"], "total": result["total"]}


@router.get("/documents/{document_id}/chunks")
async def document_chunks(
    document_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    doc = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    chunks = await list_document_chunks(document_id, limit=limit, offset=offset)
    return {"code": 200, "message": "success", "data": chunks}


@router.delete("/documents/{document_id}")
async def remove_document(document_id: str) -> dict:
    ok = await delete_document(document_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return {"code": 200, "message": "success", "data": {"deleted": True}}


# ═══ KB Rebuild ═══

@router.post("/bases/{kb_id}/rebuild", status_code=status.HTTP_202_ACCEPTED)
async def rebuild_base(kb_id: str) -> dict:
    """Re-ingest all documents with the optimized pipeline (contextual headers + semantic chunking + HyPE + GraphRAG)."""
    kb = await get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    try:
        result = await rebuild_kb(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"code": 202, "message": "accepted", "data": result}


# ═══ Graph & Stats ═══

@router.get("/graph/{kb_id}")
async def graph(kb_id: str) -> dict:
    if not await get_kb(kb_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    return {"code": 200, "message": "success", "data": await get_graph(kb_id)}


@router.get("/stats")
async def stats() -> dict:
    return {"code": 200, "message": "success", "data": await get_stats()}
