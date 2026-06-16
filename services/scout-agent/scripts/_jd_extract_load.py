"""切片2 端到端证明：把 passive 抓的商智响应抽成指标，落 mvp_daily_metric(platform='jd')。

读 _jd_responses.jsonl → getCoreTrend.ajax（list 带 dt 日级）→ 映射核心指标码 → upsert。
口径：jd_ 前缀（京东 gmv≠抖音 gmv_paid，命名带平台限定）；只落全店 _SHOP_（切片2 范围）。
    docker exec -w /app omni-scout-agent python scripts/_jd_extract_load.py
"""
import asyncio
import datetime
import json
import os

import asyncpg

JSONL = "/app/catalog/_jd_responses.jsonl"
DB = os.environ["DATABASE_URL"]
PLATFORM, SHOP, SRC = "jd", "_SHOP_", "jd_passive_capture"

# 指标码 → mvp_daily_metric.metric_name（实测响应值确认口径）
INDICATOR_MAP = {
    "jdr_sch_trade_deal_ord_ord_amt_sz_trade_deal_snapshot": "jd_gmv",            # 成交金额
    "jdr_sch_trade_deal_ord_ord_qtty_sz_trade_deal_snapshot": "jd_order_cnt",     # 成交订单数
    "jdr_sch_trade_deal_ord_sku_qtty_sz_trade_deal_snapshot": "jd_sku_qtty",      # 成交件数
    "jdr_sch_user_deal_ord_user_cnt_sz_user_deal_snapshot": "jd_buyer_cnt",       # 成交用户数
    "jdr_sch_traffic_brow_sku__page_cnt_traffic_plat_item_di_sz_bsg": "jd_item_pv",  # 商品浏览量
    "jdr_sch_traffic_enter_shop__browse_page_cnt_shop_last_src": "jd_shop_pv",    # 店铺浏览量
    "jdr_sch_traffic_exposure_event_dis_qtty_sz_exposure_base": "jd_exposure",    # 曝光量
    "fo_jdr_sch_shop_deal_rate": "jd_cvr",                                        # 成交转化率(0-1)
}


def rows_from_trend(body_json):
    out = []
    data = (body_json.get("body") or {}).get("data")
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        dt = item.get("dt")
        if not dt:
            continue
        for code, mname in INDICATOR_MAP.items():
            v = item.get(code)
            if isinstance(v, (int, float)):
                out.append((dt[:10], mname, float(v)))
    return out


async def main():
    rows = []
    parsed_trend = 0
    for line in open(JSONL, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "getCoreTrend.ajax" not in r["url"]:
            continue
        try:
            body = json.loads(r["body"])
        except Exception:
            print("WARN getCoreTrend body 截断/解析失败，跳过一条")
            continue
        parsed_trend += 1
        rows += rows_from_trend(body)

    dedup = {}
    for dt, m, v in rows:
        dedup[(dt, m)] = v
    print(f"解析 getCoreTrend 响应 {parsed_trend} 条 → {len(dedup)} 个 date×metric")

    conn = await asyncpg.connect(DB)
    n = 0
    for (dt, m), v in sorted(dedup.items()):
        await conn.execute(
            """INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, platform, source_runbook)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (sku_id, date, metric_name, platform)
               DO UPDATE SET value=EXCLUDED.value, source_runbook=EXCLUDED.source_runbook, created_at=now()""",
            SHOP, datetime.date.fromisoformat(dt), m, float(v), PLATFORM, SRC)
        n += 1
    await conn.close()
    print(f"UPSERTED {n} 行 mvp_daily_metric(platform='jd')")


asyncio.run(main())
