from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import close_db, init_db
from app.routers import analytics, audiences, campaigns, groups, materials, products, review

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(title="ad-review-service", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router)
app.include_router(campaigns.router)
app.include_router(audiences.router)
app.include_router(groups.router)
app.include_router(materials.router)
app.include_router(review.router)
app.include_router(analytics.router)


def _baked_identity(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return None if not value or value.lower() in {"unknown", "unset", "none"} else value


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "build_commit": _baked_identity("OMNI_BUILD_COMMIT"),
        "build_source_fingerprint": _baked_identity("OMNI_BUILD_SOURCE_FINGERPRINT"),
    }
