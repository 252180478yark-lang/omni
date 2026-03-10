from collections.abc import AsyncGenerator

import redis.asyncio as redis
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db_session
from app.services.archive_service import ArchiveService
from app.services.fetch_service import FetchService
from app.services.review_service import ReviewService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


async def get_redis(settings: Settings = Depends(get_settings)) -> AsyncGenerator[redis.Redis, None]:
    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def get_sp3_client(settings: Settings = Depends(get_settings)) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(base_url=settings.sp3_base_url, timeout=30.0) as client:
        yield client


async def get_sp4_client(settings: Settings = Depends(get_settings)) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(base_url=settings.sp4_base_url, timeout=30.0) as client:
        yield client


def get_fetch_service(
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    sp3_client: AsyncClient = Depends(get_sp3_client),
) -> FetchService:
    return FetchService(db=db, redis_client=redis_client, settings=settings, sp3_client=sp3_client)


def get_archive_service(
    db: AsyncSession = Depends(get_db),
    sp4_client: AsyncClient = Depends(get_sp4_client),
    settings: Settings = Depends(get_settings),
) -> ArchiveService:
    return ArchiveService(db=db, sp4_client=sp4_client, settings=settings)


def get_review_service(
    db: AsyncSession = Depends(get_db),
    archive_service: ArchiveService = Depends(get_archive_service),
) -> ReviewService:
    return ReviewService(db=db, archive_service=archive_service)
