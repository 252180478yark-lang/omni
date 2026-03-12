"""Vector similarity search using pgvector."""

from __future__ import annotations

import numpy as np

from app.database import get_pool


async def search_by_vector(
    kb_id: str,
    query_embedding: list[float],
    top_k: int = 10,
    score_threshold: float = 0.0,
) -> list[dict]:
    """Cosine similarity search via pgvector <=> operator."""
    pool = get_pool()
    vec = np.array(query_embedding, dtype=np.float32)

    rows = await pool.fetch(
        """
        SELECT id, document_id, kb_id, chunk_index, title, source_url, content,
               metadata, source_type, created_at,
               1 - (embedding <=> $1::vector) AS score
        FROM knowledge_chunks
        WHERE kb_id = $2::uuid
          AND embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        vec,
        str(kb_id),
        top_k * 2,
    )

    results: list[dict] = []
    for row in rows:
        score = float(row["score"])
        if score < score_threshold:
            continue
        results.append({
            "id": str(row["id"]),
            "document_id": str(row["document_id"]),
            "kb_id": str(row["kb_id"]),
            "chunk_index": row["chunk_index"],
            "title": row["title"],
            "source_url": row["source_url"],
            "content": row["content"],
            "metadata": dict(row["metadata"]) if row["metadata"] else {},
            "source_type": row["source_type"],
            "score": score,
            "search_source": "vector",
        })
    return results[:top_k]
