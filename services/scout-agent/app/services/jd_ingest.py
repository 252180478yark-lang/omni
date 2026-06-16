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

# 指标码 → mvp_daily_metric.metric_name（实测响应值确认口径；jd_ 前缀=京东口径，gmv≠抖音 gmv_paid）
INDICATOR_MAP = {
    "jdr_sch_trade_deal_ord_ord_amt_sz_trade_deal_snapshot": "jd_gmv",
    "jdr_sch_trade_deal_ord_ord_qtty_sz_trade_deal_snapshot": "jd_order_cnt",
    "jdr_sch_trade_deal_ord_sku_qtty_sz_trade_deal_snapshot": "jd_sku_qtty",
    "jdr_sch_user_deal_ord_user_cnt_sz_user_deal_snapshot": "jd_buyer_cnt",
    "jdr_sch_traffic_brow_sku__page_cnt_traffic_plat_item_di_sz_bsg": "jd_item_pv",
    "jdr_sch_traffic_enter_shop__browse_page_cnt_shop_last_src": "jd_shop_pv",
    "jdr_sch_traffic_exposure_event_dis_qtty_sz_exposure_base": "jd_exposure",
    "fo_jdr_sch_shop_deal_rate": "jd_cvr",
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


async def _capture() -> tuple[list[dict], bool]:
    """返回 (getCoreTrend 响应体 list, jdsz_loaded)。fail-open。"""
    from playwright.async_api import async_playwright

    trend_bodies: list[dict] = []
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

            pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
            try:
                await pg.goto("https://jdsz.jd.com/", wait_until="domcontentloaded", timeout=45000)
                jdsz_loaded = "login" not in (pg.url or "")
            except Exception as exc:
                log.warning("jd_ingest: jdsz 加载失败（疑 session 失效）: %s", str(exc)[:120])
                return [], False
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
    return trend_bodies, jdsz_loaded


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
        trend_bodies, jdsz_loaded = await _capture()
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
    finally:
        await conn.close()
    days = sorted({dt for dt, _ in rows})
    log.info("jd_ingest: upserted %d rows, %d days (%s~%s)", n, len(days), days[0], days[-1])
    return {"ok": True, "rows": n, "days": len(days), "date_range": [days[0], days[-1]],
            "metrics": sorted({m for _, m in rows})}
