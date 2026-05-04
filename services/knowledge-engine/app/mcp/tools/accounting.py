"""W2 T4 + T5：accounting tools。

- query_costs：纯 DB 查 accounting.cost_items（migration 015）
- compute_margin：DB 查成本 + Python 算账（确定性）+ LLM 写解读（T5 加）
"""
from __future__ import annotations

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.mcp.utils import decimal_to_jsonable


@tool_with_audit(mcp, require_approval=False)
async def query_costs(sku_id: str) -> dict:
    """查 SKU 的有效成本项（含共享成本如物流）。纯 DB 查询，无 LLM 调用。

    Args:
        sku_id: SKU id

    Returns:
        {"ok": True, "result": {"cost_items": [{id, sku_id, category, item_name,
            unit_cost, currency, unit, quantity_per_unit, vendor, valid_from,
            valid_to, notes}, ...]}}

        category 取值：product | logistics | partner_quote
        sku_id 为 None 的行表示共享成本（如全 SKU 共用的物流费）
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, sku_id, category, item_name, unit_cost, currency, unit,
               quantity_per_unit, vendor, valid_from, valid_to, notes
        FROM accounting.cost_items
        WHERE (sku_id = $1 OR sku_id IS NULL)
          AND is_active = TRUE
          AND valid_from <= CURRENT_DATE
          AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
        ORDER BY (sku_id IS NULL), category, valid_from DESC
        """,
        sku_id,
    )
    items = [decimal_to_jsonable(dict(r)) for r in rows]
    # UUID / date 也 str 化
    for i in items:
        if i.get("id") is not None:
            i["id"] = str(i["id"])
        if i.get("valid_from") is not None:
            i["valid_from"] = str(i["valid_from"])
        if i.get("valid_to") is not None:
            i["valid_to"] = str(i["valid_to"])
    return {"ok": True, "result": {"cost_items": items}}
