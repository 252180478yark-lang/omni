"""W2 T1：启动期孤儿清理。

mcp.tool_calls 中长时间停在 status='pending' 的记录是被 cancel 杀掉
（容器重启 / Ctrl-C / asyncio.CancelledError）的孤儿。
启动期把超过 threshold 的标 'orphaned'，便于审计 + 不污染 monitor。
"""
from __future__ import annotations

import logging

from app.database import get_pool

logger = logging.getLogger(__name__)


async def mark_orphans(threshold_minutes: int = 5) -> int:
    """把 pending 超 threshold 分钟的记录改成 orphaned。返回受影响行数。"""
    pool = get_pool()
    rec = await pool.fetchrow(
        f"""
        UPDATE mcp.tool_calls
        SET status='orphaned', completed_at=NOW(),
            error=COALESCE(error, '') || '[startup orphan cleanup]'
        WHERE status='pending'
          AND created_at < NOW() - INTERVAL '{int(threshold_minutes)} minutes'
        RETURNING id
        """
    )
    n = 0
    if rec:
        # asyncpg 没有 rowcount on UPDATE...RETURNING；走 fetch 数行
        rows = await pool.fetch(
            f"""
            SELECT id FROM mcp.tool_calls
            WHERE status='orphaned' AND completed_at >= NOW() - INTERVAL '1 minute'
            """
        )
        n = len(rows)
    if n:
        logger.warning("启动孤儿清理：%d 条 pending → orphaned (>%d min)", n, threshold_minutes)
    return n
