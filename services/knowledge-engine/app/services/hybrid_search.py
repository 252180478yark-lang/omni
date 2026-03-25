"""Hybrid search: pgvector similarity + PostgreSQL fulltext + HyPE, fused with RRF.

Enhancements:
- HyPE search: also matches against hypothetical question embeddings
- Context Window: enriches results with neighboring chunks
"""

from __future__ import annotations

import json
import logging

import numpy as np

from app.config import settings
from app.database import get_pool

logger = logging.getLogger(__name__)


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


async def hype_search(
    kb_id: str,
    query_embedding: list[float],
    top_k: int = 10,
) -> list[dict]:
    """Search against HyPE (hypothetical question) embeddings."""
    pool = get_pool()
    vec = np.array(query_embedding, dtype=np.float32)
    rows = await pool.fetch(
        """
        SELECT h.chunk_id,
               1 - (h.embedding <=> $1::vector) AS hype_score,
               c.id, c.document_id, c.kb_id, c.chunk_index, c.title, c.source_url,
               c.content, c.metadata, c.source_type, c.created_at
        FROM hype_embeddings h
        JOIN knowledge_chunks c ON c.id = h.chunk_id
        WHERE h.kb_id = $2::uuid
          AND h.embedding IS NOT NULL
        ORDER BY h.embedding <=> $1::vector
        LIMIT $3
        """,
        vec,
        str(kb_id),
        top_k,
    )
    result: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        cid = str(row["id"])
        if cid in seen:
            continue
        seen.add(cid)
        d = _row_to_dict(row, "hype")
        d["score"] = float(row["hype_score"])
        result.append(d)
    return result


async def hybrid_search(
    kb_id: str,
    query: str,
    query_embedding: list[float],
    top_k: int = 10,
    rrf_k: int = 60,
    include_hype: bool = True,
) -> list[dict]:
    """RRF-fused hybrid search combining vector, fulltext, and optionally HyPE."""
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

    hype_rows: list[dict] = []
    if include_hype and settings.hype_enabled:
        try:
            hype_rows = await hype_search(kb_id, query_embedding, top_k=fetch_n)
        except Exception:
            logger.debug("HyPE search failed, continuing without", exc_info=True)

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

    for rank, item in enumerate(hype_rows, start=1):
        cid = item["id"]
        if cid not in fused:
            fused[cid] = item
            fused[cid]["rrf_score"] = 0.0
        else:
            src = fused[cid]["search_source"]
            if "hype" not in src:
                fused[cid]["search_source"] = f"{src}+hype"
        fused[cid]["rrf_score"] += 1.0 / (rrf_k + rank)

    results = sorted(fused.values(), key=lambda x: x["rrf_score"], reverse=True)
    if results:
        max_rrf = results[0]["rrf_score"]
        for item in results:
            raw = item.pop("rrf_score")
            item["score"] = round(raw / max_rrf, 4) if max_rrf > 0 else 0.0
    return results[:top_k]


async def enrich_with_context_window(
    chunks: list[dict],
    window: int | None = None,
) -> list[dict]:
    """Fetch neighboring chunks for each result to provide broader context."""
    w = window if window is not None else settings.rag_context_window
    if w <= 0 or not chunks:
        return chunks

    pool = get_pool()
    enriched: list[dict] = []
    seen_ids: set[str] = set()

    for chunk in chunks:
        if chunk["id"] in seen_ids:
            continue
        seen_ids.add(chunk["id"])

        doc_id = chunk.get("document_id")
        ci = chunk.get("chunk_index")
        if doc_id is None or ci is None:
            enriched.append(chunk)
            continue

        neighbor_rows = await pool.fetch(
            """
            SELECT id, document_id, kb_id, chunk_index, title, source_url,
                   content, metadata, source_type, created_at
            FROM knowledge_chunks
            WHERE document_id = $1::uuid
              AND chunk_index BETWEEN $2 AND $3
              AND id != $4::uuid
            ORDER BY chunk_index
            """,
            doc_id, ci - w, ci + w, chunk["id"],
        )

        before_ctx = []
        after_ctx = []
        for nr in neighbor_rows:
            nid = str(nr["id"])
            if nid in seen_ids:
                continue
            if nr["chunk_index"] < ci:
                before_ctx.append(nr["content"])
            else:
                after_ctx.append(nr["content"])

        if before_ctx or after_ctx:
            expanded_content = "\n\n".join(
                before_ctx + [chunk["content"]] + after_ctx
            )
            expanded = dict(chunk)
            expanded["content"] = expanded_content
            expanded["metadata"] = {
                **chunk.get("metadata", {}),
                "context_window": w,
                "expanded_from": ci,
            }
            enriched.append(expanded)
        else:
            enriched.append(chunk)

    return enriched


def _row_to_dict(row, source: str) -> dict:
    raw_meta = row["metadata"]
    if isinstance(raw_meta, dict):
        metadata = raw_meta
    elif isinstance(raw_meta, str):
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
