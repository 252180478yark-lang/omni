from __future__ import annotations

import json
import math
import sqlite3


def search_by_vector(conn: sqlite3.Connection, kb_id: str, query_embedding: list[float], top_k: int = 10) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT c.id, c.document_id, c.kb_id, c.chunk_index, c.title, c.source_url, c.content, c.embedding_json, c.dimension, c.created_at
        FROM chunks c
        WHERE c.kb_id = ?
        """,
        (kb_id,),
    ).fetchall()
    scored: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        embedding = json.loads(item["embedding_json"])
        similarity = cosine_similarity(query_embedding, embedding)
        item["score"] = similarity
        item["source"] = "vector"
        item["embedding"] = embedding
        scored.append(item)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2:
        return 0.0
    dim = min(len(v1), len(v2))
    dot = sum(v1[i] * v2[i] for i in range(dim))
    norm1 = math.sqrt(sum(v1[i] * v1[i] for i in range(dim)))
    norm2 = math.sqrt(sum(v2[i] * v2[i] for i in range(dim)))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)
