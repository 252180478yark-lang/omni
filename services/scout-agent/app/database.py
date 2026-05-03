from __future__ import annotations

import json

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool not initialized")
    return _pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    # 让 JSONB / JSON 列直接还原成 Python list/dict，否则前端拿到字符串会炸 (.map is not a function)
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
    )


async def init_db() -> None:
    global _pool
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    _pool = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=10, init=_init_connection,
    )


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
