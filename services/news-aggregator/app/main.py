from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
import httpx
import structlog

from app.api.router import api_router
from app.config import get_settings
from app.database import engine, SessionLocal

settings = get_settings()

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


async def _auto_retry_kb_pushes() -> None:
    """On startup, retry archived articles that never made it to knowledge-engine."""
    await asyncio.sleep(10)
    from sqlalchemy import select, func
    from app.models.article import Article
    from app.services.archive_service import ArchiveService

    try:
        async with SessionLocal() as db:
            count = await db.scalar(
                select(func.count()).select_from(Article).where(
                    Article.status == "archived", Article.kb_doc_id.is_(None),
                )
            )
            if not count:
                return
            logger.info("Auto-retrying %d archived articles with pending KB push...", count)

            rows = (await db.scalars(
                select(Article).where(
                    Article.status == "archived", Article.kb_doc_id.is_(None),
                ).limit(50)
            )).all()

            async with httpx.AsyncClient(base_url=settings.sp4_base_url, timeout=30.0) as sp4:
                svc = ArchiveService(db=db, sp4_client=sp4, settings=settings)
                ids = [a.id for a in rows]
                result = await svc.retry_kb_push(ids)
                logger.info(
                    "Auto KB push retry done: retried=%d success=%d failed=%d",
                    result.retried, result.success, len(result.failed_ids),
                )
    except Exception as exc:
        logger.warning("Auto KB push retry skipped (tables may not exist yet): %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    asyncio.create_task(_auto_retry_kb_pushes())
    yield
    await engine.dispose()


configure_logging()
app = FastAPI(title=settings.service_name, lifespan=lifespan)
app.include_router(api_router)
