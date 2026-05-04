"""T1：启动期孤儿清理测试。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from app.database import get_pool, init_pool, close_pool
from app.mcp.orphan import mark_orphans


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    # 清理本测试新增的所有 _smoke_orphan_ 行（test 内已 DELETE，但失败时兜底）
    pool = get_pool()
    await pool.execute("DELETE FROM mcp.tool_calls WHERE tool_name LIKE '_smoke_orphan_%'")
    await close_pool()


@pytest.mark.asyncio
async def test_smoke_mark_orphans_marks_old_pending():
    """超过 threshold 的 pending 会被改成 orphaned。"""
    pool = get_pool()
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    old_time = datetime.now(timezone.utc) - timedelta(minutes=10)

    await pool.execute(
        "INSERT INTO mcp.tool_calls (id, tool_name, args, status, require_approval, created_at) "
        "VALUES ($1, '_smoke_orphan_old', '{}'::jsonb, 'pending', FALSE, $2), "
        "       ($3, '_smoke_orphan_new', '{}'::jsonb, 'pending', FALSE, NOW())",
        old_id, old_time, new_id,
    )

    n = await mark_orphans(threshold_minutes=5)
    assert n >= 1

    rows = await pool.fetch(
        "SELECT id, status FROM mcp.tool_calls WHERE id = ANY($1)", [old_id, new_id]
    )
    by_id = {r["id"]: r["status"] for r in rows}
    assert by_id[old_id] == "orphaned"
    assert by_id[new_id] == "pending"

    await pool.execute(
        "DELETE FROM mcp.tool_calls WHERE tool_name LIKE '_smoke_orphan_%'"
    )
