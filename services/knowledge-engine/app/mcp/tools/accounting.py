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


import json
from decimal import Decimal, ROUND_HALF_UP

from app.mcp.model_config import get_model_for_tool
from app.mcp.trace import attach_next_step, build_trace
from app.services.ai_hub_client import AIHubClient


def _to_dec(x) -> Decimal:
    return Decimal(str(x))


@tool_with_audit(mcp, require_approval=False)
async def compute_margin(
    sku_id: str,
    channel: str,
    sale_price: str | None = None,
    qty: int = 1,
    channel_fee_rate: str = "0.05",
    skip_llm: bool = False,
) -> dict:
    """算 SKU 在某渠道的净利率。LLM 不做数学，只写解读。

    Args:
        sku_id: SKU id
        channel: 渠道（douyin/tmall/jd 等）
        sale_price: 售价（str 输入避 float 误差）；None 则查 mvp_sku.sale_price
        qty: 数量（默认 1）
        channel_fee_rate: 渠道扣点（默认 0.05 = 5%）
        skip_llm: 测试用，跳过 LLM 解读

    Returns:
        {"ok": True,
         "result": {"breakdown": {gmv, cost_total, channel_fee, net_profit,
                                 margin_pct, items: [...]},
                    "interpretation": "..."},  # LLM 写的人话
         "trace": {...},
         "next_step_hint": {suggested_tool: "generate_brief", ...}}
    """
    pool = get_pool()

    # 1. 拿成本（直接 SQL，避免装饰器嵌套；同 query_costs 同样的过滤条件）
    cost_rows = await pool.fetch(
        """
        SELECT category, item_name, unit_cost, quantity_per_unit
        FROM accounting.cost_items
        WHERE (sku_id = $1 OR sku_id IS NULL)
          AND is_active = TRUE
          AND valid_from <= CURRENT_DATE
          AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
        """,
        sku_id,
    )

    cost_items = []
    cost_total = Decimal("0")
    for r in cost_rows:
        line = _to_dec(r["unit_cost"]) / _to_dec(r["quantity_per_unit"])
        cost_total += line
        cost_items.append({
            "category": r["category"],
            "item_name": r["item_name"],
            "line_cost": str(line.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        })

    # 2. 拿售价（如未给）
    if sale_price is None:
        srow = await pool.fetchrow(
            "SELECT sale_price FROM mvp_sku WHERE sku_id = $1", sku_id
        )
        sale_price = str(srow["sale_price"]) if srow and srow["sale_price"] else "0"

    sale_dec = _to_dec(sale_price)
    qty_dec = _to_dec(qty)
    fee_rate = _to_dec(channel_fee_rate)

    # 3. 算账
    gmv = sale_dec * qty_dec
    channel_fee = (gmv * fee_rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    cost_subtotal = (cost_total * qty_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    net_profit = (gmv - cost_subtotal - channel_fee).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    margin_pct = (net_profit / gmv).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if gmv > 0 else Decimal("0")

    breakdown = {
        "sku_id": sku_id,
        "channel": channel,
        "qty": qty,
        "sale_price": str(sale_dec),
        "channel_fee_rate": str(fee_rate),
        "gmv": str(gmv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "cost_total": str(cost_subtotal),
        "channel_fee": str(channel_fee),
        "net_profit": str(net_profit),
        "margin_pct": str(margin_pct),
        "items": cost_items,
    }

    # 4. LLM 写解读（不让它算数学）
    model_cfg = get_model_for_tool("compute_margin")
    interpretation = ""
    final_prompt = ""
    cost_estimate = "skipped"

    if not skip_llm:
        sys_msg = (
            "你是调味品工厂老板的财务助理。下面给你一组已算好的成本/利润数字"
            "（精确,不要重算）。用 2-3 句话写解读：(a) 净利率落在什么档位"
            "（健康/边缘/亏本）；(b) 成本结构里最大的占比是什么；"
            "(c) 如果想提净利 5 个点,最现实的杠杆点是什么。"
            "说人话,不要废话,不要复述数字。"
        )
        user_msg = "数据:\n" + json.dumps(breakdown, ensure_ascii=False, indent=2)
        final_prompt = sys_msg + "\n\n" + user_msg
        client = AIHubClient()
        try:
            resp = await client.chat(
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                provider=model_cfg.get("provider", "gemini"),
                model=model_cfg.get("model", "gemini-3-flash-preview"),
                temperature=model_cfg.get("temperature", 0.1),
                max_tokens=600,
                enforce_human_voice=True,
            )
            # ai-provider-hub chat response shape：实测可能是 {content, provider, model, usage}
            # 也可能是 {choices:[{message:{content:...}}]}（OpenAI 风格）
            # 兼容多种 shape：
            interpretation = (
                ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
                or resp.get("text")
                or resp.get("content")
                or ""
            ).strip()
            cost_estimate = "1 quota call (~few hundred tokens)"
        except Exception as exc:
            interpretation = f"[LLM 解读失败: {type(exc).__name__}: {exc}]"
            cost_estimate = "0 (LLM 调用失败)"

    result = {
        "ok": True,
        "result": {"breakdown": breakdown, "interpretation": interpretation},
        "trace": build_trace(
            provider=model_cfg.get("provider", "gemini"),
            model=model_cfg.get("model", "gemini-3-flash-preview"),
            prompt=final_prompt or "[skipped]",
            params={
                "temperature": model_cfg.get("temperature", 0.1),
                "max_tokens": 600,
            },
            cost_estimate=cost_estimate,
        ),
    }
    return attach_next_step(
        result,
        suggested_tool="generate_brief",
        suggested_args={"sku_id": sku_id, "channel": channel},
        human_text=f"利润 OK 的话出 brief（generate_brief，~1 quota call）",
    )
