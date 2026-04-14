import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.config import settings
from app.database import close_pool, init_pool
from app.routers.knowledge import router as knowledge_router
from app.routers.harvester import router as harvester_router
from app.routers.content_studio import router as content_studio_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s — connecting to PostgreSQL...", settings.service_name)
    await init_pool()
    logger.info("PostgreSQL connection pool ready")

    # Migrate tsv column from GENERATED to regular for Chinese search support
    from app.database import get_pool
    try:
        await _migrate_tsv_column(get_pool())
    except Exception:
        logger.warning("tsv column migration skipped", exc_info=True)

    from app.services.ingestion import recover_stuck_tasks
    try:
        result = await recover_stuck_tasks()
        if result["recovered"] > 0:
            logger.info("Recovered %d stuck tasks from previous run", result["recovered"])
    except Exception:
        logger.warning("Task recovery failed, continuing startup", exc_info=True)

    yield
    logger.info("Shutting down — closing database pool...")
    await close_pool()


app = FastAPI(title=settings.service_name, lifespan=lifespan)
app.include_router(knowledge_router)
app.include_router(harvester_router)
app.include_router(content_studio_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": settings.service_name}


# ═══ One-time migration: tsv GENERATED → regular column ═══


async def _migrate_tsv_column(pool) -> None:
    """Convert tsv from GENERATED ALWAYS to a regular column.

    The old GENERATED column used ``to_tsvector('simple', ...)`` which cannot
    segment Chinese text.  The new approach populates tsv from application code
    using jieba word segmentation.

    For existing databases the column is dropped and re-created; a background
    backfill rewrites the tsvector for every chunk that has ``tsv IS NULL``.
    """
    is_generated = await pool.fetchval(
        """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = 'knowledge'
          AND table_name  = 'knowledge_chunks'
          AND column_name = 'tsv'
          AND is_generated = 'ALWAYS'
        """
    )
    if not is_generated:
        # Already migrated or fresh deployment — check for NULL rows to backfill
        null_count = await pool.fetchval(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE tsv IS NULL"
        )
        if null_count and null_count > 0:
            logger.info("Found %d chunks with NULL tsv, scheduling backfill...", null_count)
            asyncio.create_task(_backfill_tsv(pool))
        return

    logger.warning(
        "Migrating tsv column from GENERATED to regular for Chinese search support..."
    )
    await pool.execute("ALTER TABLE knowledge_chunks DROP COLUMN tsv")
    await pool.execute("ALTER TABLE knowledge_chunks ADD COLUMN tsv tsvector")
    await pool.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_tsv "
        "ON knowledge_chunks USING gin (tsv)"
    )
    logger.info("tsv column migrated — scheduling background backfill...")
    asyncio.create_task(_backfill_tsv(pool))


async def _backfill_tsv(pool) -> None:
    """Backfill tsv column with jieba-segmented content in batches."""
    from app.services.chinese_seg import segment_for_search

    batch_size = 200
    total = 0
    while True:
        rows = await pool.fetch(
            "SELECT id, content FROM knowledge_chunks "
            "WHERE tsv IS NULL ORDER BY id LIMIT $1",
            batch_size,
        )
        if not rows:
            break
        for row in rows:
            segmented = segment_for_search(row["content"])
            await pool.execute(
                "UPDATE knowledge_chunks "
                "SET tsv = to_tsvector('simple', $1) WHERE id = $2",
                segmented,
                row["id"],
            )
        total += len(rows)
        if total % 1000 == 0:
            logger.info("tsv backfill progress: %d chunks", total)
        await asyncio.sleep(0)
    if total > 0:
        logger.info("tsv backfill complete: %d chunks updated", total)
