from __future__ import annotations

import sqlite3

from app.services.vector_search import search_by_vector


def keyword_search(conn: sqlite3.Connection, kb_id: str, query: str, top_k: int) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT c.id, c.document_id, c.kb_id, c.chunk_index, c.title, c.source_url, c.content, c.embedding_json, c.dimension, c.created_at
        FROM chunks c
        WHERE c.kb_id = ? AND lower(c.content) LIKE ?
        ORDER BY c.chunk_index ASC
        LIMIT ?
        """,
        (kb_id, f"%{query.lower()}%", top_k),
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["score"] = 1.0
        item["source"] = "keyword"
        result.append(item)
    return result


def hybrid_search(conn: sqlite3.Connection, kb_id: str, query: str, query_embedding: list[float], top_k: int = 10) -> list[dict[str, object]]:
    vec = search_by_vector(conn, kb_id, query_embedding, top_k=top_k * 2)
    key = keyword_search(conn, kb_id, query, top_k=top_k * 2)

    # Lightweight RRF fusion: score += 1 / (k + rank)
    fused: dict[str, dict[str, object]] = {}
    k = 60
    for rank, item in enumerate(vec, start=1):
        target = fused.setdefault(item["id"], dict(item))
        target["rrf_score"] = target.get("rrf_score", 0.0) + (1.0 / (k + rank))
        target["source"] = "vector"
    for rank, item in enumerate(key, start=1):
        target = fused.setdefault(item["id"], dict(item))
        target["rrf_score"] = target.get("rrf_score", 0.0) + (1.0 / (k + rank))
        if target.get("source") == "vector":
            target["source"] = "hybrid"
        else:
            target["source"] = "keyword"

    result = sorted(fused.values(), key=lambda x: x.get("rrf_score", 0.0), reverse=True)
    return result[:top_k]
