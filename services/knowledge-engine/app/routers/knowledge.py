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
    create_kb_with_profile,
    delete_document,
    delete_kb,
    get_document,
    get_graph,
    get_kb,
    get_stats,
    get_task,
    list_documents,
    list_kbs,
    list_tasks,
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
        payload.kb_id, payload.title, payload.text, payload.source_url, payload.source_type,
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
    return {"code": 200, "message": "success", "data": await list_tasks(kb_id=kb_id, status=status_filter, limit=safe_limit)}


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
    """RAG query: retrieves context from knowledge base and generates an answer via LLM."""
    from app.services.rag_chain import rag_query, rag_stream

    if not await get_kb(payload.kb_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")

    kb = await get_kb(payload.kb_id)

    if payload.stream:
        async def event_gen() -> AsyncGenerator[dict[str, str], None]:
            async for chunk in rag_stream(
                kb_id=payload.kb_id,
                query=payload.query,
                top_k=payload.top_k,
                model=payload.model,
                provider=payload.provider,
                embedding_model=kb["embedding_model"] if kb else None,
                embedding_provider=kb.get("embedding_provider") if kb else None,
                session_id=payload.session_id,
            ):
                yield {"event": "message", "data": json.dumps(chunk, ensure_ascii=False)}

        return EventSourceResponse(event_gen())

    result = await rag_query(
        kb_id=payload.kb_id,
        query=payload.query,
        top_k=payload.top_k,
        model=payload.model,
        provider=payload.provider,
        embedding_model=kb["embedding_model"] if kb else None,
        embedding_provider=kb.get("embedding_provider") if kb else None,
        session_id=payload.session_id,
    )
    return {"code": 200, "message": "success", "data": result}


# ═══ Documents ═══

@router.get("/documents/{document_id}")
async def document_detail(document_id: str) -> dict:
    doc = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return {"code": 200, "message": "success", "data": doc}


@router.get("/documents")
async def documents(kb_id: str | None = None, search: str | None = None, limit: int = 50) -> dict:
    safe_limit = max(1, min(limit, 200))
    data = await list_documents(kb_id=kb_id, search=search, limit=safe_limit)
    return {"code": 200, "message": "success", "data": data}


@router.delete("/documents/{document_id}")
async def remove_document(document_id: str) -> dict:
    ok = await delete_document(document_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return {"code": 200, "message": "success", "data": {"deleted": True}}


# ═══ Graph & Stats ═══

@router.get("/graph/{kb_id}")
async def graph(kb_id: str) -> dict:
    if not await get_kb(kb_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    return {"code": 200, "message": "success", "data": await get_graph(kb_id)}


@router.get("/stats")
async def stats() -> dict:
    return {"code": 200, "message": "success", "data": await get_stats()}
