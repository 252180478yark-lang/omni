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
import re
from pathlib import Path

import asyncpg

from app.services.metric_ownership import submit_metric

log = logging.getLogger(__name__)

SESSION = Path(os.environ.get("SCOUT_SESSIONS_DIR", "/app/sessions")) / "jd" / "storage_state.json"
PLATFORM, SHOP, SRC = "jd", "_SHOP_", "jd_passive_capture"
NAV_KW = ("经营概况", "实时", "交易", "成交", "流量", "流量来源", "商品", "数据", "推广")
NAV_KW_JM = ("经营概况", "推广", "资金", "结算", "账单", "货款")  # 京麦工作台关键词

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


# ────── 切片5 扩展：体验分/推广/货款/流量来源 解析（纯函数 fail-open，仿 _rows_from_trend）──────
def _money(s):  # 剥 ¥ 逗号 → float；'-'/''/None → None
    if s in (None, "-", ""):
        return None
    try:
        return float(re.sub(r"[¥,\s]", "", str(s)))
    except (TypeError, ValueError):
        return None


def _pct(s):  # '0.00%' → 0-1；裸数字直接 float
    if s in (None, "-", ""):
        return None
    s = str(s)
    if "%" in s:
        try:
            return float(s.rstrip("%")) / 100
        except ValueError:
            return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _f(v):  # 容字符串/数字 → float
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# A. 流量来源（getFlowSrcTop 当日快照 date×渠道）
_FS_VISITOR = "jdr_sch_traffic_brow_sku_cnt_jd_unified_attribution_sz"
_FS_GMV = "jdr_sch_traffic_intr_ord_ord_amt_jd_unified_attribution_trade_deal_snapshot_sz"
_FS_FLOW_SHARE = _FS_VISITOR + "/jdr_sch_traffic_brow_sku__page_cnt_traffic_plat_item_di_sz_bsg##customProportion"
_FS_GMV_SHARE = _FS_GMV + "/jdr_sch_trade_deal_ord_ord_amt_sz_trade_deal_snapshot##customProportion"


def _flow_sources(body_json) -> list[dict]:
    out = []
    data = body_json.get("data")
    if not isinstance(data, list):
        data = (body_json.get("body") or {}).get("data")
    if not isinstance(data, list):
        return out
    for it in data:
        if not isinstance(it, dict):
            continue
        code = it.get("jdr_sch_traffic_cha_last_field_src_rmad_sz_2")
        if not code:
            continue
        out.append({
            "channel_code": str(code), "channel_name": it.get("name"),
            "parent_name": it.get("parentName"), "rank": it.get("rank"),
            "visitor_cnt": _f(it.get(_FS_VISITOR)),
            "visitor_cnt_pre": _f(it.get(_FS_VISITOR + "##compareValue")),
            "visitor_mom": _f(it.get(_FS_VISITOR + "##compare")),
            "intro_gmv": _f(it.get(_FS_GMV)),
            "intro_gmv_pre": _f(it.get(_FS_GMV + "##compareValue")),
            "intro_gmv_mom": _f(it.get(_FS_GMV + "##compare")),
            "flow_share": _f(it.get(_FS_FLOW_SHARE)),
            "gmv_share": _f(it.get(_FS_GMV_SHARE)),
        })
    return out


# B. 体验分（VaneStars data dict / getShopStars body.data[0]）
_STARS_NUM = {
    "customServiceConsultScore": "jd_exp_consult_score",
    "afterServiceScore": "jd_exp_afterservice_score",
    "logisticsLvyueScore": "jd_exp_logistics_score",
    "userEvaluateScore": "jd_exp_evaluate_score",
    "scoreRankRate": "jd_exp_score_rank_rate",
    "customServiceConsultScoreRate": "jd_exp_consult_rank_rate",
    "afterServiceScoreRate": "jd_exp_afterservice_rank_rate",
    "logisticsLvyueScoreRate": "jd_exp_logistics_rank_rate",
    "userEvaluateScoreRate": "jd_exp_evaluate_rank_rate",
    "scoreRankRateGrade": "jd_exp_score_grade",
    "validOrderNum": "jd_exp_valid_order_num",
}


def _shop_stars(body_json) -> list[tuple[str, float]]:
    d = body_json.get("data")
    if isinstance(d, dict):
        rec = d
    elif isinstance(d, list) and d:
        rec = d[0]
    else:
        inner = (body_json.get("body") or {}).get("data")
        rec = inner[0] if isinstance(inner, list) and inner else (inner if isinstance(inner, dict) else None)
    if not isinstance(rec, dict):
        return []
    out = []
    for k, m in _STARS_NUM.items():
        v = _f(rec.get(k))
        if v is not None:
            out.append((m, v))
    rg = _f(rec.get("isRedGreenPass"))
    if rg is not None:
        out.append(("jd_exp_redgreen_pass", rg))
    return out


# C. 推广（findPromoteData 今日快照 + getAdSummaryAndTrend 日序列）
_PROMOTE_MAP = {
    ("non_site_marketing", "cost"): ("jd_ad_cost", _money),
    ("non_site_marketing", "totalOrderSum"): ("jd_ad_order_sum", _money),
    ("non_site_marketing", "orderROI"): ("jd_ad_roi", _f),
    ("non_site_marketing", "impressions"): ("jd_ad_impressions", _f),
    ("non_site_marketing", "clicks"): ("jd_ad_clicks", _f),
    ("non_site_marketing", "ctr"): ("jd_ad_ctr", _pct),
    ("non_site_marketing", "cpm"): ("jd_ad_cpm", _money),
    ("non_site_marketing", "cpc"): ("jd_ad_cpc", _money),
}


def _promote_data(body_json, today) -> list[tuple[str, str, float]]:
    out = []
    data = body_json.get("data") or {}
    for mod in data.get("modules", []):
        mc = mod.get("moduleCode")
        for ind in mod.get("indicators", []):
            key = (mc, ind.get("jmirCode"))
            if key in _PROMOTE_MAP:
                mname, parse = _PROMOTE_MAP[key]
                v = parse(ind.get("value"))
                if v is not None:
                    out.append((today, mname, float(v)))
    return out


_AD_TREND_MAP = {"Cost": "jd_ad_cost", "TotalOrderSum": "jd_ad_order_sum", "OrderROI": "jd_ad_roi",
                 "Impressions": "jd_ad_impressions", "Clicks": "jd_ad_clicks", "CTR": "jd_ad_ctr",
                 "CPM": "jd_ad_cpm", "CPC": "jd_ad_cpc", "TotalOrderCnt": "jd_ad_order_cnt"}


def _ad_trend(body_json) -> list[tuple[str, str, float]]:
    out = []
    b = body_json.get("body") or body_json
    for row in ((b.get("data") or {}).get("wholeSiteTrend") or []):
        dt = row.get("dt")
        if not dt:
            continue
        for k, mname in _AD_TREND_MAP.items():
            v = row.get(k)
            if isinstance(v, (int, float)):
                out.append((dt[:10], mname, float(v)))
    return out


# D. 货款结算（dailyBill content[]）
def _daily_bill(body_json) -> list[dict]:
    data = body_json.get("data") or {}
    out = []

    def _d(s):
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8])) if s and len(s) == 8 else None

    for c in (data.get("content") or []):
        sd = c.get("setDate")
        if not sd:
            continue
        out.append({"set_date": _d(sd), "acc_date": _d(c.get("accDate")),
                    "debit": c.get("debitAmt"), "credit": c.get("creditAmt"), "settle": c.get("actualSettle"),
                    "status": c.get("setStatus"), "bill_id": c.get("id"), "url": c.get("detailFilePath")})
    return out


def _empty_cap() -> dict:
    return {"trend": [], "product": [], "flow_src": [], "stars": [], "promote": [],
            "ad_trend": [], "bill": [], "summary": [], "jdsz_loaded": False}


async def _capture() -> dict:
    """返回 dict（trend/product/flow_src/stars/promote/ad_trend/bill/summary 各 list + jdsz_loaded）。fail-open。"""
    from playwright.async_api import async_playwright

    trend_bodies: list[dict] = []
    product_bodies: list[dict] = []
    flow_src_bodies: list[dict] = []
    stars_bodies: list[dict] = []
    promote_bodies: list[dict] = []
    ad_trend_bodies: list[dict] = []
    bill_bodies: list[dict] = []
    summary_bodies: list[dict] = []
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
                url = resp.url
                if "szgateway.jd.com/api/lowcode/" not in url and "sff.jd.com/api" not in url:
                    return
                try:
                    j = json.loads(await resp.text())
                except Exception:
                    return
                if (j.get("header") or {}).get("code") == -402:
                    saw_neg402 = True
                # 商智 szgateway lowcode
                if "getCoreTrend.ajax" in url:
                    trend_bodies.append(j)
                elif "productFlow/getProductTop.ajax" in url:
                    product_bodies.append(j)
                elif "productFlow/getFlowSrcTop.ajax" in url:
                    flow_src_bodies.append(j)
                elif "indexSummary/getShopStars.ajax" in url:
                    stars_bodies.append(j)
                elif "tradeSummary/summary/getSummary.ajax" in url or "flowSummary/getCoreSummary.ajax" in url:
                    summary_bodies.append(j)
                elif "flowSummary/ad/getAdSummaryAndTrend.ajax" in url:
                    ad_trend_bodies.append(j)
                # 京麦 sff dsm（推广/体验分/货款）
                elif "VaneStarsFacade" in url:
                    stars_bodies.append(j)
                elif "operationData.findPromoteData" in url:
                    promote_bodies.append(j)
                elif "dailyBillDsmProvider.queryDailyBillByPage" in url:
                    bill_bodies.append(j)

            pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
            try:
                await pg.goto("https://jdsz.jd.com/", wait_until="domcontentloaded", timeout=45000)
                jdsz_loaded = "login" not in (pg.url or "")
            except Exception as exc:
                log.warning("jd_ingest: jdsz 加载失败（疑 session 失效）: %s", str(exc)[:120])
                return _empty_cap()
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
            # 京麦工作台 + 财务账单（推广/体验分/货款 走 sff 网关，商智抓不到）
            try:
                await pg.goto("https://shop.jd.com/jdm/home", wait_until="domcontentloaded", timeout=45000)
                await pg.wait_for_timeout(7000)
                for kw in NAV_KW_JM:
                    try:
                        loc = pg.get_by_text(kw, exact=False).first
                        if await loc.count():
                            await loc.click(timeout=3000)
                            await pg.wait_for_timeout(3500)
                    except Exception:
                        continue
                await pg.goto("https://shop.jd.com/jdm/fin/billManage/DailyBill",
                              wait_until="domcontentloaded", timeout=45000)
                await pg.wait_for_timeout(7000)
            except Exception as exc:
                log.warning("jd_ingest: 京麦页加载失败(推广/货款可能缺): %s", str(exc)[:120])
        finally:
            await browser.close()
    if saw_neg402 and not trend_bodies:
        log.warning("jd_ingest: szgateway 返 -402（session 失效或风控）——需重登")
    return {"trend": trend_bodies, "product": product_bodies, "flow_src": flow_src_bodies,
            "stars": stars_bodies, "promote": promote_bodies, "ad_trend": ad_trend_bodies,
            "bill": bill_bodies, "summary": summary_bodies, "jdsz_loaded": jdsz_loaded}


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
        cap = await _capture()
    except Exception as exc:
        log.error("jd_ingest: capture 异常: %s", str(exc)[:200])
        return {"ok": False, "error": f"capture_error: {type(exc).__name__}"}

    trend_bodies = cap["trend"]
    product_bodies = cap["product"]
    jdsz_loaded = cap["jdsz_loaded"]
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
            result = await submit_metric(
                conn, sku_id=SHOP, metric_date=datetime.date.fromisoformat(dt),
                metric_name=m, value=v, platform=PLATFORM, source=SRC,
            )
            n += int(result["canonical_updated"])
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

        # ── 切片5：流量来源（date×渠道，今日快照）──
        fs_map = {}
        for body in cap["flow_src"]:
            for r in _flow_sources(body):
                fs_map[r["channel_code"]] = r
        fs_n = 0
        for code, r in fs_map.items():
            await conn.execute(
                """INSERT INTO mvp_jd_flow_source (date,channel_code,channel_name,parent_name,rank,
                     visitor_cnt,visitor_cnt_pre,visitor_mom,intro_gmv,intro_gmv_pre,intro_gmv_mom,
                     flow_share,gmv_share,source_runbook)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                   ON CONFLICT (date,channel_code) DO UPDATE SET
                     channel_name=EXCLUDED.channel_name, parent_name=EXCLUDED.parent_name,
                     rank=EXCLUDED.rank, visitor_cnt=EXCLUDED.visitor_cnt,
                     visitor_cnt_pre=EXCLUDED.visitor_cnt_pre, visitor_mom=EXCLUDED.visitor_mom,
                     intro_gmv=EXCLUDED.intro_gmv, intro_gmv_pre=EXCLUDED.intro_gmv_pre,
                     intro_gmv_mom=EXCLUDED.intro_gmv_mom, flow_share=EXCLUDED.flow_share,
                     gmv_share=EXCLUDED.gmv_share, created_at=now()""",
                today, code, r["channel_name"], r["parent_name"],
                int(r["rank"]) if isinstance(r["rank"], (int, float)) else None,
                r["visitor_cnt"], r["visitor_cnt_pre"], r["visitor_mom"],
                r["intro_gmv"], r["intro_gmv_pre"], r["intro_gmv_mom"],
                r["flow_share"], r["gmv_share"], SRC)
            fs_n += 1

        # ── 体验分（_SHOP_ 当天，VaneStars/getShopStars，评分类 snap）──
        exp_rows = []
        for body in cap["stars"]:
            rs = _shop_stars(body)
            if rs:
                exp_rows = rs
        exp_n = 0
        for m, v in exp_rows:
            result = await submit_metric(
                conn, sku_id=SHOP, metric_date=today, metric_name=m,
                value=v, platform=PLATFORM, source=SRC,
            )
            exp_n += int(result["canonical_updated"])

        # ── 推广（ad_trend 日序列优先，findPromoteData 快照补今日；停投显式写0=确认未投）──
        ad_map = {}
        for body in cap["ad_trend"]:
            for dt, m, v in _ad_trend(body):
                ad_map[(dt, m)] = v
        for body in cap["promote"]:
            for dt, m, v in _promote_data(body, today.isoformat()):
                ad_map.setdefault((dt, m), v)
        ad_n = 0
        for (dt, m), v in ad_map.items():
            result = await submit_metric(
                conn, sku_id=SHOP, metric_date=datetime.date.fromisoformat(dt),
                metric_name=m, value=v, platform=PLATFORM, source=SRC,
            )
            ad_n += int(result["canonical_updated"])

        # ── 货款结算（宽表 by set_date + 镜像3指标进长表，源 jd_bill_capture）──
        bill_seen = {}
        for body in cap["bill"]:
            for r in _daily_bill(body):
                if r["set_date"]:
                    bill_seen[r["set_date"]] = r
        bill_n = 0
        for sd, r in bill_seen.items():
            await conn.execute(
                """INSERT INTO mvp_jd_daily_bill (set_date,acc_date,debit_amt,credit_amt,actual_settle,
                     set_status,bill_id,detail_file_url,source_runbook)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (set_date) DO UPDATE SET
                     acc_date=EXCLUDED.acc_date, debit_amt=EXCLUDED.debit_amt,
                     credit_amt=EXCLUDED.credit_amt, actual_settle=EXCLUDED.actual_settle,
                     set_status=EXCLUDED.set_status, bill_id=EXCLUDED.bill_id,
                     detail_file_url=EXCLUDED.detail_file_url, created_at=now()""",
                sd, r["acc_date"], _num(r["debit"]), _num(r["credit"]), _num(r["settle"]),
                int(r["status"]) if isinstance(r["status"], (int, float)) else None,
                int(r["bill_id"]) if isinstance(r["bill_id"], (int, float)) else None, r["url"], "jd_bill_capture")
            for mn, val in (("jd_bill_debit", r["debit"]), ("jd_bill_credit", r["credit"]),
                            ("jd_bill_settle", r["settle"])):
                bv = _num(val)
                if bv is None:
                    continue
                await submit_metric(
                    conn, sku_id=SHOP, metric_date=sd, metric_name=mn,
                    value=bv, platform=PLATFORM, source="jd_bill_capture",
                )
            bill_n += 1
    finally:
        await conn.close()
    days = sorted({dt for dt, _ in rows})
    log.info("jd_ingest: upserted %d 店级 rows (%d days) + %d 商品 rows", n, len(days), pn)
    return {"ok": True, "rows": n, "days": len(days), "date_range": [days[0], days[-1]],
            "metrics": sorted({m for _, m in rows}), "product_rows": pn,
            "flow_rows": fs_n, "exp_rows": exp_n, "ad_rows": ad_n, "bill_rows": bill_n}
