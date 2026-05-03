"""算账工具 — 把成本/利润查询从 RAG 模糊匹配迁出，走结构化 SQL.

设计要点
- 时间区间：valid_from/valid_to 让价格变更走"新行 + 关旧行"，保留历史
- 当前有效：query_costs(active_only=True) 默认只返回当前生效的（valid_from <= today
  AND (valid_to IS NULL OR valid_to >= today))
- 共享成本：sku_id IS NULL 表示跨 SKU 共享（如物流费），算账时可选纳入
- LLM 解析：nl_to_cost_query 把"这款产品净利"翻成 sku_id + 价格 + 意图
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any
from uuid import uuid4

import httpx

from app.config import settings
from app.database import get_pool

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = {"product", "logistics", "partner_quote"}

_COST_FIELDS = (
    "id, sku_id, category, item_name, unit_cost, currency, unit, "
    "quantity_per_unit, vendor, valid_from, valid_to, is_active, notes, "
    "created_at, updated_at"
)


def _row_to_dict(row: Any) -> dict:
    if row is None:
        return None  # type: ignore[return-value]
    d = dict(row)
    # asyncpg numeric → Decimal；前端要 number
    for k in ("unit_cost", "quantity_per_unit"):
        if d.get(k) is not None:
            d[k] = float(d[k])
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    for k in ("valid_from", "valid_to", "created_at", "updated_at"):
        v = d.get(k)
        if v is not None:
            d[k] = v.isoformat()
    return d


# ═══ CRUD ═══


async def create_cost_item(payload: dict) -> dict:
    if payload.get("category") not in _VALID_CATEGORIES:
        raise ValueError(f"invalid category: {payload.get('category')}")
    pool = get_pool()
    cid = str(uuid4())
    row = await pool.fetchrow(
        f"""
        INSERT INTO accounting.cost_items
            (id, sku_id, category, item_name, unit_cost, currency, unit,
             quantity_per_unit, vendor, valid_from, valid_to, notes)
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9,
                COALESCE($10, CURRENT_DATE), $11, $12)
        RETURNING {_COST_FIELDS}
        """,
        cid,
        payload.get("sku_id"),
        payload["category"],
        payload["item_name"],
        payload["unit_cost"],
        payload.get("currency") or "CNY",
        payload.get("unit") or "件",
        payload.get("quantity_per_unit") or 1.0,
        payload.get("vendor"),
        payload.get("valid_from"),
        payload.get("valid_to"),
        payload.get("notes"),
    )
    return _row_to_dict(row)


async def update_cost_item(item_id: str, payload: dict) -> dict | None:
    """部分更新；只更新 payload 里非 None 的字段."""
    if "category" in payload and payload["category"] not in _VALID_CATEGORIES:
        raise ValueError(f"invalid category: {payload['category']}")
    fields = []
    values: list[Any] = []
    idx = 1
    for col in (
        "sku_id", "category", "item_name", "unit_cost", "currency", "unit",
        "quantity_per_unit", "vendor", "valid_from", "valid_to", "is_active", "notes",
    ):
        if col in payload and payload[col] is not None:
            fields.append(f"{col} = ${idx}")
            values.append(payload[col])
            idx += 1
    if not fields:
        return await get_cost_item(item_id)
    values.append(item_id)
    pool = get_pool()
    row = await pool.fetchrow(
        f"UPDATE accounting.cost_items SET {', '.join(fields)} "
        f"WHERE id = ${idx}::uuid RETURNING {_COST_FIELDS}",
        *values,
    )
    return _row_to_dict(row) if row else None


async def get_cost_item(item_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        f"SELECT {_COST_FIELDS} FROM accounting.cost_items WHERE id = $1::uuid",
        item_id,
    )
    return _row_to_dict(row) if row else None


async def delete_cost_item(item_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute(
        "DELETE FROM accounting.cost_items WHERE id = $1::uuid", item_id,
    )
    return result.endswith(" 1")


async def bulk_create_cost_items(payloads: list[dict]) -> dict:
    """批量入库，事务内逐条 INSERT，遇到错误整批回滚.

    返回 {created: [...], errors: [{index, error}]}
    """
    if not payloads:
        return {"created": [], "errors": []}
    pool = get_pool()
    created: list[dict] = []
    errors: list[dict] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for idx, p in enumerate(payloads):
                if p.get("category") not in _VALID_CATEGORIES:
                    errors.append({"index": idx, "error": f"invalid category: {p.get('category')}"})
                    continue
                try:
                    cid = str(uuid4())
                    row = await conn.fetchrow(
                        f"""
                        INSERT INTO accounting.cost_items
                            (id, sku_id, category, item_name, unit_cost, currency, unit,
                             quantity_per_unit, vendor, valid_from, valid_to, notes)
                        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9,
                                COALESCE($10, CURRENT_DATE), $11, $12)
                        RETURNING {_COST_FIELDS}
                        """,
                        cid,
                        p.get("sku_id"),
                        p["category"],
                        p["item_name"],
                        p["unit_cost"],
                        p.get("currency") or "CNY",
                        p.get("unit") or "件",
                        p.get("quantity_per_unit") or 1.0,
                        p.get("vendor"),
                        p.get("valid_from"),
                        p.get("valid_to"),
                        p.get("notes"),
                    )
                    created.append(_row_to_dict(row))
                except Exception as exc:
                    errors.append({"index": idx, "error": str(exc)})
                    raise  # transaction rollback
    return {"created": created, "errors": errors}


# ═══ Query ═══


async def query_costs(
    *,
    sku_id: str | None = None,
    category: str | None = None,
    item_name_search: str | None = None,
    active_only: bool = True,
    on_date: date | None = None,
    include_shared: bool = True,
    limit: int = 200,
) -> list[dict]:
    """
    Args:
        sku_id: 绑定指定 SKU 的成本项
        include_shared: 同时返回 sku_id IS NULL 的共享成本（如物流）
        active_only: 仅返回 is_active=TRUE 且当前有效（在 on_date 范围内）的
        on_date: 检查"当前有效"的参考日期，None=今天
    """
    if category and category not in _VALID_CATEGORIES:
        raise ValueError(f"invalid category: {category}")

    clauses: list[str] = []
    args: list[Any] = []

    if sku_id and include_shared:
        args.append(sku_id)
        clauses.append(f"(sku_id = ${len(args)} OR sku_id IS NULL)")
    elif sku_id:
        args.append(sku_id)
        clauses.append(f"sku_id = ${len(args)}")
    elif include_shared is False:
        clauses.append("sku_id IS NOT NULL")

    if category:
        args.append(category)
        clauses.append(f"category = ${len(args)}")

    if item_name_search:
        args.append(f"%{item_name_search}%")
        clauses.append(f"item_name ILIKE ${len(args)}")

    if active_only:
        args.append(on_date or date.today())
        anchor = f"${len(args)}"
        clauses.append(
            f"is_active = TRUE AND valid_from <= {anchor} "
            f"AND (valid_to IS NULL OR valid_to >= {anchor})"
        )

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)

    pool = get_pool()
    rows = await pool.fetch(
        f"SELECT {_COST_FIELDS} FROM accounting.cost_items{where} "
        f"ORDER BY category, valid_from DESC LIMIT ${len(args)}",
        *args,
    )
    return [_row_to_dict(r) for r in rows]


# ═══ Margin ═══


async def compute_margin(
    *,
    sku_id: str,
    sale_price: float,
    quantity: float = 1.0,
    platform_fee_rate: float = 0.0,
    include_shared_logistics: bool = True,
) -> dict:
    """计算 SKU 净利率（取当前有效成本，按 quantity 件折算）.

    成本归类：
      - product: 产品类（原料/包装/瓶身），按"单件成本 / quantity_per_unit * quantity"折算
      - logistics: 物流类，按 quantity 件计
      - partner_quote: 合作报价仅作参考，不计入净利

    返回字段：
      revenue / platform_fee / cost_breakdown / total_cost / net_profit / net_margin
    """
    if sale_price <= 0 or quantity <= 0:
        raise ValueError("sale_price 和 quantity 必须 > 0")

    items = await query_costs(
        sku_id=sku_id,
        active_only=True,
        include_shared=include_shared_logistics,
    )

    revenue = sale_price * quantity
    platform_fee = revenue * platform_fee_rate

    cost_by_cat: dict[str, float] = {"product": 0.0, "logistics": 0.0}
    breakdown: list[dict] = []

    for it in items:
        cat = it["category"]
        if cat == "partner_quote":
            continue  # 报价不计成本
        unit_cost = float(it["unit_cost"])
        per = float(it.get("quantity_per_unit") or 1.0)
        # "一箱 24 瓶"语义：unit_cost 是箱单价，每瓶成本 = unit_cost / per
        # 直接卖 quantity 件 → 总成本 = unit_cost / per * quantity
        line_cost = unit_cost / per * quantity
        cost_by_cat[cat] = cost_by_cat.get(cat, 0.0) + line_cost
        breakdown.append({
            "item_id": it["id"],
            "item_name": it["item_name"],
            "category": cat,
            "unit_cost": unit_cost,
            "quantity_per_unit": per,
            "vendor": it.get("vendor"),
            "line_cost": round(line_cost, 4),
            "shared": it.get("sku_id") is None,
        })

    total_cost = sum(cost_by_cat.values()) + platform_fee
    net_profit = revenue - total_cost
    net_margin = net_profit / revenue if revenue > 0 else 0.0

    return {
        "sku_id": sku_id,
        "sale_price": sale_price,
        "quantity": quantity,
        "revenue": round(revenue, 2),
        "platform_fee_rate": platform_fee_rate,
        "platform_fee": round(platform_fee, 2),
        "cost_breakdown": breakdown,
        "cost_by_category": {k: round(v, 2) for k, v in cost_by_cat.items()},
        "total_cost": round(total_cost, 2),
        "net_profit": round(net_profit, 2),
        "net_margin": round(net_margin, 4),
        "items_used": len(breakdown),
    }


# ═══ NL → 结构化查询（LLM 解析） ═══


_NL_QUERY_PROMPT = """你是一个算账助手。把下面的中文问题翻译成结构化查询参数。

可用操作（intent）：
- "list_costs"：列出某 SKU 的成本明细
- "compute_margin"：计算某 SKU 的净利率（需要售价）
- "compare_vendors"：对比 partner_quote 报价

输出严格 JSON（不要 markdown 包裹），结构如下：
{{
  "intent": "list_costs" | "compute_margin" | "compare_vendors",
  "sku_id": "...",       // 若问题里没提 SKU 则填 null
  "category": "product" | "logistics" | "partner_quote" | null,
  "sale_price": 19.9,    // 若问题里没说价格则 null
  "quantity": 1,
  "explanation": "..."   // 一句话说明你的理解
}}

如果用户上下文已传入 SKU={ctx_sku}、价格={ctx_price}，可直接用。

问题：{query}"""


async def nl_to_cost_query(
    query: str,
    *,
    ctx_sku_id: str | None = None,
    ctx_sale_price: float | None = None,
    model: str | None = None,
) -> dict:
    """LLM 把中文自然语言翻成结构化查询参数。"""
    prompt = _NL_QUERY_PROMPT.format(
        query=query,
        ctx_sku=ctx_sku_id or "未指定",
        ctx_price=ctx_sale_price if ctx_sale_price is not None else "未指定",
    )
    payload: dict = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 800,
    }
    if model:
        payload["model"] = model

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.ai_provider_hub_url}/api/v1/ai/chat",
            json=payload,
        )
        resp.raise_for_status()
        raw = (resp.json().get("content") or "").strip()

    cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
    s = cleaned.find("{")
    e = cleaned.rfind("}")
    if s < 0 or e <= s:
        raise ValueError(f"LLM 未返回有效 JSON: {raw[:200]}")
    parsed = json.loads(cleaned[s:e+1])

    # 上下文兜底
    if not parsed.get("sku_id") and ctx_sku_id:
        parsed["sku_id"] = ctx_sku_id
    if not parsed.get("sale_price") and ctx_sale_price is not None:
        parsed["sale_price"] = ctx_sale_price
    return parsed


async def answer_cost_question(
    query: str,
    *,
    ctx_sku_id: str | None = None,
    ctx_sale_price: float | None = None,
    platform_fee_rate: float = 0.0,
) -> dict:
    """端到端：自然语言 → 解析 → 执行 → 返回结构化结果（可被 chat 直接调用）。"""
    parsed = await nl_to_cost_query(
        query, ctx_sku_id=ctx_sku_id, ctx_sale_price=ctx_sale_price,
    )
    intent = parsed.get("intent") or "list_costs"
    sku_id = parsed.get("sku_id")
    category = parsed.get("category")

    if intent == "compute_margin":
        if not sku_id or not parsed.get("sale_price"):
            return {
                "intent": intent,
                "ok": False,
                "reason": "缺少 sku_id 或 sale_price，无法算净利率",
                "parsed": parsed,
            }
        margin = await compute_margin(
            sku_id=sku_id,
            sale_price=float(parsed["sale_price"]),
            quantity=float(parsed.get("quantity") or 1.0),
            platform_fee_rate=platform_fee_rate,
        )
        return {"intent": intent, "ok": True, "parsed": parsed, "result": margin}

    if intent == "compare_vendors":
        items = await query_costs(
            sku_id=sku_id, category="partner_quote", active_only=True,
        )
        return {"intent": intent, "ok": True, "parsed": parsed, "result": items}

    # 默认 list_costs
    items = await query_costs(sku_id=sku_id, category=category, active_only=True)
    return {"intent": "list_costs", "ok": True, "parsed": parsed, "result": items}
