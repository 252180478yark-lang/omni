from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
import structlog

from app.api.router import api_router
from app.config import get_settings
from app.database import engine

settings = get_settings()


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await engine.dispose()


configure_logging()
app = FastAPI(title=settings.service_name, lifespan=lifespan)
app.include_router(api_router)
