"""Graph-based retrieval for GraphRAG.

Pipeline:
1. Extract key terms from the user query
2. Fuzzy-match entities in the knowledge graph (pg_trgm similarity)
3. Traverse 1–2 hops of relations to find connected entities
4. Collect associated document_ids and fetch relevant chunks
5. Build a structured graph context string for the LLM prompt
"""

from __future__ import annotations

import logging
import re

from app.database import get_pool

logger = logging.getLogger(__name__)

_STOPWORDS_ZH = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己"
    " 这 他 她 它 们 那 里 为 什么 怎么 哪 如何 可以 什么样 怎样 多少 吗 呢 吧 啊 哦"
    " 中 用 哪些 什么 怎么样 那些 这些 还是 或者 以及 关于 通过 进行 使用 如果 但是"
    .split()
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_RE = re.compile(r"[a-zA-Z][\w-]*[a-zA-Z0-9]|[a-zA-Z]{2,}")


def _extract_query_terms(query: str) -> list[str]:
    """Extract meaningful terms from a user query for entity matching.

    For Chinese text, generates overlapping 2/3/4-gram windows from each
    continuous CJK run so that short entity names can be fuzzy-matched by
    pg_trgm.  Latin words are kept as-is.
    """
    terms: list[str] = []
    seen: set[str] = set()

    for m in _LATIN_RE.finditer(query):
        w = m.group()
        if len(w) >= 2 and w.lower() not in seen:
            seen.add(w.lower())
            terms.append(w)

    for m in _CJK_RE.finditer(query):
        run = m.group()
        filtered = "".join(ch for ch in run if ch not in _STOPWORDS_ZH)
        if len(filtered) < 2:
            continue
        for n in (4, 3, 2):
            for i in range(len(filtered) - n + 1):
                gram = filtered[i : i + n]
                if gram not in seen and gram not in _STOPWORDS_ZH:
                    seen.add(gram)
                    terms.append(gram)
        if filtered not in seen:
            seen.add(filtered)
            terms.append(filtered)

    return terms[:15]


async def graph_search(
    kb_id: str,
    query: str,
    *,
    top_entities: int = 15,
    max_hops: int = 2,
    max_relations: int = 50,
    max_chunks: int = 8,
) -> dict:
    """Retrieve graph context for a user query.

    Returns:
        {
            "entities": [{"name", "type", "description", "similarity"}],
            "relations": [{"source", "target", "type", "weight"}],
            "graph_chunks": [{"id", "content", "title", "score"}],
            "graph_context": str  # formatted text for LLM prompt
        }
    """
    pool = get_pool()
    terms = _extract_query_terms(query)
    logger.info("graph_search: query=%s terms=%s", query[:60], terms[:6])

    if not terms:
        return await _fallback_top_entities(pool, kb_id, top_entities, max_relations, max_chunks)

    # ── Step 1: Fuzzy-match entities using pg_trgm ──
    matched_entities = await _match_entities(pool, kb_id, terms, top_entities)
    if not matched_entities:
        logger.info("graph_search: no term-matched entities, using fallback top entities")
        return await _fallback_top_entities(pool, kb_id, top_entities, max_relations, max_chunks)

    entity_names = [e["name"] for e in matched_entities]

    # ── Step 2: Traverse relations (1–2 hops) ──
    relations = await _traverse_relations(pool, kb_id, entity_names, max_hops, max_relations)

    # ── Step 3: Collect related document_ids and fetch chunks ──
    all_entity_names = set(entity_names)
    for rel in relations:
        all_entity_names.add(rel["source"])
        all_entity_names.add(rel["target"])

    graph_chunks = await _fetch_entity_chunks(pool, kb_id, list(all_entity_names), max_chunks)

    # ── Step 4: Build formatted context ──
    graph_context = _format_graph_context(matched_entities, relations)

    return {
        "entities": matched_entities,
        "relations": relations,
        "graph_chunks": graph_chunks,
        "graph_context": graph_context,
    }


async def _match_entities(
    pool, kb_id: str, terms: list[str], limit: int,
) -> list[dict]:
    """Fuzzy-match entities using pg_trgm similarity + exact substring.

    Uses a low similarity threshold (0.1) and boosts ILIKE substring hits
    so that short CJK terms can still match longer entity names.
    """
    results: list[dict] = []
    seen: set[str] = set()

    for term in terms[:8]:
        rows = await pool.fetch(
            """
            SELECT name, entity_type, description,
                   GREATEST(
                       similarity(name, $1),
                       CASE WHEN name ILIKE '%' || $1 || '%' THEN 0.85 ELSE 0 END,
                       CASE WHEN $1 ILIKE '%' || name || '%' THEN 0.75 ELSE 0 END
                   ) AS sim
            FROM entities
            WHERE kb_id = $2::uuid
              AND (
                  similarity(name, $1) > 0.1
                  OR name ILIKE '%' || $1 || '%'
                  OR $1 ILIKE '%' || name || '%'
              )
            ORDER BY sim DESC
            LIMIT $3
            """,
            term, str(kb_id), limit,
        )
        for row in rows:
            name = row["name"]
            if name not in seen:
                seen.add(name)
                results.append({
                    "name": name,
                    "type": row["entity_type"],
                    "description": row["description"],
                    "similarity": float(row["sim"]),
                })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]


async def _traverse_relations(
    pool, kb_id: str, seed_names: list[str], max_hops: int, limit: int,
) -> list[dict]:
    """BFS-style relation traversal up to max_hops."""
    visited_edges: set[str] = set()
    current_names = set(seed_names)
    all_relations: list[dict] = []

    for _hop in range(max_hops):
        if not current_names:
            break

        name_list = list(current_names)
        rows = await pool.fetch(
            """
            SELECT source_entity, target_entity, relation_type, weight
            FROM relations
            WHERE kb_id = $1::uuid
              AND (source_entity = ANY($2) OR target_entity = ANY($2))
            ORDER BY weight DESC
            LIMIT $3
            """,
            str(kb_id), name_list, limit,
        )

        next_names: set[str] = set()
        for row in rows:
            edge_key = f"{row['source_entity']}|{row['target_entity']}|{row['relation_type']}"
            if edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)
            all_relations.append({
                "source": row["source_entity"],
                "target": row["target_entity"],
                "type": row["relation_type"],
                "weight": float(row["weight"]),
            })
            next_names.add(row["source_entity"])
            next_names.add(row["target_entity"])

        current_names = next_names - set(seed_names)

    return all_relations[:limit]


async def _fetch_entity_chunks(
    pool, kb_id: str, entity_names: list[str], limit: int,
) -> list[dict]:
    """Fetch chunks from documents linked to matched entities."""
    if not entity_names:
        return []

    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (c.id)
            c.id, c.content, c.title, c.document_id, c.source_url,
            1.0 AS score
        FROM entities e
        JOIN knowledge_chunks c ON c.document_id = e.document_id AND c.kb_id = e.kb_id
        WHERE e.kb_id = $1::uuid
          AND e.name = ANY($2)
          AND e.document_id IS NOT NULL
        LIMIT $3
        """,
        str(kb_id), entity_names, limit,
    )
    return [
        {
            "id": str(row["id"]),
            "content": row["content"],
            "title": row["title"],
            "source_url": row["source_url"],
            "score": float(row["score"]),
            "search_source": "graph",
        }
        for row in rows
    ]


def _format_graph_context(
    entities: list[dict], relations: list[dict],
) -> str:
    """Format graph data into a readable context string for the LLM."""
    if not entities and not relations:
        return ""

    parts: list[str] = []

    if entities:
        parts.append("相关实体：")
        for e in entities[:15]:
            desc = f" — {e['description']}" if e.get("description") else ""
            parts.append(f"  • {e['name']} [{e['type']}]{desc}")

    if relations:
        parts.append("\n实体关系：")
        for r in relations[:20]:
            parts.append(f"  • {r['source']} —[{r['type']}]→ {r['target']} (权重: {r['weight']:.1f})")

    return "\n".join(parts)


async def _fallback_top_entities(
    pool, kb_id: str, top_entities: int, max_relations: int, max_chunks: int,
) -> dict:
    """When no query terms matched, pull the most-connected entities as
    general graph context so the LLM still benefits from the knowledge graph."""
    rows = await pool.fetch(
        """
        SELECT e.name, e.entity_type, e.description,
               COUNT(r.*) AS rel_cnt
        FROM entities e
        LEFT JOIN relations r
            ON r.kb_id = e.kb_id
           AND (r.source_entity = e.name OR r.target_entity = e.name)
        WHERE e.kb_id = $1::uuid
        GROUP BY e.name, e.entity_type, e.description
        ORDER BY rel_cnt DESC
        LIMIT $2
        """,
        str(kb_id), top_entities,
    )
    if not rows:
        return _empty_result()

    entities = [
        {
            "name": r["name"],
            "type": r["entity_type"],
            "description": r["description"],
            "similarity": 0.0,
        }
        for r in rows
    ]
    entity_names = [e["name"] for e in entities]
    relations = await _traverse_relations(pool, kb_id, entity_names, 1, max_relations)
    graph_chunks = await _fetch_entity_chunks(pool, kb_id, entity_names, max_chunks)
    graph_context = _format_graph_context(entities, relations)
    return {
        "entities": entities,
        "relations": relations,
        "graph_chunks": graph_chunks,
        "graph_context": graph_context,
    }


def _empty_result() -> dict:
    return {
        "entities": [],
        "relations": [],
        "graph_chunks": [],
        "graph_context": "",
    }
