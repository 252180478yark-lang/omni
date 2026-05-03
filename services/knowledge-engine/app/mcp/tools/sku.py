"""W1: list_skus, get_sku（design doc §3.2 W1 行 1-2）。

直接读 mvp_sku；get_sku 额外关联 content_studio.briefs 拉最近 3 条 brief 摘要。
"""
from __future__ import annotations

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp


@tool_with_audit(mcp, require_approval=False)
async def list_skus(status: str | None = None) -> dict:
    """列出 SKU 主数据。

    Args:
        status: 过滤状态（active / archived / draft 等），None=全部

    Returns:
        {"ok": True, "count": N, "skus": [{id, name, category, status,
            growth_class, in_focus_pool, total_stock, available_stock}, ...]}
    """
    pool = get_pool()
    if status:
        rows = await pool.fetch(
            "SELECT id, name, category, status, growth_class, in_focus_pool,"
            "       total_stock, available_stock"
            "  FROM mvp_sku WHERE status=$1 ORDER BY created_at DESC",
            status,
        )
    else:
        rows = await pool.fetch(
            "SELECT id, name, category, status, growth_class, in_focus_pool,"
            "       total_stock, available_stock"
            "  FROM mvp_sku ORDER BY created_at DESC"
        )
    skus = [dict(r) for r in rows]
    return {"ok": True, "count": len(skus), "skus": skus}


@tool_with_audit(mcp, require_approval=False)
async def get_sku(sku_id: str) -> dict:
    """单 SKU 详情 + 最近 3 条 brief。

    Args:
        sku_id: mvp_sku.id (VARCHAR(64))

    Returns:
        成功 {"ok": True, "sku": {...全字段}, "recent_briefs": [...]}
        失败 {"ok": False, "error": "sku_not_found", "hint": "..."}
    """
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM mvp_sku WHERE id=$1",
        sku_id,
    )
    if row is None:
        return {
            "ok": False,
            "error": "sku_not_found",
            "hint": f"SKU id '{sku_id}' 不存在；调 list_skus 看可用 ID 列表",
        }

    briefs = await pool.fetch(
        """
        SELECT id, title, status, target_purpose, created_at
          FROM content_studio.briefs
         WHERE sku_id=$1
         ORDER BY created_at DESC LIMIT 3
        """,
        sku_id,
    )
    return {
        "ok": True,
        "sku": dict(row),
        "recent_briefs": [dict(b) for b in briefs],
    }
