"""Knowledge ingestion service — PostgreSQL + pgvector backed.

Ingestion pipelines run behind an asyncio.Semaphore so that heavy embedding
+ DB-write work cannot starve the event loop that serves RAG queries.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np

from app.config import settings
from app.database import get_pool
from app.services.chunking import ChunkStrategy, auto_detect_strategy, split_text
from app.services.embedding_client import embed_texts
from app.services.graph_rag import extract_entities_and_relations
from app.services.provider_profile import resolve_embedding_profile

logger = logging.getLogger(__name__)

_INGESTION_SEMAPHORE = asyncio.Semaphore(2)
_CHUNK_INSERT_BATCH = 10

# ═══ Knowledge Base CRUD ═══


async def create_kb_with_profile(
    *,
    name: str,
    description: str,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    dimension: int | None = None,
) -> dict:
    resolved_provider, resolved_model = await resolve_embedding_profile(
        preferred_provider=embedding_provider,
        preferred_model=embedding_model,
    )
    return await create_kb(
        name=name,
        description=description,
        embedding_provider=resolved_provider,
        embedding_model=resolved_model,
        dimension=dimension or 1536,
    )


async def create_kb(
    name: str, description: str, embedding_provider: str, embedding_model: str, dimension: int,
) -> dict:
    pool = get_pool()
    kb_id = str(uuid4())
    row = await pool.fetchrow(
        """
        INSERT INTO knowledge_bases (id, name, description, embedding_provider, embedding_model, dimension)
        VALUES ($1::uuid, $2, $3, $4, $5, $6)
        RETURNING id, name, description, embedding_provider, embedding_model, dimension, created_at
        """,
        kb_id, name, description, embedding_provider, embedding_model, dimension,
    )
    return _kb_row(row)


async def list_kbs() -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, name, description, embedding_provider, embedding_model, dimension, created_at "
        "FROM knowledge_bases ORDER BY created_at DESC"
    )
    return [_kb_row(r) for r in rows]


async def get_kb(kb_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, description, embedding_provider, embedding_model, dimension, created_at "
        "FROM knowledge_bases WHERE id = $1::uuid",
        kb_id,
    )
    return _kb_row(row) if row else None


async def delete_kb(kb_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute("DELETE FROM knowledge_bases WHERE id = $1::uuid", kb_id)
    return result.endswith("1")


# ═══ Document CRUD ═══


async def get_document(document_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, kb_id, title, source_url, source_type, raw_text, chunk_count, created_at "
        "FROM documents WHERE id = $1::uuid",
        document_id,
    )
    return _doc_row(row) if row else None


async def list_document_chunks(document_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, chunk_index, content, metadata "
        "FROM knowledge_chunks WHERE document_id = $1::uuid "
        "ORDER BY chunk_index ASC LIMIT $2 OFFSET $3",
        document_id, limit, offset,
    )
    return [
        {
            "id": str(r["id"]),
            "chunk_index": r["chunk_index"],
            "content": r["content"],
            "metadata": r["metadata"],
        }
        for r in rows
    ]


async def list_documents(kb_id: str | None = None, search: str | None = None, limit: int = 50) -> list[dict]:
    pool = get_pool()
    clauses = []
    params: list[object] = []
    idx = 1

    if kb_id:
        clauses.append(f"d.kb_id = ${idx}::uuid")
        params.append(kb_id)
        idx += 1
    if search:
        clauses.append(f"d.title ILIKE ${idx}")
        params.append(f"%{search}%")
        idx += 1

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    rows = await pool.fetch(
        f"""
        SELECT d.id, d.kb_id, d.title, d.source_url, d.source_type, d.chunk_count, d.created_at,
               COUNT(c.id) AS actual_chunk_count
        FROM documents d
        LEFT JOIN knowledge_chunks c ON c.document_id = d.id
        {where}
        GROUP BY d.id
        ORDER BY d.created_at DESC
        LIMIT ${idx}
        """,
        *params,
    )
    return [_doc_row(r) for r in rows]


async def delete_document(document_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute("DELETE FROM documents WHERE id = $1::uuid", document_id)
    return result.endswith("1")


# ═══ Task Management ═══


async def submit_ingestion_task(
    kb_id: str,
    title: str,
    text: str,
    source_url: str | None,
    source_type: str = "manual",
    filename: str = "",
) -> str:
    pool = get_pool()
    task_id = str(uuid4())
    await pool.execute(
        """
        INSERT INTO tasks (id, kb_id, title, source_url, raw_text, source_type, status)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, 'queued')
        """,
        task_id, kb_id, title, source_url, text, source_type,
    )
    asyncio.create_task(_guarded_pipeline(task_id, kb_id, title, text, source_url, source_type, filename))
    return task_id


async def _guarded_pipeline(
    task_id: str, kb_id: str, title: str, text: str,
    source_url: str | None, source_type: str, filename: str,
) -> None:
    """Acquire semaphore before running pipeline so queries aren't starved."""
    async with _INGESTION_SEMAPHORE:
        await _run_pipeline(task_id, kb_id, title, text, source_url, source_type, filename)


async def get_task(task_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, kb_id, title, source_url, status, error, document_id, created_at, updated_at "
        "FROM tasks WHERE id = $1::uuid",
        task_id,
    )
    if not row:
        return None
    task = _task_row(row)
    task["progress"] = _status_to_progress(task["status"])
    return task


async def list_tasks(kb_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
    pool = get_pool()
    clauses = []
    params: list[object] = []
    idx = 1

    if kb_id:
        clauses.append(f"kb_id = ${idx}::uuid")
        params.append(kb_id)
        idx += 1
    if status:
        clauses.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    rows = await pool.fetch(
        f"""
        SELECT id, kb_id, title, source_url, status, error, document_id, created_at, updated_at
        FROM tasks {where} ORDER BY updated_at DESC LIMIT ${idx}
        """,
        *params,
    )
    data = [_task_row(r) for r in rows]
    for item in data:
        item["progress"] = _status_to_progress(item["status"])
    return data


async def retry_task(task_id: str) -> str:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, kb_id, title, source_url, raw_text, source_type, document_id FROM tasks WHERE id = $1::uuid",
        task_id,
    )
    if not row:
        raise ValueError("task not found")

    raw_text = row["raw_text"]
    title = row["title"]
    source_url = row["source_url"]
    source_type = row.get("source_type", "manual")
    kb_id = str(row["kb_id"])

    if (not raw_text or not title) and row["document_id"]:
        doc = await get_document(str(row["document_id"]))
        if doc:
            raw_text = raw_text or doc.get("raw_text")
            title = title or doc.get("title")
            source_url = source_url or doc.get("source_url")
            source_type = source_type or doc.get("source_type", "manual")

    if not raw_text or not title:
        raise ValueError("task payload unavailable for retry")

    return await submit_ingestion_task(kb_id, title, raw_text, source_url, source_type)


# ═══ Search ═══


async def search_chunks(kb_id: str, query: str, top_k: int) -> list[dict]:
    from app.services.hybrid_search import hybrid_search

    kb = await get_kb(kb_id)
    if not kb:
        return []
    query_vecs = await embed_texts(
        [query],
        model=kb["embedding_model"],
        provider=kb.get("embedding_provider") or settings.embedding_provider,
    )
    return await hybrid_search(kb_id, query, query_vecs[0], top_k=top_k)


# ═══ Graph ═══


async def get_graph(kb_id: str) -> dict:
    pool = get_pool()
    entities = await pool.fetch(
        "SELECT id, name, entity_type FROM entities WHERE kb_id = $1::uuid", kb_id
    )
    relations = await pool.fetch(
        "SELECT id, source_entity, target_entity, relation_type, weight FROM relations WHERE kb_id = $1::uuid",
        kb_id,
    )
    return {
        "nodes": [{"id": str(e["id"]), "name": e["name"], "type": e["entity_type"]} for e in entities],
        "edges": [
            {
                "id": str(r["id"]),
                "source": r["source_entity"],
                "target": r["target_entity"],
                "type": r["relation_type"],
                "weight": r["weight"],
            }
            for r in relations
        ],
    }


# ═══ Browse Query ═══


async def browse_kb(kb_id: str) -> dict:
    """Return structured overview of a knowledge base for browse-type queries."""
    pool = get_pool()
    kb = await get_kb(kb_id)
    if not kb:
        return {"kb": None, "documents": [], "stats": {}}

    docs = await list_documents(kb_id=kb_id, limit=100)
    doc_count = len(docs)
    chunk_total = await pool.fetchval(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE kb_id = $1::uuid", kb_id,
    )

    doc_summaries = []
    for doc in docs:
        first_chunk = await pool.fetchrow(
            "SELECT content FROM knowledge_chunks WHERE document_id = $1::uuid ORDER BY chunk_index LIMIT 1",
            doc["id"],
        )
        preview = ""
        if first_chunk:
            preview = first_chunk["content"][:300]
        doc_summaries.append({
            "id": doc["id"],
            "title": doc["title"],
            "chunk_count": doc["chunk_count"],
            "source_type": doc.get("source_type", ""),
            "created_at": doc["created_at"],
            "preview": preview,
        })

    return {
        "kb": {"id": kb["id"], "name": kb["name"], "description": kb.get("description", "")},
        "documents": doc_summaries,
        "stats": {
            "document_count": doc_count,
            "chunk_count": chunk_total or 0,
            "embedding_provider": kb.get("embedding_provider", ""),
            "embedding_model": kb.get("embedding_model", ""),
            "dimension": kb.get("dimension", 0),
        },
    }


# ═══ Stats ═══


async def get_stats() -> dict:
    pool = get_pool()
    kb_total = await pool.fetchval("SELECT COUNT(*) FROM knowledge_bases")
    doc_total = await pool.fetchval("SELECT COUNT(*) FROM documents")
    chunk_total = await pool.fetchval("SELECT COUNT(*) FROM knowledge_chunks")
    task_rows = await pool.fetch("SELECT status, COUNT(*) AS c FROM tasks GROUP BY status")
    return {
        "knowledge_bases": kb_total or 0,
        "documents": doc_total or 0,
        "chunks": chunk_total or 0,
        "tasks_by_status": {row["status"]: row["c"] for row in task_rows},
    }


# ═══ Pipeline ═══


async def _run_pipeline(
    task_id: str,
    kb_id: str,
    title: str,
    text: str,
    source_url: str | None,
    source_type: str = "manual",
    filename: str = "",
) -> None:
    try:
        await _update_task(task_id, "running")
        kb = await get_kb(kb_id)
        if not kb:
            raise ValueError("knowledge base not found")

        strategy = auto_detect_strategy(text, filename)
        chunk_data = split_text(text, strategy=strategy)

        if not chunk_data:
            raise ValueError("No chunks produced from input text")

        embeddings = await embed_texts(
            [c.content for c in chunk_data],
            model=kb["embedding_model"],
            provider=kb.get("embedding_provider") or settings.embedding_provider,
        )

        document_id = str(uuid4())
        pool = get_pool()

        await pool.execute(
            """
            INSERT INTO documents (id, kb_id, title, source_url, source_type, raw_text, chunk_count)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7)
            """,
            document_id, kb_id, title, source_url, source_type, text, len(chunk_data),
        )

        for idx, chunk in enumerate(chunk_data):
            vec = embeddings[idx] if idx < len(embeddings) else [0.0] * kb["dimension"]
            np_vec = np.array(vec, dtype=np.float32)
            await pool.execute(
                """
                INSERT INTO knowledge_chunks
                    (id, document_id, kb_id, chunk_index, title, source_url, content, embedding, metadata, source_type)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8::vector, $9::jsonb, $10)
                """,
                str(uuid4()), document_id, kb_id, chunk.chunk_index, title, source_url,
                chunk.content, np_vec, json.dumps(chunk.metadata, ensure_ascii=False), source_type,
            )
            if (idx + 1) % _CHUNK_INSERT_BATCH == 0:
                await asyncio.sleep(0)

        # Entity/relation extraction (heuristic, lightweight)
        try:
            entities, relations = extract_entities_and_relations(text)
            for entity in entities:
                await pool.execute(
                    "INSERT INTO entities (id, kb_id, name, entity_type, description) VALUES ($1::uuid, $2::uuid, $3, $4, $5)",
                    str(uuid4()), kb_id, entity.name, entity.entity_type, entity.description,
                )
            for relation in relations:
                await pool.execute(
                    "INSERT INTO relations (id, kb_id, source_entity, target_entity, relation_type, weight) "
                    "VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)",
                    str(uuid4()), kb_id, relation.source, relation.target, relation.relation_type, relation.weight,
                )
        except Exception:
            logger.warning("Entity extraction failed, skipping", exc_info=True)

        await _update_task(task_id, "succeeded", document_id=document_id)
        logger.info("Ingestion completed: task=%s doc=%s chunks=%d", task_id, document_id, len(chunk_data))

    except Exception as exc:
        logger.exception("Ingestion pipeline failed: task=%s", task_id)
        await _update_task(task_id, "failed", error=str(exc))


async def _update_task(task_id: str, status: str, error: str | None = None, document_id: str | None = None) -> None:
    pool = get_pool()
    if document_id:
        await pool.execute(
            "UPDATE tasks SET status = $1, error = $2, document_id = $3::uuid, updated_at = NOW() WHERE id = $4::uuid",
            status, error, document_id, task_id,
        )
    else:
        await pool.execute(
            "UPDATE tasks SET status = $1, error = $2, updated_at = NOW() WHERE id = $3::uuid",
            status, error, task_id,
        )


# ═══ Helpers ═══


def _kb_row(row) -> dict:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "embedding_provider": row["embedding_provider"],
        "embedding_model": row["embedding_model"],
        "dimension": row["dimension"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
    }


def _doc_row(row) -> dict:
    d: dict = {
        "id": str(row["id"]),
        "kb_id": str(row["kb_id"]),
        "title": row["title"],
        "source_url": row["source_url"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
    }
    if "source_type" in row.keys():
        d["source_type"] = row["source_type"]
    if "chunk_count" in row.keys():
        d["chunk_count"] = row["chunk_count"]
    if "actual_chunk_count" in row.keys():
        d["chunk_count"] = row["actual_chunk_count"]
    if "raw_text" in row.keys():
        d["raw_text"] = row["raw_text"]
    return d


def _task_row(row) -> dict:
    return {
        "id": str(row["id"]),
        "kb_id": str(row["kb_id"]),
        "title": row["title"],
        "source_url": row["source_url"],
        "status": row["status"],
        "error": row["error"],
        "document_id": str(row["document_id"]) if row["document_id"] else None,
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
    }


def _status_to_progress(status: str) -> int:
    return {"succeeded": 100, "completed": 100, "running": 60, "processing": 60, "queued": 10, "pending": 10}.get(status, 0)
