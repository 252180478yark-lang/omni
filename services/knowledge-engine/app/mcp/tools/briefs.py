"""W1: list_briefs（design doc §3.2 W1 行 5）。

thin wrapper over services.briefs.list_briefs（已存在）。
"""
from __future__ import annotations

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import briefs as briefs_service


@tool_with_audit(mcp, require_approval=False)
async def list_briefs(
    sku_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict:
    """列已生成的 Brief。

    Args:
        sku_id: 按 SKU 过滤
        status: 按状态过滤（active / archived 等）
        limit: 上限（默认 50，最大 200）

    Returns:
        {"ok": True, "count": N, "briefs": [{id, sku_id, title, usp, status,
            target_purpose, created_at}, ...]}
    """
    rows = await briefs_service.list_briefs(
        limit=min(limit, 200),
        offset=0,
        sku_id=sku_id,
        status=status,
    )
    # 只回 LLM 关心的薄字段；避免返 audience_profile 这种 JSON 太大撑爆 context
    slim = [
        {
            "id": str(b["id"]),
            "sku_id": b.get("sku_id"),
            "title": b.get("title"),
            "usp": b.get("usp"),
            "status": b.get("status"),
            "target_purpose": b.get("target_purpose"),
            "created_at": b.get("created_at"),
        }
        for b in rows
    ]
    return {"ok": True, "count": len(slim), "briefs": slim}
