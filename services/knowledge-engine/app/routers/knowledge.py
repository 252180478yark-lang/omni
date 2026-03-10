from fastapi import APIRouter, HTTPException, Query, status

from app.schemas import IngestRequest, KnowledgeBaseCreateRequest, QueryRequest
from app.services.ingestion import (
    create_kb_with_profile,
    delete_document,
    delete_kb,
    get_document,
    get_stats,
    get_graph,
    get_kb,
    get_task,
    list_documents,
    list_tasks,
    list_kbs,
    retry_task,
    search_chunks,
    submit_ingestion_task,
)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


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
    return {"code": 200, "message": "success", "data": list_kbs()}


@router.delete("/bases/{kb_id}")
async def remove_base(kb_id: str) -> dict:
    ok = delete_kb(kb_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    return {"code": 200, "message": "success", "data": {"deleted": True}}


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest(payload: IngestRequest) -> dict:
    kb = get_kb(payload.kb_id)
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    task_id = submit_ingestion_task(payload.kb_id, payload.title, payload.text, payload.source_url)
    return {"code": 202, "message": "accepted", "data": {"task_id": task_id}}


@router.get("/tasks/{task_id}")
async def task_status(task_id: str) -> dict:
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return {"code": 200, "message": "success", "data": task}


@router.get("/tasks")
async def tasks(kb_id: str | None = None, status_filter: str | None = Query(default=None, alias="status"), limit: int = 50) -> dict:
    safe_limit = max(1, min(limit, 200))
    return {"code": 200, "message": "success", "data": list_tasks(kb_id=kb_id, status=status_filter, limit=safe_limit)}


@router.post("/tasks/{task_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry(task_id: str) -> dict:
    try:
        new_task_id = retry_task(task_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "task not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    return {"code": 202, "message": "accepted", "data": {"task_id": new_task_id}}


@router.post("/query")
async def query(payload: QueryRequest) -> dict:
    if not get_kb(payload.kb_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    ranked = await search_chunks(payload.kb_id, payload.query, payload.top_k)
    return {"code": 200, "message": "success", "data": ranked}


@router.get("/graph/{kb_id}")
async def graph(kb_id: str) -> dict:
    if not get_kb(kb_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    return {"code": 200, "message": "success", "data": get_graph(kb_id)}


@router.get("/documents/{document_id}")
async def document_detail(document_id: str) -> dict:
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return {"code": 200, "message": "success", "data": doc}


@router.get("/documents")
async def documents(kb_id: str | None = None, search: str | None = None, limit: int = 50) -> dict:
    safe_limit = max(1, min(limit, 200))
    data = list_documents(kb_id=kb_id, search=search, limit=safe_limit)
    return {"code": 200, "message": "success", "data": data}


@router.delete("/documents/{document_id}")
async def remove_document(document_id: str) -> dict:
    ok = delete_document(document_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return {"code": 200, "message": "success", "data": {"deleted": True}}


@router.get("/stats")
async def stats() -> dict:
    return {"code": 200, "message": "success", "data": get_stats()}
