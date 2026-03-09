import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.config import settings
from app.services.chunking import split_text
from app.services.embedding_client import embed_texts
from app.services.graph_rag import extract_entities_and_relations
from app.services.hybrid_search import hybrid_search

_LOCK = Lock()


def _connect() -> sqlite3.Connection:
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    title TEXT,
                    source_url TEXT,
                    raw_text TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    document_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_url TEXT,
                    raw_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    kb_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    source_url TEXT,
                    content TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    description TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS relations (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    source_entity TEXT NOT NULL,
                    target_entity TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    weight REAL NOT NULL
                )
                """
            )
            _ensure_column(conn, "tasks", "title", "TEXT")
            _ensure_column(conn, "tasks", "source_url", "TEXT")
            _ensure_column(conn, "tasks", "raw_text", "TEXT")
            conn.commit()
        finally:
            conn.close()


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    names = {row["name"] for row in cols}
    if column_name not in names:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def create_kb(name: str, description: str, embedding_model: str, dimension: int) -> dict:
    kb_id = str(uuid4())
    created_at = datetime.now(UTC).isoformat()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO knowledge_bases(id, name, description, embedding_model, dimension, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (kb_id, name, description, embedding_model, dimension, created_at),
            )
            conn.commit()
        finally:
            conn.close()
    return {"id": kb_id, "name": name, "description": description, "embedding_model": embedding_model, "dimension": dimension, "created_at": created_at}


def list_kbs() -> list[dict]:
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute("SELECT id, name, description, embedding_model, dimension, created_at FROM knowledge_bases ORDER BY created_at DESC").fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


def get_kb(kb_id: str) -> dict | None:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, name, description, embedding_model, dimension, created_at FROM knowledge_bases WHERE id = ?",
                (kb_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def submit_ingestion_task(kb_id: str, title: str, text: str, source_url: str | None) -> str:
    task_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("INSERT INTO tasks(id, kb_id, status, error, document_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, kb_id, "queued", None, None, now, now))
            conn.execute(
                "UPDATE tasks SET title = ?, source_url = ?, raw_text = ? WHERE id = ?",
                (title, source_url, text, task_id),
            )
            conn.commit()
        finally:
            conn.close()
    asyncio.create_task(_run_pipeline(task_id, kb_id, title, text, source_url))
    return task_id


def get_task(task_id: str) -> dict | None:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT id, kb_id, title, source_url, status, error, document_id, created_at, updated_at
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
            if not row:
                return None
            task = dict(row)
            task["progress"] = _status_to_progress(task["status"])
            return task
        finally:
            conn.close()


def list_tasks(kb_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
    with _LOCK:
        conn = _connect()
        try:
            clauses: list[str] = []
            params: list[object] = []
            if kb_id:
                clauses.append("kb_id = ?")
                params.append(kb_id)
            if status:
                clauses.append("status = ?")
                params.append(status)
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT id, kb_id, title, source_url, status, error, document_id, created_at, updated_at
                FROM tasks
                {where_sql}
                ORDER BY datetime(updated_at) DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            data = [dict(row) for row in rows]
            for item in data:
                item["progress"] = _status_to_progress(item["status"])
            return data
        finally:
            conn.close()


def get_document(document_id: str) -> dict | None:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, kb_id, title, source_url, raw_text, created_at FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


async def search_chunks(kb_id: str, query: str, top_k: int) -> list[dict]:
    kb = get_kb(kb_id)
    if not kb:
        return []
    query_vecs = await embed_texts([query], model=kb["embedding_model"])
    with _LOCK:
        conn = _connect()
        try:
            ranked = hybrid_search(conn, kb_id, query, query_vecs[0], top_k=top_k)
            for item in ranked:
                if "embedding_json" in item:
                    item.pop("embedding_json")
            return ranked
        finally:
            conn.close()


def get_graph(kb_id: str) -> dict:
    with _LOCK:
        conn = _connect()
        try:
            entities = [dict(row) for row in conn.execute("SELECT id, name, entity_type FROM entities WHERE kb_id = ?", (kb_id,)).fetchall()]
            relations = [
                {
                    "id": row["id"],
                    "source": row["source_entity"],
                    "target": row["target_entity"],
                    "type": row["relation_type"],
                    "weight": row["weight"],
                }
                for row in conn.execute(
                    "SELECT id, source_entity, target_entity, relation_type, weight FROM relations WHERE kb_id = ?",
                    (kb_id,),
                ).fetchall()
            ]
            return {"nodes": entities, "edges": relations}
        finally:
            conn.close()


async def _run_pipeline(task_id: str, kb_id: str, title: str, text: str, source_url: str | None) -> None:
    try:
        _update_task(task_id, "running")
        kb = get_kb(kb_id)
        if not kb:
            raise ValueError("knowledge base not found")

        chunk_data = split_text(text, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
        embeddings = await embed_texts([c.content for c in chunk_data], model=kb["embedding_model"])
        now = datetime.now(UTC).isoformat()
        document_id = str(uuid4())
        entities, relations = extract_entities_and_relations(text)

        with _LOCK:
            conn = _connect()
            try:
                conn.execute(
                    "INSERT INTO documents(id, kb_id, title, source_url, raw_text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (document_id, kb_id, title, source_url, text, now),
                )
                for idx, chunk in enumerate(chunk_data):
                    vector = embeddings[idx] if idx < len(embeddings) else [0.0] * kb["dimension"]
                    conn.execute(
                        """
                        INSERT INTO chunks(id, document_id, kb_id, chunk_index, title, source_url, content, embedding_json, dimension, metadata_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            document_id,
                            kb_id,
                            chunk.chunk_index,
                            title,
                            source_url,
                            chunk.content,
                            json.dumps(vector, ensure_ascii=False),
                            kb["dimension"],
                            json.dumps(chunk.metadata, ensure_ascii=False),
                            now,
                        ),
                    )
                for entity in entities:
                    conn.execute(
                        "INSERT INTO entities(id, kb_id, name, entity_type, description) VALUES (?, ?, ?, ?, ?)",
                        (str(uuid4()), kb_id, entity.name, entity.entity_type, entity.description),
                    )
                for relation in relations:
                    conn.execute(
                        "INSERT INTO relations(id, kb_id, source_entity, target_entity, relation_type, weight) VALUES (?, ?, ?, ?, ?, ?)",
                        (str(uuid4()), kb_id, relation.source, relation.target, relation.relation_type, relation.weight),
                    )
                conn.commit()
            finally:
                conn.close()
        _update_task(task_id, "succeeded", document_id=document_id)
    except Exception as exc:  # pragma: no cover
        _update_task(task_id, "failed", str(exc))


def _update_task(task_id: str, status: str, error: str | None = None, document_id: str | None = None) -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE tasks SET status = ?, error = ?, document_id = COALESCE(?, document_id), updated_at = ? WHERE id = ?",
                (status, error, document_id, datetime.now(UTC).isoformat(), task_id),
            )
            conn.commit()
        finally:
            conn.close()


def retry_task(task_id: str) -> str:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, kb_id, title, source_url, raw_text, document_id FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                raise ValueError("task not found")
            payload = dict(row)
        finally:
            conn.close()

    title = payload.get("title")
    source_url = payload.get("source_url")
    raw_text = payload.get("raw_text")
    kb_id = payload["kb_id"]
    document_id = payload.get("document_id")

    if (not raw_text or not title) and document_id:
        doc = get_document(document_id)
        if doc:
            raw_text = raw_text or doc.get("raw_text")
            title = title or doc.get("title")
            source_url = source_url or doc.get("source_url")

    if not raw_text or not title:
        raise ValueError("task payload unavailable for retry")

    return submit_ingestion_task(kb_id, title, raw_text, source_url)


def get_stats() -> dict:
    with _LOCK:
        conn = _connect()
        try:
            kb_total = conn.execute("SELECT COUNT(*) AS c FROM knowledge_bases").fetchone()["c"]
            doc_total = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
            task_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS c
                FROM tasks
                GROUP BY status
                """
            ).fetchall()
            tasks_by_status = {row["status"]: row["c"] for row in task_rows}
            return {
                "knowledge_bases": kb_total,
                "documents": doc_total,
                "tasks_by_status": tasks_by_status,
            }
        finally:
            conn.close()


def _status_to_progress(status: str) -> int:
    if status in {"succeeded", "completed"}:
        return 100
    if status in {"running", "processing"}:
        return 60
    if status in {"queued", "pending"}:
        return 10
    if status == "failed":
        return 0
    return 0
