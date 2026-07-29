import os

from fastapi import APIRouter
from app.database import get_pool

router = APIRouter()


def _baked_identity(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return None if not value or value.lower() in {"unknown", "unset", "none"} else value


@router.get("/health")
async def health():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {
        "status": "ok",
        "build_commit": _baked_identity("OMNI_BUILD_COMMIT"),
        "build_source_fingerprint": _baked_identity("OMNI_BUILD_SOURCE_FINGERPRINT"),
    }
