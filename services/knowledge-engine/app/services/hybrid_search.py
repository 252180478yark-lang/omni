"""Hybrid search: pgvector similarity + PostgreSQL fulltext, fused with RRF."""

from __future__ import annotations

import numpy as np

from app.database import get_pool


async def fulltext_search(
    kb_id: str,
    query: str,
    top_k: int = 10,
) -> list[dict]:
    """Full-text search using tsvector + ts_rank."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, document_id, kb_id, chunk_index, title, source_url, content,
               metadata, source_type, created_at,
               ts_rank(tsv, plainto_tsquery('simple', $1)) AS score
        FROM knowledge_chunks
        WHERE kb_id = $2::uuid
          AND tsv @@ plainto_tsquery('simple', $1)
        ORDER BY score DESC
        LIMIT $3
        """,
        query,
        str(kb_id),
        top_k,
    )
    return [_row_to_dict(row, "fulltext") for row in rows]


async def hybrid_search(
    kb_id: str,
    query: str,
    query_embedding: list[float],
    top_k: int = 10,
    rrf_k: int = 60,
) -> list[dict]:
    """RRF-fused hybrid search combining vector similarity and fulltext."""
    pool = get_pool()
    vec = np.array(query_embedding, dtype=np.float32)
    fetch_n = top_k * 3

    vec_rows = await pool.fetch(
        """
        SELECT id, document_id, kb_id, chunk_index, title, source_url, content,
               metadata, source_type, created_at,
               1 - (embedding <=> $1::vector) AS score
        FROM knowledge_chunks
        WHERE kb_id = $2::uuid AND embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        vec,
        str(kb_id),
        fetch_n,
    )

    ft_rows = await pool.fetch(
        """
        SELECT id, document_id, kb_id, chunk_index, title, source_url, content,
               metadata, source_type, created_at,
               ts_rank(tsv, plainto_tsquery('simple', $1)) AS score
        FROM knowledge_chunks
        WHERE kb_id = $2::uuid
          AND tsv @@ plainto_tsquery('simple', $1)
        ORDER BY score DESC
        LIMIT $3
        """,
        query,
        str(kb_id),
        fetch_n,
    )

    # Reciprocal Rank Fusion
    fused: dict[str, dict] = {}

    for rank, row in enumerate(vec_rows, start=1):
        cid = str(row["id"])
        if cid not in fused:
            fused[cid] = _row_to_dict(row, "vector")
            fused[cid]["rrf_score"] = 0.0
        fused[cid]["rrf_score"] += 1.0 / (rrf_k + rank)

    for rank, row in enumerate(ft_rows, start=1):
        cid = str(row["id"])
        if cid not in fused:
            fused[cid] = _row_to_dict(row, "fulltext")
            fused[cid]["rrf_score"] = 0.0
        else:
            fused[cid]["search_source"] = "hybrid"
        fused[cid]["rrf_score"] += 1.0 / (rrf_k + rank)

    results = sorted(fused.values(), key=lambda x: x["rrf_score"], reverse=True)
    for item in results:
        item["score"] = item.pop("rrf_score")
    return results[:top_k]


def _row_to_dict(row, source: str) -> dict:
    raw_meta = row["metadata"]
    if isinstance(raw_meta, dict):
        metadata = raw_meta
    elif isinstance(raw_meta, str):
        import json
        try:
            metadata = json.loads(raw_meta)
        except (json.JSONDecodeError, TypeError):
            metadata = {}
    else:
        metadata = {}

    return {
        "id": str(row["id"]),
        "document_id": str(row["document_id"]),
        "kb_id": str(row["kb_id"]),
        "chunk_index": row["chunk_index"],
        "title": row["title"],
        "source_url": row["source_url"],
        "content": row["content"],
        "metadata": metadata,
        "source_type": row["source_type"],
        "score": float(row["score"]),
        "search_source": source,
    }
