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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s — connecting to PostgreSQL...", settings.service_name)
    await init_pool()
    logger.info("PostgreSQL connection pool ready")

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": settings.service_name}
