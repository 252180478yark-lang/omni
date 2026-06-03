"""落库桥抽取器（MVP，~29 标量，含时间维度）。
干跑：python _ingest_kpi.py        → 读 _kpi_raw，抽取，打验证表（不落库）
落库：python _ingest_kpi.py --write → 抽取 + upsert mvp_daily_metric（容器内跑，有 DB）

时间维度：序列端点(kind='series')落整段历史(每天一行)；snapshot 端点落今日一行(趋势靠 cron 累积)。
口径：罗盘金额「分」→÷100 元；rate/sov/占比 存原始 0-1；全店 sku_id='_SHOP_'；platform='douyin'。
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "catalog" / "_kpi_raw"
BRAND = "11835330"
TODAY = date.today()


def F(lst, **kw):
    for x in (lst or []):
        if all(str(x.get(k)) == str(v) for k, v in kw.items()):
            return x
    return None


def _int(v):
    return int(float(str(v))) if v not in (None, "") else None


def _float(v):
    return float(str(v)) if v not in (None, "") else None


def _yuan(v):
    f = _float(v)
    return round(f / 100, 2) if f is not None else None


def mmdd(s):
    mm, dd = s.split("/")
    d = date(TODAY.year, int(mm), int(dd))
    if d > TODAY:
        d = date(TODAY.year - 1, int(mm), int(dd))
    return d.isoformat()


# 序列抽取器（返回 [(date_iso, raw_value), ...]）
def s_gmv(d):
    arr = d["data"]["module_data"]["trade_core_index_trend"]["unify_chart_info"]["axis_data"]["income_amt"]
    return [(mmdd(p["x_str"]), p["y"]) for p in arr]


def s_trend(field):
    return lambda d: [(p["date"], p[field]) for p in d["data"]["trend_points"]]


def s_sov(d):
    r = F(d["data"]["data"], brandId=BRAND, queryIntent=2)
    return [(p["date"], p["value"]) for p in (r.get("dailyData") or [])]


# (raw文件, metric, 中文, kind, fn, transform)  kind: 'series'|'snap'
CFG = [
    ("compass__core_trend_v3", "gmv_paid", "成交金额(支付)", "series", s_gmv, _yuan),
    ("compass__flow_source_funnel", "buyer_count", "成交人数", "snap",
     lambda d: d["data"][0]["cell_info"]["pay_ucnt"]["pay_ucnt_index_value"]["index_values"]["value"]["value"], _int),
    ("compass__flow_source_funnel", "product_click_uv", "商品点击人数", "snap",
     lambda d: d["data"][0]["cell_info"]["product_click_ucnt"]["product_click_ucnt_index_value"]["index_values"]["value"]["value"], _int),
    ("compass__flow_source_funnel", "product_show_uv", "商品曝光人数", "snap",
     lambda d: d["data"][0]["cell_info"]["product_show_ucnt"]["product_show_ucnt_index_value"]["index_values"]["value"]["value"], _int),
    ("compass__flow_source_funnel", "pay_conversion", "曝光支付转化率", "snap",
     lambda d: d["data"][0]["cell_info"]["product_show_pay_converse_uv_rate"]["product_show_pay_converse_uv_rate_index_value"]["index_values"]["value"]["value"], _float),
    ("doudian__getoverviewbyversion", "experience_score", "店铺体验分", "snap",
     lambda d: d["data"]["experience_score"]["value"], _int),
    ("doudian__getoverviewbyversion", "experience_goods_score", "商品体验分", "snap",
     lambda d: d["data"]["goods_score"]["value"], _int),
    ("doudian__getoverviewbyversion", "experience_logistics_score", "物流体验分", "snap",
     lambda d: d["data"]["logistics_score"]["value"], _int),
    ("doudian__getoverviewbyversion", "experience_service_score", "服务体验分", "snap",
     lambda d: d["data"]["service_score"]["value"], _int),
    ("doudian__doudian_shop_overview", "gmv_paid_card_7d", "近7天商品卡成交额", "snap",
     lambda d: d["data"]["index_card"]["data"][0]["cell_info"]["pay_amt"]["pay_amt_index_values"]["index_values"]["value"]["value"], _float),
    ("doudian__doudian_shop_overview", "pay_conversion_card_7d", "近7天商品卡转化率", "snap",
     lambda d: d["data"]["index_card"]["data"][0]["cell_info"]["pay_converse_rate_ucnt"]["pay_converse_rate_ucnt_index_values"]["index_values"]["value"]["value"], _float),
    ("doudian__doudian_shop_overview", "uv_card_show_7d", "近7天商品卡曝光人数", "snap",
     lambda d: d["data"]["index_card"]["data"][0]["cell_info"]["product_show_ucnt"]["product_show_ucnt_index_values"]["index_values"]["value"]["value"], _int),
    ("yuntu__getaudienceassetstructure", "asset_5a_a1", "A1认知人群资产", "snap",
     lambda d: F(d["data"]["structure_list"], name="a1")["value"], _int),
    ("yuntu__getaudienceassetstructure", "asset_5a_a2", "A2种草人群资产", "snap",
     lambda d: F(d["data"]["structure_list"], name="a2")["value"], _int),
    ("yuntu__getaudienceassetstructure", "asset_5a_a3", "A3互动人群资产", "snap",
     lambda d: F(d["data"]["structure_list"], name="a3")["value"], _int),
    ("yuntu__getaudienceassetstructure", "asset_5a_a4", "A4购买人群资产", "snap",
     lambda d: F(d["data"]["structure_list"], name="a4")["value"], _int),
    ("yuntu__getaudienceassetstructure", "asset_5a_a5", "A5拥护人群资产", "snap",
     lambda d: F(d["data"]["structure_list"], name="a5")["value"], _int),
    ("yuntu__get_audience_asset_trend", "asset_5a_total", "5A总人群资产", "series", s_trend("cover_num"), _int),
    ("yuntu__get_audience_asset_trend", "industry_rank_5a", "5A资产行业排名", "series", s_trend("rank"), _int),
    ("yuntu__get_audience_asset_trend", "asset_5a_day_added", "5A当日新增", "series", s_trend("day_added"), _int),
    ("yuntu__get_audience_asset_trend", "asset_5a_day_loss", "5A当日流失", "series", s_trend("day_loss"), _int),
    ("yuntu__audienceflowanalysisv2", "asset_5a_a3_cover", "A3当前覆盖人数", "snap",
     lambda d: d["data"]["num"], _int),
    ("yuntu__audienceflowanalysisv2", "asset_5a_a3_inflow_rate", "A3净流入转化率", "snap",
     lambda d: d["data"]["rate"], _float),
    ("yuntu__industryrank", "industry_rank", "行业品牌总排名", "snap",
     lambda d: F(d["data"], id=BRAND)["rank"], _int),
    ("yuntu__industryrank", "industry_rank_diff", "行业排名环比变动", "snap",
     lambda d: F(d["data"], id=BRAND)["rankDiff"], _int),
    ("yuntu__corebrand", "search_sov", "品牌搜索声量份额SOV", "series", s_sov, _float),
    ("yuntu__corebrand", "search_brand_rank", "品牌搜索声量排名", "snap",
     lambda d: F(d["data"]["data"], brandId=BRAND, queryIntent=2)["rnk"], _int),
    ("yuntu__productstructure", "gmv_share_best_selling", "爆款GMV占比", "snap",
     lambda d: F(d["data"], brandType="BRAND", dimension="BEST_SELLING_PRODUCT")["value"], _float),
    ("yuntu__productstructure", "gmv_share_normal", "常规品GMV占比", "snap",
     lambda d: F(d["data"], brandType="BRAND", dimension="NORMAL_PRODUCT")["value"], _float),
]


def extract():
    """返回 rows: [{metric, cn, kind, date, value}], + meta per metric."""
    cache = {}
    rows = []
    summary = []
    for fname, metric, cn, kind, fn, tr in CFG:
        if fname not in cache:
            p = RAW / f"{fname}.json"
            cache[fname] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        d = cache[fname]
        try:
            if d is None:
                raise ValueError("raw缺失")
            if kind == "series":
                pts = [(dt, tr(v)) for dt, v in fn(d)]
                for dt, v in pts:
                    rows.append({"metric": metric, "cn": cn, "date": dt, "value": v})
                summary.append({"metric": metric, "cn": cn, "kind": "series", "n": len(pts),
                                "first": pts[0] if pts else None, "last": pts[-1] if pts else None, "err": None})
            else:
                v = tr(fn(d))
                rows.append({"metric": metric, "cn": cn, "date": TODAY.isoformat(), "value": v})
                summary.append({"metric": metric, "cn": cn, "kind": "snap", "n": 1,
                                "first": None, "last": (TODAY.isoformat(), v), "err": None})
        except Exception as exc:
            summary.append({"metric": metric, "cn": cn, "kind": kind, "n": 0,
                            "first": None, "last": None, "err": f"{type(exc).__name__}: {exc}"})
    return rows, summary


def main():
    rows, summary = extract()
    print(f"{'指标':<26}{'中文':<20}{'类型':<8}{'天数':<6}{'最新值':<14}{'最早':<26}状态")
    print("-" * 110)
    ok = 0
    for s in summary:
        if not s["err"]:
            ok += 1
        last = f"{s['last'][0]}={s['last'][1]}" if s["last"] else "-"
        first = f"{s['first'][0]}={s['first'][1]}" if s["first"] else ""
        st = "OK" if not s["err"] else ("ERR " + s["err"])
        print(f"{s['metric']:<26}{(s['cn'] or '')[:18]:<20}{s['kind']:<8}{s['n']:<6}{str(last)[:12]:<14}{first[:24]:<26}{st}")
    print("-" * 110)
    print(f"{ok}/{len(summary)} 指标抽取成功；共 {len(rows)} 行(含历史序列回补)")
    if "--write" in sys.argv:
        print("(--write 模式待接 DB upsert)")


if __name__ == "__main__":
    main()
