import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db_session
from app.utils.security import create_access_token, decode_token

router = APIRouter(tags=["health"])


def _baked_identity(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return None if not value or value.lower() in {"unknown", "unset", "none"} else value


@router.get("/health")
async def health() -> dict[str, str | None]:
    return {
        "status": "healthy",
        "service": settings.service_name,
        "build_commit": _baked_identity("OMNI_BUILD_COMMIT"),
        "build_source_fingerprint": _baked_identity("OMNI_BUILD_SOURCE_FINGERPRINT"),
    }


@router.get("/health/readiness")
async def readiness(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str | bool | None]:
    readable = (await session.execute(text("SELECT 1"))).scalar_one() == 1
    token = create_access_token("health-probe", {"role": "admin"})
    claims = decode_token(token)
    authenticated = claims.get("sub") == "health-probe" and claims.get("type") == "access"
    return {
        "status": "healthy" if readable and authenticated else "unavailable",
        "readable": readable,
        "authenticated": authenticated,
        "build_commit": _baked_identity("OMNI_BUILD_COMMIT"),
        "build_source_fingerprint": _baked_identity("OMNI_BUILD_SOURCE_FINGERPRINT"),
    }
