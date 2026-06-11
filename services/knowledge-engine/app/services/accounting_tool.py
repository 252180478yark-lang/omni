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
from decimal import Decimal, ROUND_HALF_UP
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

    # 2026-06-11 安全修复（数据审计）: REST /api/v1/accounting/* 链路无口令防护，这里默认
    # 只取员工口径（public+shared）——否则老板录入 visibility='real' 行后，REST /margin 会
    # public+real 双计成本，且任何调用方不带口令即可读到老板真实成本。
    # real 口径只走 MCP tool（app/mcp/tools/accounting.py 的 _resolve_view 口令校验）。
    clauses.append("visibility = ANY(ARRAY['public','shared'])")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)

    pool = get_pool()
    rows = await pool.fetch(
        f"SELECT {_COST_FIELDS} FROM accounting.cost_items{where} "
        f"ORDER BY category, valid_from DESC LIMIT ${len(args)}",
        *args,
    )
    return [_row_to_dict(r) for r in rows]


# ═══ Margin 核心（单一口径纯函数，§3/R-4 地基）═══


def _dec(x: Any) -> Decimal:
    """任意数值 → Decimal（先转 str 避 float 二进制误差）。"""
    return Decimal(str(x))


# 口径常量（§3 难改地基；改前先改蓝图 + 标 needs_boss）
#   - 报价类 partner_quote 不计入成本（仅供比价参考）
#   - 共享成本 sku_id IS NULL（如物流）由调用方决定是否纳入，core 只算给它的行
_COST_CATEGORIES_IN_MARGIN = {"product", "logistics"}  # partner_quote 排除


def _margin_core(
    *,
    cost_lines: list[dict],
    sale_price: Any,
    quantity: Any = 1,
    fee_rate: Any = 0,
) -> dict:
    """毛利/ROI/保本线**单一口径**纯函数（无 DB、无 LLM、无副作用）。

    把原本散在两套 compute_margin 里的算法收口成一处，两个公共入口都调它，
    保证"同一 SKU 同一天毛利两套返回完全相同的数"（蓝图 §3/R-4 DoD：diff=0）。

    Args:
        cost_lines: 已查好的成本行，每行至少含
            {"category": str, "unit_cost": 数值, "quantity_per_unit": 数值,
             ...其它字段原样透传给 breakdown}
            语义同两套老实现："一箱 N 件" → 每件成本 = unit_cost / quantity_per_unit。
            category='partner_quote' 的行**不计入成本**（仅比价用）。
        sale_price: 单件售价
        quantity: 件数（默认 1）
        fee_rate: 渠道/平台扣点率（小数，如 0.02 = 2%）

    口径假设（保守默认，有争议项见 needs_boss）：
        - GMV = sale_price * quantity（**不扣退款**：core 拿到的是成交口径售价，
          退款维度由上游数据负责，core 不在此处估退款）
        - 成本 = Σ(unit_cost/quantity_per_unit) * quantity，仅 product+logistics
        - 渠道费 = GMV * fee_rate
        - 净利 = GMV - 成本 - 渠道费
        - 毛利率 margin = 净利 / GMV
        - ★ROI（保本/广告维度）：core 不接广告花费入参，故 roi 在此返 None，
          由"投后归因"层用真实 ad_metrics 的 spend 算（蓝图 R-4：ROI 后端算非手填）。
          这里只产出**保本线**给老板看"投放要回多少本"：
            - breakeven_roas = 1 / margin（毛利率，毛利率<=0 时 None，无意义）
            - breakeven_price = 单件保本售价（净利=0 时的 sale_price，
              含同比例渠道费：price*(1-fee_rate) = 单件成本 → price = 单件成本/(1-fee_rate)）

    Returns:
        全 Decimal 的规范结果（调用方按各自历史格式量化/转 float/转 str）：
        {
          "gmv": Decimal, "cost_subtotal": Decimal, "channel_fee": Decimal,
          "net_profit": Decimal, "margin": Decimal,
          "unit_cost_total": Decimal,   # 单件成本合计（含份数折算）
          "cost_by_category": {cat: Decimal, ...},
          "breakdown": [ {原行字段 + "line_cost": Decimal, "shared": bool}, ... ],
          "items_used": int,
          "roi": None,                  # core 无广告花费入参 → None（投后层算）
          "breakeven_roas": Decimal | None,
          "breakeven_price": Decimal | None,
        }
    """
    sale = _dec(sale_price)
    qty = _dec(quantity)
    rate = _dec(fee_rate)

    gmv = sale * qty

    unit_cost_total = Decimal("0")  # 单件成本合计（已按份数折算）
    cost_by_category: dict[str, Decimal] = {"product": Decimal("0"), "logistics": Decimal("0")}
    breakdown: list[dict] = []

    for it in cost_lines:
        cat = it.get("category")
        if cat not in _COST_CATEGORIES_IN_MARGIN:
            continue  # partner_quote 等不计入成本
        unit_cost = _dec(it.get("unit_cost") or 0)
        per = _dec(it.get("quantity_per_unit") or 1)
        if per == 0:
            per = Decimal("1")  # 防除零；份数缺失按 1 件
        line_unit = unit_cost / per           # 单件该项成本
        unit_cost_total += line_unit
        cost_by_category[cat] = cost_by_category.get(cat, Decimal("0")) + line_unit
        row = dict(it)  # 原样透传调用方给的字段（item_id/vendor/visibility 等）
        row["line_cost"] = line_unit * qty    # 该项按 qty 件的总成本
        row["shared"] = it.get("sku_id") is None
        breakdown.append(row)

    cost_subtotal = unit_cost_total * qty
    channel_fee = gmv * rate
    net_profit = gmv - cost_subtotal - channel_fee
    margin = (net_profit / gmv) if gmv > 0 else Decimal("0")

    # ── 新增（加法）：ROI / 保本线 ─────────────────────────────
    # roi：core 无广告花费入参 → None（蓝图 R-4：ROI 由投后归因层用真实 spend 算，拒手填）
    roi: Decimal | None = None
    # breakeven_roas = 1 / 毛利率（毛利率 <= 0 时不存在保本点 → None）
    breakeven_roas: Decimal | None = (Decimal("1") / margin) if margin > 0 else None
    # breakeven_price = 单件保本售价：price*(1-rate) = 单件成本 → price = 单件成本/(1-rate)
    #   rate >= 1（扣点 ≥100%，异常）时无解 → None
    breakeven_price: Decimal | None = (
        (unit_cost_total / (Decimal("1") - rate)) if rate < 1 else None
    )

    return {
        "gmv": gmv,
        "cost_subtotal": cost_subtotal,
        "channel_fee": channel_fee,
        "net_profit": net_profit,
        "margin": margin,
        "unit_cost_total": unit_cost_total,
        "cost_by_category": cost_by_category,
        "breakdown": breakdown,
        "items_used": len(breakdown),
        "roi": roi,
        "breakeven_roas": breakeven_roas,
        "breakeven_price": breakeven_price,
    }


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

    # ── §3/R-4：算法收口到 _margin_core（单一口径），此入口只做"取数 + 映回历史字段名"──
    # 给 core 的 cost_lines 透传 item_id/item_name/vendor，core 算完原样带回 breakdown。
    cost_lines = [
        {
            "category": it["category"],
            "unit_cost": float(it["unit_cost"]),
            "quantity_per_unit": float(it.get("quantity_per_unit") or 1.0),
            "item_id": it["id"],
            "item_name": it["item_name"],
            "vendor": it.get("vendor"),
            "sku_id": it.get("sku_id"),
        }
        for it in items
    ]
    core = _margin_core(
        cost_lines=cost_lines,
        sale_price=sale_price,
        quantity=quantity,
        fee_rate=platform_fee_rate,
    )

    # core 返回全 Decimal；本入口历史契约是 float + 这套字段名，逐一映回（字段名/结构不变）
    revenue = float(core["gmv"])
    platform_fee = float(core["channel_fee"])
    # total_cost 历史口径 = 成本 + 平台费（保持不变）
    total_cost = float(core["cost_subtotal"] + core["channel_fee"])
    net_profit = float(core["net_profit"])
    net_margin = float(core["margin"])

    # breakdown 映回历史字段名（item_id/item_name/category/unit_cost/quantity_per_unit/
    # vendor/line_cost/shared），不引入 core 内部新键
    breakdown: list[dict] = []
    for row in core["breakdown"]:
        breakdown.append({
            "item_id": row.get("item_id"),
            "item_name": row.get("item_name"),
            "category": row.get("category"),
            "unit_cost": float(row.get("unit_cost") or 0.0),
            "quantity_per_unit": float(row.get("quantity_per_unit") or 1.0),
            "vendor": row.get("vendor"),
            "line_cost": round(float(row["line_cost"]), 4),
            "shared": row.get("shared", False),
        })
    cost_by_cat = {k: round(float(v), 2) for k, v in core["cost_by_category"].items()}

    # 新增字段（加法，不动现有键）：roi / breakeven_roas / breakeven_price
    roi = core["roi"]  # 此入口无广告花费 → None（投后归因层算）
    breakeven_roas = (
        round(float(core["breakeven_roas"]), 4)
        if core["breakeven_roas"] is not None else None
    )
    breakeven_price = (
        round(float(core["breakeven_price"]), 4)
        if core["breakeven_price"] is not None else None
    )

    return {
        "sku_id": sku_id,
        "sale_price": sale_price,
        "quantity": quantity,
        "revenue": round(revenue, 2),
        "platform_fee_rate": platform_fee_rate,
        "platform_fee": round(platform_fee, 2),
        "cost_breakdown": breakdown,
        "cost_by_category": cost_by_cat,
        "total_cost": round(total_cost, 2),
        "net_profit": round(net_profit, 2),
        "net_margin": round(net_margin, 4),
        "items_used": len(breakdown),
        # ── §3/R-4 新增（加法）──
        "roi": roi,
        "breakeven_roas": breakeven_roas,
        "breakeven_price": breakeven_price,
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
