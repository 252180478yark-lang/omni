from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.exceptions import register_exception_handlers
from app.middleware import RequestLoggingMiddleware, configure_cors
from app.routers import auth_router, health_router


def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    # Fail before serving if the allocator-owned signing key or DB is absent.
    # Schema DDL belongs exclusively to the canonical migration runner.
    _ = settings.jwt_signing_key
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    await engine.dispose()


app = FastAPI(title=settings.service_name, lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
configure_cors(app)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(auth_router)
