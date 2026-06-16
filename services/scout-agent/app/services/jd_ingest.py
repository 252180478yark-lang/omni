"""京东 passive 抓取日级落库（切片2 产线化）。

链路：headed(xvfb)+session 加载商智 jdsz → SPA 自己签 user-mnp 发 szgateway 请求 →
page.on(response) 抓 → 抽 getCoreTrend 日级核心指标 → upsert mvp_daily_metric(platform='jd',_SHOP_)。
**不 forge 签名、不抓取对抗**（让 SPA 自己签，我只读）。getCoreTrend 返最近 ~7 天，每跑刷新近 7 天（幂等自愈）。

session 失效（无 storage_state / jdsz 加载不到 / 响应全 -402 / 抽不到指标）→ fail-open 返
needs_relogin + log.warning（老板重扫 `_jd_login_capture_host.py` 即恢复，像抖音罗盘 cookie 浮动）。

触发：scout scheduler 日级（scheduler.py）+ REST `POST /api/v1/scout/jd/ingest`（按需/测试）。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

SESSION = Path(os.environ.get("SCOUT_SESSIONS_DIR", "/app/sessions")) / "jd" / "storage_state.json"
PLATFORM, SHOP, SRC = "jd", "_SHOP_", "jd_passive_capture"
NAV_KW = ("经营概况", "实时", "交易", "成交", "流量", "商品", "数据")

# 指标码 → mvp_daily_metric.metric_name（口径=实测响应值 + 商智概况 DOM 中文名交叉确认；
# jd_ 前缀=京东口径，gmv≠抖音 gmv_paid。访客/浏览口径：cnt=访客数(UV,小)，qtty=浏览量(PV,大)；
# exposure dis_qtty=曝光人数(UV)，qtty=曝光次数(PV)——按访客<浏览 + DOM「商品访客数」确认）。
INDICATOR_MAP = {
    # 成交
    "jdr_sch_trade_deal_ord_ord_amt_sz_trade_deal_snapshot": "jd_gmv",                 # 成交金额
    "jdr_sch_trade_deal_ord_ord_qtty_sz_trade_deal_snapshot": "jd_order_cnt",          # 成交单量
    "jdr_sch_user_deal_ord_user_cnt_sz_user_deal_snapshot": "jd_buyer_cnt",            # 成交客户数
    "jdr_sch_trade_deal_ord_sku_qtty_sz_trade_deal_snapshot": "jd_sku_qtty",           # 成交商品件数
    "fo_jdr_sch_trade_deal_ord_amt_user_sz_trade_deal_snapshot": "jd_per_customer_price",  # 客单价(=gmv/buyer 实测对上)
    # 流量·访客数(UV，page_cnt/dis)
    "jdr_sch_traffic_brow_sku__page_cnt_traffic_plat_item_di_sz_bsg": "jd_item_uv",    # 商品访客数
    "jdr_sch_traffic_enter_shop__browse_page_cnt_shop_last_src": "jd_shop_uv",         # 店铺访客数
    "jdr_sch_traffic_exposure_event_dis_qtty_sz_exposure_base": "jd_exposure_uv",      # 曝光人数
    # 流量·浏览量(PV，page_qtty/qtty)
    "jdr_sch_traffic_brow_sku__page_qtty_traffic_plat_item_di_sz_bsg": "jd_item_pv",   # 商品浏览量
    "jdr_sch_traffic_enter_shop__browse_page_qtty_shop_last_src": "jd_shop_pv",        # 店铺浏览量
    "jdr_sch_traffic_exposure_event_qtty_sz_exposure_base": "jd_exposure_pv",          # 曝光次数
    # 互动/效率
    "fo_jdr_sch_uv_value_sz": "jd_uv_value",                                           # UV价值
    "jdr_sch_sku_add_cart_sku_user_qtty_product_user_cart_add_minus_sz_bsg_shoppingcart@increase": "jd_add_cart_user",  # 加购人数(净增)
    "jdr_sch_sku_add_cart_sku_sku_amt_shopping_cart": "jd_add_cart_amt",               # 加购金额
    "fo_jdr_sch_add_cart_user_uv_rate@increase": "jd_add_cart_rate",                   # 加购率
    "fo_jdr_sch_fo_flow_item_detail_view_pv_per_uv": "jd_item_pv_per_uv",              # 商详人均浏览次数
    "fo_jdr_sch_fo_fsd_flow_item_detail_view_avg_stay_duration_per": "jd_item_stay_sec",  # 商详平均停留(秒)
    "fo_jdr_sch_traffic_enter_shop__browse_page_avg_duration_shop_last_src": "jd_shop_stay_sec",  # 店铺平均停留(秒)
}


def _rows_from_trend(body_json) -> list[tuple[str, str, float]]:
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


async def _capture() -> tuple[list[dict], list[dict], bool]:
    """返回 (getCoreTrend 响应体 list, getProductTop 响应体 list, jdsz_loaded)。fail-open。"""
    from playwright.async_api import async_playwright

    trend_bodies: list[dict] = []
    product_bodies: list[dict] = []
    saw_neg402 = False
    jdsz_loaded = False
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx = await browser.new_context(storage_state=str(SESSION), locale="zh-CN",
                                            viewport={"width": 1440, "height": 900})
            pg = await ctx.new_page()

            async def on_resp(resp):
                nonlocal saw_neg402
                if "szgateway.jd.com/api/lowcode/" not in resp.url:
                    return
                try:
                    body = await resp.text()
                    j = json.loads(body)
                except Exception:
                    return
                if (j.get("header") or {}).get("code") == -402:
                    saw_neg402 = True
                if "getCoreTrend.ajax" in resp.url:
                    trend_bodies.append(j)
                elif "productFlow/getProductTop.ajax" in resp.url:
                    product_bodies.append(j)

            pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
            try:
                await pg.goto("https://jdsz.jd.com/", wait_until="domcontentloaded", timeout=45000)
                jdsz_loaded = "login" not in (pg.url or "")
            except Exception as exc:
                log.warning("jd_ingest: jdsz 加载失败（疑 session 失效）: %s", str(exc)[:120])
                return [], [], False
            await pg.wait_for_timeout(8000)
            for kw in NAV_KW:
                try:
                    loc = pg.get_by_text(kw, exact=False).first
                    if await loc.count():
                        await loc.click(timeout=3000)
                        await pg.wait_for_timeout(5000)
                except Exception:
                    continue
            await pg.wait_for_timeout(3000)
        finally:
            await browser.close()
    if saw_neg402 and not trend_bodies:
        log.warning("jd_ingest: szgateway 返 -402（session 失效或风控）——需重登")
    return trend_bodies, product_bodies, jdsz_loaded


# 商品维度（切片4）：getProductTop 每商品 引入成交额 + 商品访客数 + rank + 名 + spu
_PROD_SALES = "jdr_sch_traffic_intr_ord_ord_amt_jd_unified_attribution_trade_deal_snapshot_sz"
_PROD_VISITOR = "jdr_sch_traffic_brow_sku_cnt_jd_unified_attribution_sz"


def _products_from_top(body_json) -> list[dict]:
    out = []
    data = (body_json.get("body") or {}).get("data")
    items = data.get("list") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        spu = it.get("spu_id") or it.get("spuId")
        if not spu:
            continue
        out.append({
            "spu_id": str(spu),
            "product_name": it.get("name"),
            "sales_amt": it.get(_PROD_SALES),
            "visitor_cnt": it.get(_PROD_VISITOR),
            "rank": it.get("rank"),
            "pro_url": it.get("pro_url"),
        })
    return out


async def run_jd_daily_ingest() -> dict:
    """日级京东落库主入口。fail-open，永不抛。"""
    if not SESSION.exists():
        log.warning("jd_ingest: 无 session（%s）——需老板扫码登录 _jd_login_capture_host.py", SESSION)
        return {"ok": False, "error": "no_session"}
    db = os.environ.get("DATABASE_URL")
    if not db:
        log.error("jd_ingest: 无 DATABASE_URL")
        return {"ok": False, "error": "no_db"}
    try:
        trend_bodies, product_bodies, jdsz_loaded = await _capture()
    except Exception as exc:
        log.error("jd_ingest: capture 异常: %s", str(exc)[:200])
        return {"ok": False, "error": f"capture_error: {type(exc).__name__}"}

    if not jdsz_loaded:
        return {"ok": False, "error": "session_expired", "hint": "重跑 _jd_login_capture_host.py 扫码"}

    rows: dict[tuple[str, str], float] = {}
    for body in trend_bodies:
        for dt, m, v in _rows_from_trend(body):
            rows[(dt, m)] = v
    if not rows:
        log.warning("jd_ingest: 抓到页面但没抽到指标（疑 session 失效/页面结构变）")
        return {"ok": False, "error": "no_metrics", "trend_responses": len(trend_bodies)}

    # 商品维度（切片4）：getProductTop → 当日商品榜，按 spu 去重
    prod_map: dict[str, dict] = {}
    for body in product_bodies:
        for p in _products_from_top(body):
            prod_map[p["spu_id"]] = p

    def _num(v):
        return float(v) if isinstance(v, (int, float)) else None

    conn = await asyncpg.connect(db)
    try:
        n = 0
        for (dt, m), v in rows.items():
            await conn.execute(
                """INSERT INTO mvp_daily_metric (sku_id, date, metric_name, value, platform, source_runbook)
                   VALUES ($1,$2,$3,$4,$5,$6)
                   ON CONFLICT (sku_id, date, metric_name, platform)
                   DO UPDATE SET value=EXCLUDED.value, source_runbook=EXCLUDED.source_runbook, created_at=now()""",
                SHOP, datetime.date.fromisoformat(dt), m, v, PLATFORM, SRC)
            n += 1
        today = datetime.date.today()
        pn = 0
        for spu, p in prod_map.items():
            await conn.execute(
                """INSERT INTO mvp_jd_product_daily
                       (date, spu_id, product_name, sales_amt, visitor_cnt, rank, pro_url, source_runbook)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT (date, spu_id) DO UPDATE SET
                       product_name=EXCLUDED.product_name, sales_amt=EXCLUDED.sales_amt,
                       visitor_cnt=EXCLUDED.visitor_cnt, rank=EXCLUDED.rank,
                       pro_url=EXCLUDED.pro_url, created_at=now()""",
                today, spu, p["product_name"], _num(p["sales_amt"]), _num(p["visitor_cnt"]),
                int(p["rank"]) if isinstance(p["rank"], (int, float)) else None, p["pro_url"], SRC)
            pn += 1
    finally:
        await conn.close()
    days = sorted({dt for dt, _ in rows})
    log.info("jd_ingest: upserted %d 店级 rows (%d days) + %d 商品 rows", n, len(days), pn)
    return {"ok": True, "rows": n, "days": len(days), "date_range": [days[0], days[-1]],
            "metrics": sorted({m for _, m in rows}), "product_rows": pn}
