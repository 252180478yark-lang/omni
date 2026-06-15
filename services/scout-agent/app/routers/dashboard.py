"""
Dashboard endpoints for Workspace page.

GET /dashboard/5a               — brand-level 5A asset (last 7 days)
GET /dashboard/shop-todos       — shop todo counts (today)
GET /dashboard/strategy-cards   — 5A flow data for 6 scene strategy cards
"""
from __future__ import annotations

from app.database import get_pool
from fastapi import APIRouter

router = APIRouter()

SHOP_TODO_METRICS = [
    ("shop_pending_shipment",  "待发货",    "https://fxg.jinritemai.com/ffa/main/order/list"),
    ("shop_pending_aftersale", "待处理售后", "https://fxg.jinritemai.com/ffa/main/aftersale/list"),
    ("shop_pending_review",    "待回评",     "https://fxg.jinritemai.com/ffa/main/comment/list"),
    ("shop_pending_audit",     "待审核",     "https://fxg.jinritemai.com/ffa/main/product/audit"),
    ("shop_abnormal_order",    "异常订单",   "https://fxg.jinritemai.com/ffa/main/order/list?tab=abnormal"),
    ("shop_appeal_in_progress","申诉中",     "https://fxg.jinritemai.com/ffa/main/appeal/list"),
]

# Scene keys come from yuntu/5a-flow.yaml LLM prompt (English keys).
# Map to short Chinese label + actionable suggestion for the strategy cards.
SCENE_LABELS = {
    "acquire":      "拉新",
    "nurture":      "蓄水",
    "seed":         "种草",
    "live_convert": "直播转化",
    "seed_convert": "种草转化",
    "repurchase":   "复购",
}

SCENE_SUGGESTIONS = {
    "acquire":      "投信息流曝光或达人合作扩流量池",
    "nurture":      "多发短视频 + 搜索卡词吸引潜客",
    "seed":         "制作场景化短视频 + 知识问答激活兴趣",
    "live_convert": "开播时发福利券 + 加大直播间流量",
    "seed_convert": "精准收割主图/主推 + 详情页强化卖点",
    "repurchase":   "触达私域老客 + 会员专属权益召回",
}


@router.get("/dashboard/5a")
async def get_brand_5a(days: int = 7):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date,
                   o_count, a1_aware, a2_appeal, a3_ask, a4_act, a5_advocate, total_5a,
                   a1_outperform_pct, a2_outperform_pct, a3_outperform_pct,
                   a4_outperform_pct, a5_outperform_pct, total_outperform_pct,
                   o_industry_avg, a1_industry_avg, a2_industry_avg,
                   a3_industry_avg, a4_industry_avg, a5_industry_avg,
                   ai_summary
            FROM mvp_5a_asset_daily
            WHERE sku_id = ''
            ORDER BY date DESC
            LIMIT $1
            """,
            days,
        )
    return [dict(r) for r in rows]


@router.get("/dashboard/shop-todos")
async def get_shop_todos():
    pool = await get_pool()
    metric_names = [m[0] for m in SHOP_TODO_METRICS]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT metric_name, value
            FROM mvp_daily_metric
            WHERE sku_id = '_SHOP_'
              AND metric_name = ANY($1)
              AND date = CURRENT_DATE - 1
              AND platform = 'douyin'
            """,
            metric_names,
        )
    value_map = {r["metric_name"]: int(r["value"] or 0) for r in rows}
    return [
        {
            "metric": key,
            "label": label,
            "value": value_map.get(key),
            "link": link,
        }
        for key, label, link in SHOP_TODO_METRICS
    ]


@router.get("/dashboard/strategy-cards")
async def get_strategy_cards():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT scene, flow_count, outperform_pct, industry_avg
            FROM mvp_5a_flow_daily
            WHERE sku_id = ''
              AND date = (
                  SELECT MAX(date) FROM mvp_5a_flow_daily WHERE sku_id = ''
              )
            ORDER BY scene
            """,
        )
    result = []
    for r in rows:
        scene_key = r["scene"]
        scene_short = SCENE_LABELS.get(scene_key, scene_key)
        suggestion = SCENE_SUGGESTIONS.get(scene_key, "")
        pct = float(r["outperform_pct"] or 0)
        result.append({
            "scene": scene_key,
            "scene_label": scene_short,
            "flow_count": r["flow_count"],
            "outperform_pct": pct,
            "industry_avg": r["industry_avg"],
            "suggestion": suggestion,
        })
    return result
