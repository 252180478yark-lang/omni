import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import close_pool, init_pool
from app.routers.knowledge import router as knowledge_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s — connecting to PostgreSQL...", settings.service_name)
    await init_pool()
    logger.info("PostgreSQL connection pool ready")
    yield
    logger.info("Shutting down — closing database pool...")
    await close_pool()


app = FastAPI(title=settings.service_name, lifespan=lifespan)
app.include_router(knowledge_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": settings.service_name}
