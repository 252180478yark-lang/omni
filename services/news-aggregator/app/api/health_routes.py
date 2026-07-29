import os

from fastapi import APIRouter

router = APIRouter(tags=["health"])


def _baked_identity(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return None if not value or value.lower() in {"unknown", "unset", "none"} else value


@router.get("/health")
async def health() -> dict[str, str | None]:
    return {
        "status": "ok",
        "build_commit": _baked_identity("OMNI_BUILD_COMMIT"),
        "build_source_fingerprint": _baked_identity("OMNI_BUILD_SOURCE_FINGERPRINT"),
    }
