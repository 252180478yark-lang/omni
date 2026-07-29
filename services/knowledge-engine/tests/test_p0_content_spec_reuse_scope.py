"""Live schema contract for P0 ContentSpec reuse across production orders."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from app.database import close_pool, get_pool, init_pool


MIGRATION = "092_p0_content_spec_reuse_scope.sql"
REPO_ROOT = (
    Path("/workspace")
    if Path("/workspace/migrations").is_dir()
    else Path(__file__).resolve().parents[3]
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def database_pool():
    await init_pool()
    yield
    await close_pool()


def test_content_spec_reuse_migration_scopes_the_hash_to_an_order() -> None:
    sql = (REPO_ROOT / "migrations" / MIGRATION).read_text(encoding="utf-8")

    assert "DROP CONSTRAINT IF EXISTS production_content_specs_spec_hash_key" in sql
    assert "production_content_specs_order_spec_hash_unique" in sql
    assert "UNIQUE (production_order_id, spec_hash)" in sql


@pytest.mark.asyncio
async def test_live_content_spec_hash_constraint_is_order_scoped() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        ledger = await conn.fetchrow(
            "SELECT checksum FROM public.schema_migrations WHERE filename=$1",
            MIGRATION,
        )
        constraints = await conn.fetch(
            """
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE conrelid='pipeline.production_content_specs'::regclass
              AND contype='u'
            ORDER BY conname
            """
        )
        index_definition = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname='pipeline' AND indexname='idx_production_content_specs_spec_hash'"
        )

    definitions = {str(row["conname"]): str(row["definition"]) for row in constraints}
    assert ledger is not None and ledger["checksum"]
    assert "production_content_specs_spec_hash_key" not in definitions
    assert definitions["production_content_specs_order_spec_hash_unique"] == (
        "UNIQUE (production_order_id, spec_hash)"
    )
    assert index_definition and "(spec_hash)" in index_definition
