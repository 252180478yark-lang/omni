"""Test graph_search entity matching for Chinese queries."""
import asyncio
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://omni_user:changeme_in_production@omni-postgres:5432/omni_vibe_db",
)

from app.database import init_pool, get_pool
from app.services.graph_search import graph_search, _extract_query_terms

async def main():
    await init_pool()
    pool = get_pool()

    # Show entity stats per kb
    rows = await pool.fetch(
        "SELECT kb_id, COUNT(*) as cnt FROM entities GROUP BY kb_id"
    )
    for r in rows:
        print(f"KB {r['kb_id']}: {r['cnt']} entities")

    # Show some entity names
    rows = await pool.fetch(
        "SELECT DISTINCT name, entity_type FROM entities LIMIT 30"
    )
    print("\n=== Sample entities ===")
    for r in rows:
        print(f"  {r['name']} [{r['entity_type']}]")

    # Test term extraction
    queries = [
        "直播中主播用了哪些互动技巧",
        "油焖春笋怎么做",
        "有机酱油的品质特点",
    ]
    for q in queries:
        terms = _extract_query_terms(q)
        print(f"\nQuery: {q}")
        print(f"  Terms: {terms}")

    # Test graph_search against each KB
    for q in queries:
        print(f"\n=== graph_search: {q} ===")
        for r in await pool.fetch("SELECT DISTINCT kb_id FROM entities"):
            kb = str(r['kb_id'])
            result = await graph_search(kb, q)
            ents = result.get('entities', [])
            rels = result.get('relations', [])
            ctx = result.get('graph_context', '')
            print(f"  KB {kb[:8]}: {len(ents)} entities, {len(rels)} relations, ctx_len={len(ctx)}")
            if ents:
                for e in ents[:3]:
                    print(f"    -> {e['name']} [{e['type']}] sim={e['similarity']:.3f}")

    # Direct similarity test
    print("\n=== Direct SQL similarity test ===")
    test_terms = ["油焖", "春笋", "主播", "直播", "互动", "酱油"]
    for t in test_terms:
        rows = await pool.fetch(
            """
            SELECT name, entity_type,
                   similarity(name, $1) as sim,
                   (name ILIKE '%' || $1 || '%') as ilike_match
            FROM entities
            WHERE similarity(name, $1) > 0.1 OR name ILIKE '%' || $1 || '%'
            ORDER BY sim DESC
            LIMIT 5
            """,
            t,
        )
        print(f"\n  Term '{t}': {len(rows)} matches")
        for r in rows:
            print(f"    {r['name']} sim={r['sim']:.3f} ilike={r['ilike_match']}")


asyncio.run(main())
