from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.exceptions import register_exception_handlers
from app.middleware import RequestLoggingMiddleware, configure_cors
from app.models import Base
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title=settings.service_name, lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
configure_cors(app)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(auth_router)
