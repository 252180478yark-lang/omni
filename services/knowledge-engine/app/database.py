"""PostgreSQL async connection pool with pgvector support."""

from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector

from app.config import settings

_pool: asyncpg.Pool | None = None


def _normalize_dsn(url: str) -> str:
    """Convert SQLAlchemy-style DSN to asyncpg-compatible format."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool

    dsn = _normalize_dsn(settings.database_url)
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        init=_init_connection,
        server_settings={"search_path": "knowledge,public"},
    )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    return _pool
