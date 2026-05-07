"""W2 T4 + T5：accounting tools。

- query_costs：纯 DB 查 accounting.cost_items（migration 015）
- compute_margin：DB 查成本 + Python 算账（确定性）+ LLM 写解读（T5 加）

W4-B 切片 7：两版成本 + 口令（migration 018）
- view='public'（默认，员工版）+ view='real'（老板版，需 passphrase）
- shared visibility 行两版都包含

W4-B 切片 8：工厂出厂价字典（migration 019）
- list_product_prices：查 accounting.product_price_list（工厂单品出厂价）
- 给 agent 在组 mvp_sku 成本时调用——查工厂 SKU 出厂价 → 按组合关系算
  → 录到 cost_items
"""
from __future__ import annotations

from app.config import settings
from app.database import get_pool
from app.mcp import prompts
from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.mcp.utils import decimal_to_jsonable


_VALID_VIEWS = {"public", "real"}


def _resolve_view(view: str, passphrase: str) -> tuple[bool, str, list[str], str]:
    """决定本次查询用哪些 visibility 值。

    Returns:
        (ok, error, allowed_visibilities, hint)
    """
    if view not in _VALID_VIEWS:
        return False, "invalid_view", [], (
            f"view 必须是 {sorted(_VALID_VIEWS)} 之一，给的是 {view!r}"
        )
    if view == "public":
        return True, "", ["public", "shared"], ""
    # view == "real"
    required = (settings.cost_real_view_passphrase or "").strip()
    if required and (passphrase or "").strip() != required:
        return False, "wrong_passphrase", [], (
            "view='real' 需正确 passphrase 才能解锁老板真实成本；"
            "传 passphrase=<.env COST_REAL_VIEW_PASSPHRASE 设的值>"
        )
    return True, "", ["real", "shared"], ""


@tool_with_audit(mcp, require_approval=False)
async def query_costs(
    sku_id: str,
    view: str = "public",
    passphrase: str = "",
) -> dict:
    """查 SKU 的有效成本项（含共享成本如物流）。纯 DB 查询，无 LLM 调用。

    Args:
        sku_id: SKU id
        view: public（默认，员工出厂价）| real（老板真实成本，需 passphrase）
        passphrase: view='real' 时校验，跟 .env COST_REAL_VIEW_PASSPHRASE 比对

    Returns:
        {"ok": True, "result": {"view": str, "cost_items": [{id, sku_id, category,
            item_name, unit_cost, currency, unit, quantity_per_unit, vendor,
            visibility, valid_from, valid_to, notes}, ...]}}

        category 取值：product | logistics | partner_quote
        visibility 取值：public（员工版）| real（老板版）| shared（两版共用）
        sku_id 为 None 的行表示共享成本（如全 SKU 共用的物流费）
    """
    ok, err, allowed_vis, hint = _resolve_view(view, passphrase)
    if not ok:
        return {"ok": False, "error": err, "hint": hint}

    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, sku_id, category, item_name, unit_cost, currency, unit,
               quantity_per_unit, vendor, visibility, valid_from, valid_to, notes
        FROM accounting.cost_items
        WHERE (sku_id = $1 OR sku_id IS NULL)
          AND is_active = TRUE
          AND visibility = ANY($2::text[])
          AND valid_from <= CURRENT_DATE
          AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
        ORDER BY (sku_id IS NULL), category, valid_from DESC
        """,
        sku_id, allowed_vis,
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
    return {"ok": True, "result": {"view": view, "cost_items": items}}


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
    view: str = "public",
    passphrase: str = "",
) -> dict:
    """算 SKU 在某渠道的净利率。LLM 不做数学，只写解读。

    Args:
        sku_id: SKU id
        channel: 渠道（douyin/tmall/jd 等）
        sale_price: 售价（str 输入避 float 误差）；None 则查 mvp_sku.sale_price
        qty: 数量（默认 1）
        channel_fee_rate: 渠道扣点（默认 0.05 = 5%）
        skip_llm: 测试用，跳过 LLM 解读
        view: public（默认，员工出厂价算）| real（老板真实成本算，需 passphrase）
        passphrase: view='real' 时校验，跟 .env COST_REAL_VIEW_PASSPHRASE 比对

    Returns:
        {"ok": True,
         "result": {"view": str,
                    "breakdown": {gmv, cost_total, channel_fee, net_profit,
                                 margin_pct, items: [...]},
                    "interpretation": "..."},  # LLM 写的人话
         "trace": {...},
         "next_step_hint": {suggested_tool: "generate_brief", ...}}
    """
    ok, err, allowed_vis, hint = _resolve_view(view, passphrase)
    if not ok:
        return {"ok": False, "error": err, "hint": hint}

    pool = get_pool()

    # 1. 拿成本（直接 SQL，避免装饰器嵌套；同 query_costs 同样的过滤条件 + visibility）
    cost_rows = await pool.fetch(
        """
        SELECT category, item_name, unit_cost, quantity_per_unit, visibility
        FROM accounting.cost_items
        WHERE (sku_id = $1 OR sku_id IS NULL)
          AND is_active = TRUE
          AND visibility = ANY($2::text[])
          AND valid_from <= CURRENT_DATE
          AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
        """,
        sku_id, allowed_vis,
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
            "visibility": r["visibility"],
        })

    # 2. 拿售价（如未给）。mvp_sku 实际 schema：PK=id，价格列是 price_min/price_max
    # （不是 plan 字面写的 sku_id/sale_price）。默认用 price_min（最低档），
    # 老板想算其他档位可显式传 sale_price="..."。
    if sale_price is None:
        srow = await pool.fetchrow(
            "SELECT price_min FROM mvp_sku WHERE id = $1", sku_id
        )
        sale_price = str(srow["price_min"]) if srow and srow["price_min"] else "0"

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
        "view": view,
        "items": cost_items,
    }

    # 4. LLM 写解读（不让它算数学）
    model_cfg = get_model_for_tool("compute_margin")
    interpretation = ""
    final_prompt = ""
    cost_estimate = "skipped"

    if not skip_llm:
        sys_msg = prompts.render("compute_margin.system")
        user_msg = prompts.render(
            "compute_margin.user",
            breakdown_json=json.dumps(breakdown, ensure_ascii=False, indent=2),
        )
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
        "result": {"view": view, "breakdown": breakdown, "interpretation": interpretation},
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


# ─── W4-B 切片 8：工厂出厂价字典 query tool ────────────────────────────────


@tool_with_audit(mcp, require_approval=False)
async def list_product_prices(
    query: str = "",
    vendor: str = "",
    barcode: str = "",
    limit: int = 30,
) -> dict:
    """查工厂出厂价字典 accounting.product_price_list。

    给 agent 用——组 mvp_sku 成本时先 list_product_prices 查工厂单品出厂价，
    再按组合关系算总价（人工识别 / 老板告诉的组合关系）。

    Args:
        query: 模糊搜（match product_name / spec / grade），空则不过滤
        vendor: 'and田宽产品' 或 '辣嘴宽心系列产品'，空则全要
        barcode: 精确条码匹配（match 优先级最高，命中后忽略 query/vendor）
        limit: 返回上限（默认 30，最大 200）

    Returns:
        {ok, result: {total: int, items: [{id, vendor, product_name, grade,
            spec, pack_size, unit_price, case_price, barcode, visibility,
            valid_from}, ...]}}
    """
    pool = get_pool()
    limit = max(1, min(int(limit or 30), 200))

    # barcode 精确匹配优先
    if barcode and barcode.strip():
        rows = await pool.fetch(
            """
            SELECT id, vendor, product_name, grade, spec, pack_size,
                   unit_price, case_price, barcode, visibility, valid_from
              FROM accounting.product_price_list
             WHERE barcode = $1 AND is_active = TRUE
             ORDER BY valid_from DESC
             LIMIT $2
            """,
            barcode.strip(), limit,
        )
    else:
        # 模糊搜 + vendor 过滤
        q_pattern = f"%{query.strip()}%" if query and query.strip() else "%"
        v_pattern = vendor.strip() if vendor and vendor.strip() else None
        if v_pattern:
            rows = await pool.fetch(
                """
                SELECT id, vendor, product_name, grade, spec, pack_size,
                       unit_price, case_price, barcode, visibility, valid_from
                  FROM accounting.product_price_list
                 WHERE is_active = TRUE
                   AND vendor = $1
                   AND (product_name ILIKE $2 OR spec ILIKE $2 OR grade ILIKE $2)
                 ORDER BY product_name, spec
                 LIMIT $3
                """,
                v_pattern, q_pattern, limit,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id, vendor, product_name, grade, spec, pack_size,
                       unit_price, case_price, barcode, visibility, valid_from
                  FROM accounting.product_price_list
                 WHERE is_active = TRUE
                   AND (product_name ILIKE $1 OR spec ILIKE $1 OR grade ILIKE $1)
                 ORDER BY vendor, product_name, spec
                 LIMIT $2
                """,
                q_pattern, limit,
            )

    items = []
    for r in rows:
        d = decimal_to_jsonable(dict(r))
        if d.get("id") is not None:
            d["id"] = str(d["id"])
        if d.get("valid_from") is not None:
            d["valid_from"] = str(d["valid_from"])
        items.append(d)
    return {
        "ok": True,
        "result": {
            "total": len(items),
            "items": items,
        },
    }
