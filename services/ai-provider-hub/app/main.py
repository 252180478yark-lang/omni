import logging
import os

from fastapi import FastAPI

from app.config import settings
from app.routers.ai import router as ai_router
from app.routers.v1 import router as v1_router
from app.runtime import bootstrap_providers

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title=settings.service_name)
app.include_router(v1_router)
app.include_router(ai_router)


def _baked_identity(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return None if not value or value.lower() in {"unknown", "unset", "none"} else value


@app.on_event("startup")
async def startup() -> None:
    bootstrap_providers()


@app.get("/health")
async def health() -> dict[str, str | None]:
    return {
        "status": "healthy",
        "service": settings.service_name,
        "build_commit": _baked_identity("OMNI_BUILD_COMMIT"),
        "build_source_fingerprint": _baked_identity("OMNI_BUILD_SOURCE_FINGERPRINT"),
    }
