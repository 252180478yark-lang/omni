"""Backfill graph entities/relations for existing documents.

Run inside the knowledge-engine container:
    docker exec omni-knowledge-engine python -m scripts.backfill_graph

Or directly (with correct env vars set):
    python -m scripts.backfill_graph
"""

from __future__ import annotations

import asyncio
import logging
import sys
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    from app.database import close_pool, init_pool
    from app.services.graph_rag import extract_entities_and_relations_llm

    pool = await init_pool()

    docs = await pool.fetch(
        """
        SELECT d.id, d.kb_id, d.title,
               (SELECT COUNT(*) FROM entities e WHERE e.document_id = d.id) AS entity_count
        FROM documents d
        ORDER BY d.created_at
        """
    )

    need_backfill = [d for d in docs if d["entity_count"] == 0]
    logger.info(
        "Total documents: %d, need graph backfill: %d", len(docs), len(need_backfill),
    )

    if not need_backfill:
        logger.info("All documents already have graph data. Nothing to do.")
        await close_pool()
        return

    for idx, doc in enumerate(need_backfill, 1):
        doc_id = str(doc["id"])
        kb_id = str(doc["kb_id"])
        title = doc["title"]
        logger.info("[%d/%d] Processing: %s (doc=%s)", idx, len(need_backfill), title, doc_id)

        chunks = await pool.fetch(
            "SELECT chunk_index, content FROM knowledge_chunks "
            "WHERE document_id = $1::uuid ORDER BY chunk_index",
            doc_id,
        )
        if not chunks:
            logger.warning("  No chunks found, skipping")
            continue

        total_e, total_r = 0, 0
        for chunk in chunks:
            try:
                entities, relations = await extract_entities_and_relations_llm(
                    chunk["content"], model="gemini-3.1-flash-lite-preview",
                )
            except Exception:
                logger.debug("  Chunk %d extraction failed", chunk["chunk_index"], exc_info=True)
                continue

            for entity in entities:
                await pool.execute(
                    """
                    INSERT INTO entities (id, kb_id, document_id, name, entity_type, description)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6)
                    ON CONFLICT (kb_id, name) DO UPDATE
                        SET description = CASE
                            WHEN LENGTH(EXCLUDED.description) > LENGTH(entities.description)
                            THEN EXCLUDED.description
                            ELSE entities.description
                        END
                    """,
                    str(uuid4()), kb_id, doc_id,
                    entity.name, entity.entity_type, entity.description,
                )
                total_e += 1

            for rel in relations:
                await pool.execute(
                    """
                    INSERT INTO relations (id, kb_id, document_id, source_entity, target_entity, relation_type, weight)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7)
                    ON CONFLICT (kb_id, source_entity, target_entity, relation_type) DO UPDATE
                        SET weight = GREATEST(relations.weight, EXCLUDED.weight)
                    """,
                    str(uuid4()), kb_id, doc_id,
                    rel.source, rel.target, rel.relation_type, rel.weight,
                )
                total_r += 1

            await asyncio.sleep(0.1)

        logger.info("  Done: %d entities, %d relations extracted", total_e, total_r)

    final_e = await pool.fetchval("SELECT COUNT(*) FROM entities")
    final_r = await pool.fetchval("SELECT COUNT(*) FROM relations")
    logger.info("Backfill complete. Total entities: %d, relations: %d", final_e, final_r)

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
