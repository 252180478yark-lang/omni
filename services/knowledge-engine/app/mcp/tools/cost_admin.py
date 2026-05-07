"""W3a T8：cost_items 写入 tools（require_approval=True）。

W2 落地的 query_costs / compute_margin 是只读；W3a 加这两个 T 类 tool 让老板
用对话录入成本（不再依赖前端表单/SQL 直插）：

- record_cost：插一行 accounting.cost_items
- disable_cost_item：软删（is_active=FALSE）

两个都走 Human Gate（CLI 批），因为是不可逆 / 影响利润计算的动作。
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp


_VALID_CATEGORIES = {"product", "logistics", "partner_quote"}
_VALID_VISIBILITIES = {"public", "real", "shared"}


def _record_cost_summary(args: dict) -> str:
    """Gate 卡片摘要：录入 SKU-X 的 product 类成本「瓶身」¥0.5/件 × 24 件 [public]"""
    parts = [
        f"录入 {args.get('category', '?')} 类成本「{args.get('item_name', '?')}」",
        f"¥{args.get('unit_cost', '?')}/{args.get('unit', '件')}",
    ]
    if args.get("sku_id"):
        parts.insert(0, f"SKU={args['sku_id']}")
    if args.get("vendor"):
        parts.append(f"供应商={args['vendor']}")
    vis = args.get("visibility", "public")
    if vis != "public":
        parts.append(f"visibility={vis}")
    return "；".join(parts)


def _disable_cost_summary(args: dict) -> str:
    return f"停用 cost_item {args.get('cost_item_id', '?')[:8]}（{args.get('reason', '无 reason')}）"


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_record_cost_summary,
    timeout_seconds=3600,
)
async def record_cost(
    sku_id: str | None,
    category: str,
    item_name: str,
    unit_cost: str,
    currency: str = "CNY",
    unit: str = "件",
    quantity_per_unit: str = "1",
    vendor: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    notes: str | None = None,
    visibility: str = "public",
) -> dict:
    """录一行 accounting.cost_items（require_approval=True，CLI 批后才写）。

    Args:
        sku_id: 绑定 SKU id；None = 共享成本（如全 SKU 物流费）
        category: product | logistics | partner_quote
        item_name: 成本项名（如「瓶身」「顺丰华东」）
        unit_cost: 单价（str 输入避 float 误差，如 "0.50"）
        currency: 默认 CNY
        unit: 单位（"件"/"次"/"箱"...）
        quantity_per_unit: 一个 unit 含多少个最小计量单位（如「一箱 24 瓶」= 24）
        vendor: 供应商
        valid_from: 起始日期 ISO（"2026-05-05"），默认今天
        valid_to: 截止日期 ISO；None = 长期有效
        notes: 备注
        visibility: public（默认，员工可见）| real（仅老板真实成本）|
            shared（两版共用，如物流/平台扣点）

    Returns:
        {ok, result: {cost_item_id, ...}}
    """
    if category not in _VALID_CATEGORIES:
        return {
            "ok": False,
            "error": "invalid_category",
            "hint": f"category 必须是 {sorted(_VALID_CATEGORIES)} 之一，给的是 {category!r}",
        }
    if visibility not in _VALID_VISIBILITIES:
        return {
            "ok": False,
            "error": "invalid_visibility",
            "hint": f"visibility 必须是 {sorted(_VALID_VISIBILITIES)} 之一，给的是 {visibility!r}",
        }

    try:
        unit_cost_dec = Decimal(unit_cost)
        qty_per_unit_dec = Decimal(quantity_per_unit)
    except (InvalidOperation, ValueError) as exc:
        return {
            "ok": False,
            "error": "invalid_decimal",
            "hint": f"unit_cost / quantity_per_unit 必须是数字 str: {exc}",
        }
    if unit_cost_dec < 0:
        return {"ok": False, "error": "invalid_decimal", "hint": "unit_cost 不能为负"}
    if qty_per_unit_dec <= 0:
        return {"ok": False, "error": "invalid_decimal", "hint": "quantity_per_unit 必须 > 0"}

    vf = date.fromisoformat(valid_from) if valid_from else date.today()
    vt = date.fromisoformat(valid_to) if valid_to else None

    pool = get_pool()
    new_id = uuid.uuid4()
    await pool.execute(
        """
        INSERT INTO accounting.cost_items
            (id, sku_id, category, item_name, unit_cost, currency, unit,
             quantity_per_unit, vendor, valid_from, valid_to, notes, visibility)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        new_id, sku_id, category, item_name, unit_cost_dec, currency, unit,
        qty_per_unit_dec, vendor, vf, vt, notes, visibility,
    )

    return {
        "ok": True,
        "result": {
            "cost_item_id": str(new_id),
            "sku_id": sku_id,
            "category": category,
            "item_name": item_name,
            "unit_cost": str(unit_cost_dec),
            "valid_from": vf.isoformat(),
            "visibility": visibility,
        },
    }


@tool_with_audit(
    mcp,
    require_approval=True,
    summary_fn=_disable_cost_summary,
    timeout_seconds=3600,
)
async def disable_cost_item(cost_item_id: str, reason: str = "") -> dict:
    """软删 cost_item（is_active=FALSE）。原行不删，保留历史。

    Args:
        cost_item_id: cost_items.id（uuid str）
        reason: 停用原因（写入 notes 末尾）
    """
    try:
        cid = uuid.UUID(cost_item_id)
    except ValueError:
        return {"ok": False, "error": "invalid_uuid", "hint": f"cost_item_id 不是合法 uuid: {cost_item_id}"}

    pool = get_pool()
    rec = await pool.fetchrow(
        """
        UPDATE accounting.cost_items
           SET is_active = FALSE,
               notes = COALESCE(notes, '') || $2
         WHERE id = $1 AND is_active = TRUE
         RETURNING id, item_name
        """,
        cid, f"\n[停用 reason: {reason}]" if reason else "\n[停用]",
    )
    if rec is None:
        return {
            "ok": False,
            "error": "cost_item_not_found_or_already_inactive",
            "hint": f"cost_item_id={cost_item_id} 不存在或已 is_active=FALSE",
        }

    return {
        "ok": True,
        "result": {
            "cost_item_id": str(rec["id"]),
            "item_name": rec["item_name"],
            "disabled": True,
        },
    }
