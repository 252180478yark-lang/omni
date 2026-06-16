"""落库桥管线（2026-06-03）：实时取端点真返回 → 抽取器 → upsert mvp_daily_metric。

把 scripts/_ingest_kpi.py（干跑过的抽取器）升级成正式落库管线：
  1. fetch 实时：复用 LiveFetchExecutor.batch_raw 抓真返回（不读 _kpi_raw 缓存）
  2. 跑抽取器：series 落整段历史（每天一行）、snap 落今日一行
  3. upsert mvp_daily_metric(sku_id='_SHOP_', platform='douyin')，ON CONFLICT(sku_id,date,metric_name)
  4. 同行标杆：income_amt_benchmark(罗盘) + asset_trend 行业 cover_5/20/50/100 + count_average
     + doudian diagnose 分位 + 行业价格带占比 → upsert mvp_industry_benchmark(category_id='14')

抽取器分两批：
  - 地基 agent 的 29 个核心 metric（10 端点）
  - 覆盖扩展 agent 追加（2026-06-03）：再加 ~16 个明细 headline 标量 + 行业价格带 benchmark
    · compass.product_list 商品榜：榜首/合计 支付额(含退款两口径) + 在榜商品数
    · compass.list 达人榜：榜首/合计 GMV + 退款合计 + 种草人数合计 + 达人数（'¥xxx' 元字符串口径）
    · compass.trend_v3：直播 vs 商品卡 曝光人数 渠道分流日序列
    · compass.category_overview_price_band_distribution：5 个价格带行业成交占比 → benchmark
  明细整张表（每行 product_id / nickname / 波动归因文案 …）标 deferred，二期单独存维表
  （见 DEFERRED_DETAIL_TABLES），不进 mvp_daily_metric 标量。

口径（对齐 scripts/_ingest_kpi.py）：
  - 罗盘数值端点金额「分」→ ÷100 元（_yuan）；rate/sov/占比 存原始 0-1；rank 越小越好
  - compass.list 达人榜金额是 '¥xxx' 元字符串 → 去¥即元，**不再 ÷100**（_yuan_str）
  - 全店哨兵 sku_id='_SHOP_'；platform='douyin'（云图/罗盘/抖店同属抖音生态）

设计上 fail-open：单端点抓不到 / 单抽取器抛错都不挂整批，只少落几个指标 + 收进 errors。
"""
from __future__ import annotations

import logging
import re
from datetime import date as date_cls
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from app.database import get_pool
from app.services.live_fetch import LiveFetchExecutor

log = logging.getLogger(__name__)

BRAND = "11835330"
SHOP_SENTINEL = "_SHOP_"
PLATFORM = "douyin"
BENCHMARK_CATEGORY = "14"  # 调味品所在行业 category_id（云图/罗盘同一行业维度）

# 落库桥要抓的端点（catalog key）。一次浏览器会话连打。
# 地基 agent 的 10 个核心端点 + 覆盖扩展 agent 追加的 4 个明细 headline 端点（2026-06-03）。
INGEST_ENDPOINTS = [
    {"platform": "compass", "endpoint": "compass.core_trend_v3"},
    {"platform": "compass", "endpoint": "compass.flow_source_funnel"},
    {"platform": "doudian", "endpoint": "doudian.getoverviewbyversion"},
    {"platform": "doudian", "endpoint": "doudian.doudian_shop_overview"},
    {"platform": "yuntu", "endpoint": "yuntu.getaudienceassetstructure"},
    {"platform": "yuntu", "endpoint": "yuntu.get_audience_asset_trend"},
    {"platform": "yuntu", "endpoint": "yuntu.audienceflowanalysisv2"},
    {"platform": "yuntu", "endpoint": "yuntu.industryrank"},
    {"platform": "yuntu", "endpoint": "yuntu.corebrand"},
    {"platform": "yuntu", "endpoint": "yuntu.productstructure"},
    # ── 覆盖扩展（2026-06-03）：商品榜 / 达人榜 / 单品流量趋势 / 行业价格带 ──
    {"platform": "compass", "endpoint": "compass.product_list"},   # 商品维度大表（headline 标量 + per-SKU）
    {"platform": "compass", "endpoint": "compass.list"},           # 达人合作明细榜（headline + 维表）
    {"platform": "compass", "endpoint": "compass.trend_v3"},       # 直播/商品卡曝光日序列
    {"platform": "compass", "endpoint": "compass.category_overview_price_band_distribution"},  # 行业价格带（benchmark）
    # ── BI 2.0 维表端点（2026-06-03，dim_ingest 用）──
    {"platform": "compass", "endpoint": "compass.flow_data_v2"},                          # 流量来源渠道下钻
    {"platform": "compass", "endpoint": "compass.word_rank"},                             # 搜索词榜
    {"platform": "compass", "endpoint": "compass.category_overview_price_analysis_product"},  # 价格带竞品池
    {"platform": "yuntu", "endpoint": "yuntu.getaudienceassetbig8profile"},               # 八大人群×5A快照
    {"platform": "yuntu", "endpoint": "yuntu.getaudienceassetbig8trend"},                 # 八大人群30天趋势
    {"platform": "yuntu", "endpoint": "yuntu.bestsellingproduct"},                        # 行业畅销榜
    # ── BI 2.0 第1批：P0 诊断闭环 + 投放ROI（2026-06-03，全店标量/per-product → mvp_daily_metric）──
    {"platform": "compass", "endpoint": "compass.shop_rank"},              # 店铺行业排名
    {"platform": "compass", "endpoint": "compass.prof_exp_score"},        # 体验分+行业对比
    {"platform": "compass", "endpoint": "compass.flow_loss_card"},        # 转化流失定位
    {"platform": "compass", "endpoint": "compass.flow_overview_card"},    # 流量大盘核心
    {"platform": "compass", "endpoint": "compass.core_data"},             # 商品卡UV价值
    {"platform": "compass", "endpoint": "compass.overview_data"},         # 搜索四档对标
    {"platform": "compass", "endpoint": "compass.core_index_v3"},         # 投放ROI榜(per-product)
    {"platform": "doudian", "endpoint": "doudian.statistics"},            # 好评率/差评数
    {"platform": "doudian", "endpoint": "doudian.homepage"},              # 今日大盘
    # ── BI 2.0 第3批：品牌资产/自家流量/达人直播/竞品/罚单（2026-06-03）──
    {"platform": "yuntu", "endpoint": "yuntu.getoverview"},               # 品牌心智总览(标量)
    {"platform": "yuntu", "endpoint": "yuntu.getbrandnsrdetailstats"},    # NSR口碑序列(标量)
    {"platform": "compass", "endpoint": "compass.flow_source_detail_v2"}, # 自家5源排行(维表)
    {"platform": "compass", "endpoint": "compass.top_list"},              # Top直播间榜(维表)
    {"platform": "yuntu", "endpoint": "yuntu.bestsellingauthor"},         # 抖音号带货榜(维表)
    {"platform": "yuntu", "endpoint": "yuntu.listbrandtopkeyword"},       # 心智Top词(维表)
    {"platform": "compass", "endpoint": "compass.good_compete_product_list"},  # 同类竞品(维表)
    {"platform": "doudian", "endpoint": "doudian.get_ticket_list"},       # 平台罚单(维表)
    {"platform": "compass", "endpoint": "compass.shop_video_list"},       # 视频看后搜(维表)
    {"platform": "compass", "endpoint": "compass.realtime_word_overview_v2"},  # 搜索热词机会(维表)
    # ── migration 042: 服务健康(差评) + 流量入口 (维表) ──
    {"platform": "doudian", "endpoint": "doudian.getnegativecommenttagscount"},  # 差评原因标签榜
    {"platform": "doudian", "endpoint": "doudian.allcommenttagaggstat"},          # 差评聚合标签×类目
    {"platform": "yuntu", "endpoint": "yuntu.flowentrystructure"},                # 流量入口结构(货架vs内容)
]


# ─────────────────────────── 口径换算 + 取值小工具 ───────────────────────────

def _F(lst: Any, **kw) -> Any:
    for x in (lst or []):
        if all(str(x.get(k)) == str(v) for k, v in kw.items()):
            return x
    return None


def _int(v: Any) -> int | None:
    return int(float(str(v))) if v not in (None, "") else None


def _float(v: Any) -> float | None:
    return float(str(v)) if v not in (None, "") else None


def _yuan(v: Any) -> float | None:
    f = _float(v)
    return round(f / 100, 2) if f is not None else None


def _yuan_str(v: Any) -> float | None:
    """达人榜 list 端点金额是已格式化字符串 '¥890' / '¥199.4'（已是元，非分）→ 去¥号转 float。

    口径坑：compass 数值端点是「分」(需 _yuan ÷100)，但 compass.list 的 pay_gmv /
    refund_success_gmv 是带¥的元字符串，直接 strip ¥ 即元，**不能再 ÷100**。
    """
    if v in (None, ""):
        return None
    s = re.sub(r"[^\d.\-]", "", str(v))
    return float(s) if s not in ("", "-", ".") else None


def _mmdd(s: str, today: date_cls) -> str:
    """罗盘 x_str 'MM/DD' → ISO 日期（跨年回退去年）。"""
    mm, dd = s.split("/")
    d = date_cls(today.year, int(mm), int(dd))
    if d > today:
        d = date_cls(today.year - 1, int(mm), int(dd))
    return d.isoformat()


def _as_date(s: Any) -> date_cls | None:
    """ISO 日期字符串 → datetime.date（asyncpg DATE 列要 date 对象，不吃 str）。"""
    if isinstance(s, date_cls):
        return s
    if not s:
        return None
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def _as_num(v: Any) -> Decimal | None:
    """数值 → Decimal（asyncpg NUMERIC 列要 Decimal，float 会 DataError）。"""
    if v is None:
        return None
    return Decimal(str(v))


# ─────────────────────────── series 抽取器（返回 [(date_iso, raw)]）──────────

def _s_gmv(d: dict, today: date_cls) -> list[tuple[str, Any]]:
    arr = d["data"]["module_data"]["trade_core_index_trend"]["unify_chart_info"]["axis_data"]["income_amt"]
    return [(_mmdd(p["x_str"], today), p["y"]) for p in arr]


def _s_trend(field: str) -> Callable[[dict, date_cls], list[tuple[str, Any]]]:
    return lambda d, _today: [(p["date"], p[field]) for p in d["data"]["trend_points"]]


def _s_sov(d: dict, _today: date_cls) -> list[tuple[str, Any]]:
    r = _F(d["data"]["data"], brandId=BRAND, queryIntent=2)
    return [(p["date"], p["value"]) for p in ((r or {}).get("dailyData") or [])]


def _s_trend_v3(yk: str) -> Callable[[dict, date_cls], list[tuple[str, Any]]]:
    """compass.trend_v3 流量来源诊断日序列：value=[{x:'MM/DD', y:{<yk>:n,...}}]。

    x 是 'MM/DD' 字符串（同 core_trend_v3 口径，跨年回退去年）。yk 选哪条线
    （live_dh_product_show_uv 直播曝光人数 / product_card_dh_product_show_uv 商品卡曝光人数）。
    """
    return lambda d, today: [
        (_mmdd(p["x"], today), p["y"].get(yk))
        for p in d["data"]["trend"]["data_result"]["value"]
    ]


# ── 覆盖扩展 snap 抽取器（明细榜只抽 headline 标量；整张明细表 deferred 二期单存）──

def _sum_yuan_str(d: dict, path_rows, key: str) -> float | None:
    """compass.list 达人榜：对每行 strip¥ 求和（元）。fail-open 单行坏不挂整笔。"""
    total = 0.0
    for r in path_rows(d):
        v = _yuan_str(r.get(key))
        if v is not None:
            total += v
    return round(total, 2)


def _author_rows(d: dict) -> list:
    return d["data"]["data_result"] or []


def _pl_rows(d: dict) -> list:
    return d["data"] or []


def _pl_top_amt(d: dict, key: str) -> Any:
    """商品榜 headline：取 data[0]（已按 pay_amt 倒序）某金额字段 raw 值（分）。"""
    return d["data"][0]["cell_info"][key][f"{key}_index_values"]["index_values"]["value"]["value"]


def _pl_sum_amt(d: dict, key: str) -> float | None:
    """商品榜在榜商品某金额字段合计（分→元）。"""
    total = 0.0
    for r in d["data"]:
        v = _yuan(r["cell_info"][key][f"{key}_index_values"]["index_values"]["value"]["value"])
        if v is not None:
            total += v
    return round(total, 2)


def _price_band_rank1(d: dict) -> dict:
    """行业价格带分布：取 rank_no==1 那行 cell_info。"""
    for c in d["data"]:
        ci = c["cell_info"]
        if str(ci["rank_no"]["rank_no_value"]["value"]["value_str"]) == "1":
            return ci
    raise ValueError("无 rank_no=1 行")


# ── per-SKU 商品维度抽取（步骤1：解决"看不到产品"，落 mvp_daily_metric sku_id=真实商品，非 _SHOP_）──

# (metric_name, cell_info 金额块 key, 取值子节点, transform)
# 子节点 'value'=主值、'out_period_ratio'=环比(原样 0-1 可负)。空块(unit=6 无 value 字段)跳过。
# **metric_name 与全店同名**（gmv_paid/gmv_net）——per-SKU 商品支付额就是 SKU 粒度的 gmv_paid，
# 同名让现有 RankChart(查 gmv_paid)/DeepDrilldown/query_metric_nl 零改动直接出产品榜。
# (_SHOP_, date, gmv_paid) 与 (SKU-xxx, date, gmv_paid) 靠 sku_id 区分，不冲突。
_PL_METRICS = [
    ("gmv_paid", "pay_amt", "value", _yuan),                       # 商品支付金额（同全店口径）
    ("gmv_net", "pay_amt_exclude_refund", "value", _yuan),         # 退款后支付金额（老板两版GMV的净额版）
    ("gmv_paid_wow_ratio", "pay_amt", "out_period_ratio", _float), # 支付额环比（0-1 可负）
]


def _extract_product_metrics(raw: dict[str, dict], today: date_cls) -> tuple[list[dict], list[str]]:
    """compass.product_list per-product 抽取。返回 ([{product_id, name, metric, date, value}], errors)。
    sku_id 待 upsert 时 resolve（product_id→内部 SKU）。空块跳过、单行坏不挂整批（fail-open）。"""
    rows: list[dict] = []
    errs: list[str] = []
    parsed = (raw.get("compass.product_list") or {}).get("parsed")
    if not parsed or not isinstance(parsed.get("data"), list):
        return rows, errs
    for item in parsed["data"]:
        try:
            ci = item.get("cell_info") or {}
            pi = ci.get("product_info") or {}
            pid = str((((pi.get("product_id_value") or {}).get("value") or {}).get("value_str") or "")).strip()
            if not pid:
                continue
            name = (((pi.get("product_name_value") or {}).get("value") or {}).get("value_str") or "").strip() or None
            for metric, ckey, sub, tr in _PL_METRICS:
                node = ci.get(ckey) or {}
                idx = (node.get(f"{ckey}_index_values") or {}).get("index_values") or {}
                sub_node = idx.get(sub) or {}
                if "value" not in sub_node:  # 空块 unit=6 无 value 字段 → 跳过（防 KeyError）
                    continue
                v = tr(sub_node["value"])
                if v is not None:
                    rows.append({"product_id": pid, "name": name, "metric": metric,
                                 "date": today.isoformat(), "value": v})
        except Exception as exc:  # noqa: BLE001
            errs.append(f"product_list row: {type(exc).__name__}: {exc}")
    return rows, errs


# (endpoint_key, metric, 中文, kind, fn, transform)  kind: 'series'|'snap'
# series fn 签名 (d, today)；snap fn 签名 (d) → 标量
CFG: list[tuple] = [
    ("compass.core_trend_v3", "gmv_paid", "成交金额(支付)", "series", _s_gmv, _yuan),
    ("compass.flow_source_funnel", "buyer_count", "成交人数", "snap",
     lambda d: d["data"][0]["cell_info"]["pay_ucnt"]["pay_ucnt_index_value"]["index_values"]["value"]["value"], _int),
    ("compass.flow_source_funnel", "product_click_uv", "商品点击人数", "snap",
     lambda d: d["data"][0]["cell_info"]["product_click_ucnt"]["product_click_ucnt_index_value"]["index_values"]["value"]["value"], _int),
    ("compass.flow_source_funnel", "product_show_uv", "商品曝光人数", "snap",
     lambda d: d["data"][0]["cell_info"]["product_show_ucnt"]["product_show_ucnt_index_value"]["index_values"]["value"]["value"], _int),
    ("compass.flow_source_funnel", "pay_conversion", "曝光支付转化率", "snap",
     lambda d: d["data"][0]["cell_info"]["product_show_pay_converse_uv_rate"]["product_show_pay_converse_uv_rate_index_value"]["index_values"]["value"]["value"], _float),
    ("doudian.getoverviewbyversion", "experience_score", "店铺体验分", "snap",
     lambda d: d["data"]["experience_score"]["value"], _int),
    ("doudian.getoverviewbyversion", "experience_goods_score", "商品体验分", "snap",
     lambda d: d["data"]["goods_score"]["value"], _int),
    ("doudian.getoverviewbyversion", "experience_logistics_score", "物流体验分", "snap",
     lambda d: d["data"]["logistics_score"]["value"], _int),
    ("doudian.getoverviewbyversion", "experience_service_score", "服务体验分", "snap",
     lambda d: d["data"]["service_score"]["value"], _int),
    ("doudian.doudian_shop_overview", "gmv_paid_card_7d", "近7天商品卡成交额", "snap",
     lambda d: d["data"]["index_card"]["data"][0]["cell_info"]["pay_amt"]["pay_amt_index_values"]["index_values"]["value"]["value"], _yuan),
    ("doudian.doudian_shop_overview", "pay_conversion_card_7d", "近7天商品卡转化率", "snap",
     lambda d: d["data"]["index_card"]["data"][0]["cell_info"]["pay_converse_rate_ucnt"]["pay_converse_rate_ucnt_index_values"]["index_values"]["value"]["value"], _float),
    ("doudian.doudian_shop_overview", "uv_card_show_7d", "近7天商品卡曝光人数", "snap",
     lambda d: d["data"]["index_card"]["data"][0]["cell_info"]["product_show_ucnt"]["product_show_ucnt_index_values"]["index_values"]["value"]["value"], _int),
    ("yuntu.getaudienceassetstructure", "asset_5a_a1", "A1认知人群资产", "snap",
     lambda d: _F(d["data"]["structure_list"], name="a1")["value"], _int),
    ("yuntu.getaudienceassetstructure", "asset_5a_a2", "A2种草人群资产", "snap",
     lambda d: _F(d["data"]["structure_list"], name="a2")["value"], _int),
    ("yuntu.getaudienceassetstructure", "asset_5a_a3", "A3互动人群资产", "snap",
     lambda d: _F(d["data"]["structure_list"], name="a3")["value"], _int),
    ("yuntu.getaudienceassetstructure", "asset_5a_a4", "A4购买人群资产", "snap",
     lambda d: _F(d["data"]["structure_list"], name="a4")["value"], _int),
    ("yuntu.getaudienceassetstructure", "asset_5a_a5", "A5拥护人群资产", "snap",
     lambda d: _F(d["data"]["structure_list"], name="a5")["value"], _int),
    ("yuntu.get_audience_asset_trend", "asset_5a_total", "5A总人群资产", "series", _s_trend("cover_num"), _int),
    ("yuntu.get_audience_asset_trend", "industry_rank_5a", "5A资产行业排名", "series", _s_trend("rank"), _int),
    ("yuntu.get_audience_asset_trend", "asset_5a_day_added", "5A当日新增", "series", _s_trend("day_added"), _int),
    ("yuntu.get_audience_asset_trend", "asset_5a_day_loss", "5A当日流失", "series", _s_trend("day_loss"), _int),
    ("yuntu.audienceflowanalysisv2", "asset_5a_a3_cover", "A3当前覆盖人数", "snap",
     lambda d: d["data"]["num"], _int),
    ("yuntu.audienceflowanalysisv2", "asset_5a_a3_inflow_rate", "A3净流入转化率", "snap",
     lambda d: d["data"]["rate"], _float),
    ("yuntu.industryrank", "industry_rank", "行业品牌总排名", "snap",
     lambda d: _F(d["data"], id=BRAND)["rank"], _int),
    ("yuntu.industryrank", "industry_rank_diff", "行业排名环比变动", "snap",
     lambda d: _F(d["data"], id=BRAND)["rankDiff"], _int),
    ("yuntu.corebrand", "search_sov", "品牌搜索声量份额SOV", "series", _s_sov, _float),
    ("yuntu.corebrand", "search_brand_rank", "品牌搜索声量排名", "snap",
     lambda d: _F(d["data"]["data"], brandId=BRAND, queryIntent=2)["rnk"], _int),
    ("yuntu.productstructure", "gmv_share_best_selling", "爆款GMV占比", "snap",
     lambda d: _F(d["data"], brandType="BRAND", dimension="BEST_SELLING_PRODUCT")["value"], _float),
    ("yuntu.productstructure", "gmv_share_normal", "常规品GMV占比", "snap",
     lambda d: _F(d["data"], brandType="BRAND", dimension="NORMAL_PRODUCT")["value"], _float),

    # ───────── 覆盖扩展（2026-06-03）：明细 headline 标量 + 渠道曝光序列 ─────────
    # compass.product_list 商品维度大表 —— 只抽 headline（整张 6 行明细 deferred，二期单存商品维表）
    ("compass.product_list", "top_sku_gmv_paid", "Top1商品用户支付金额(榜首·分→元)", "snap",
     lambda d: _pl_top_amt(d, "pay_amt"), _yuan),
    ("compass.product_list", "top_sku_gmv_net", "Top1商品退款后支付金额(榜首·分→元)", "snap",
     lambda d: _pl_top_amt(d, "pay_amt_exclude_refund"), _yuan),
    ("compass.product_list", "listed_sku_gmv_paid_total", "在榜商品支付金额合计(分→元)", "snap",
     lambda d: _pl_sum_amt(d, "pay_amt"), _float),
    ("compass.product_list", "listed_sku_gmv_net_total", "在榜商品退款后支付金额合计(分→元)", "snap",
     lambda d: _pl_sum_amt(d, "pay_amt_exclude_refund"), _float),
    ("compass.product_list", "listed_sku_count", "在榜商品数(headline)", "snap",
     lambda d: d["page_result"]["total"], _int),
    # compass.list 达人合作明细榜 —— 金额是 '¥xxx' 元字符串（去¥，不再÷100）。整张 18 行 deferred 二期单存达人维表
    ("compass.list", "top_author_gmv_paid", "Top1达人用户支付金额(榜首·元)", "snap",
     lambda d: _author_rows(d)[0].get("pay_gmv") if _author_rows(d) else None, _yuan_str),
    ("compass.list", "author_gmv_paid_total", "达人渠道支付金额合计(元)", "snap",
     lambda d: _sum_yuan_str(d, _author_rows, "pay_gmv"), _float),
    ("compass.list", "author_refund_amt_total", "达人渠道退款金额合计(元)", "snap",
     lambda d: _sum_yuan_str(d, _author_rows, "refund_success_gmv"), _float),
    ("compass.list", "author_purchase_ucnt_total", "达人渠道种草人数合计(个)", "snap",
     lambda d: sum((_int(r.get("purchase_ucnt")) or 0) for r in _author_rows(d)), _int),
    ("compass.list", "author_count", "在榜带货达人数(headline)", "snap",
     lambda d: d["data"]["page_result"]["total"], _int),
    # compass.trend_v3 流量来源诊断日序列 —— 直播 vs 商品卡曝光人数（渠道分流趋势，落整段历史每天一行）
    ("compass.trend_v3", "live_product_show_uv", "直播商品曝光人数(渠道·序列)", "series",
     _s_trend_v3("live_dh_product_show_uv"), _int),
    ("compass.trend_v3", "product_card_show_uv", "商品卡商品曝光人数(渠道·序列)", "series",
     _s_trend_v3("product_card_dh_product_show_uv"), _int),
    # compass.category_overview_price_band_distribution 行业价格带 —— rank1 带的成交占比中值
    # （行业脱敏区间值，行业大盘结构，非自家经营；标杆用，也存一份 _SHOP_ 级标量做选品参考）
    ("compass.category_overview_price_band_distribution", "category_top_band_gmv_ratio", "类目占比最高价格带的成交占比(中值)", "snap",
     lambda d: (lambda r: (r["cate_pay_amt_ratio"]["cate_pay_amt_ratio_index_values"]["index_values"]["extra_value"]["lower_range"]["value"]
                           + r["cate_pay_amt_ratio"]["cate_pay_amt_ratio_index_values"]["index_values"]["extra_value"]["upper_range"]["value"]) / 2)(_price_band_rank1(d)),
     _float),
]

# 整张明细表标 deferred（二期单独存，不进 mvp_daily_metric 标量）：
#   - compass.product_list 每行(product_id/pay_amt/fluctuation_analysis 波动归因文案/广告占比) → 商品维表
#   - compass.list 每行(nickname/author_id/pay_combo_nums/各渠道 GMV) → 达人维表
#   - compass.category_overview_price_band_distribution 5 行各价格带区间 → 行业价格带维表（部分入下方 benchmark）
DEFERRED_DETAIL_TABLES = [
    "compass.product_list",      # 商品维度明细（headline 已抽，整表二期）
    "compass.list",              # 达人维度明细（headline 已抽，整表二期）
    "compass.category_overview_price_band_distribution",  # 行业价格带 5 行明细（rank1 占比已抽，整表二期）
]


# ─────────────────────────── 同行标杆抽取（mvp_industry_benchmark）───────────

def _extract_benchmarks(raw: dict[str, dict], today: date_cls) -> tuple[list[dict], list[str]]:
    """从同批 raw 抽"你 vs 同行"标杆行。

    返回 (rows, errors)。每 row = {date, metric_name, industry_avg, industry_top, shop_value,
    percentile, industry_rank, source}。
    """
    rows: list[dict] = []
    errors: list[str] = []

    # 1) 罗盘 GMV 同行标杆（core_trend income_amt_benchmark），落整段每天一行
    try:
        d = (raw.get("compass.core_trend_v3") or {}).get("parsed")
        chart = d["data"]["module_data"]["trade_core_index_trend"]["unify_chart_info"]["axis_data"]
        shop_map = {_mmdd(p["x_str"], today): _yuan(p["y"]) for p in chart["income_amt"]}
        for p in chart["income_amt_benchmark"]:
            dt = _mmdd(p["x_str"], today)
            rows.append({
                "date": dt, "metric_name": "gmv_paid",
                "industry_avg": _yuan(p["y"]), "industry_top": None,
                "shop_value": shop_map.get(dt), "percentile": None,
                "industry_rank": None, "source": "compass_core_trend",
            })
    except Exception as exc:
        errors.append(f"benchmark gmv_paid: {type(exc).__name__}: {exc}")

    # 2) 5A 行业 TOP5/20/50/100 + 行业均值（asset_trend），落整段每天一行
    try:
        d = (raw.get("yuntu.get_audience_asset_trend") or {}).get("parsed")
        for p in d["data"]["trend_points"]:
            dt = p["date"]
            shop_val = _int(p.get("cover_num"))
            rank = _int(p.get("rank"))
            # 行业 TOP（top5 头部）+ 行业均值（count_average / cover_industry_avg）
            rows.append({
                "date": dt, "metric_name": "asset_5a_total",
                "industry_avg": _int(p.get("count_average")) or _int(p.get("cover_industry_avg")),
                "industry_top": _int(p.get("cover_industry_5")),
                "shop_value": shop_val, "percentile": None,
                "industry_rank": rank, "source": "yuntu_asset_trend",
            })
            # 各阈值梯队单独留行（top20/50/100 当 industry_top 维度差异，用 metric 后缀区分）
            for tier, key in (("20", "cover_industry_20"), ("50", "cover_industry_50"), ("100", "cover_industry_100")):
                val = _int(p.get(key))
                if val:
                    rows.append({
                        "date": dt, "metric_name": f"asset_5a_total_top{tier}",
                        "industry_avg": None, "industry_top": val,
                        "shop_value": shop_val, "percentile": None,
                        "industry_rank": rank, "source": "yuntu_asset_trend",
                    })
    except Exception as exc:
        errors.append(f"benchmark asset_5a: {type(exc).__name__}: {exc}")

    # 3) 抖店同行分位（doudian_shop_overview 卡片 benchmark + rank_percentage_promotion）
    try:
        d = (raw.get("doudian.doudian_shop_overview") or {}).get("parsed")
        ci = d["data"]["index_card"]["data"][0]["cell_info"]
        today_iso = today.isoformat()
        # 卡片字段 → (我们的 metric_name, 是否金额单位需 ÷100)
        card_map = [
            ("pay_amt", "gmv_paid_card_7d", True),
            ("pay_converse_rate_ucnt", "pay_conversion_card_7d", False),
            ("product_show_ucnt", "uv_card_show_7d", False),
        ]
        for raw_key, metric, is_money in card_map:
            try:
                node = ci[raw_key][f"{raw_key}_index_values"]["index_values"]
                shop_v = node["value"]["value"]
                bm = (node.get("benchmark") or {}).get("value")
                pct = (node.get("extra_value", {}).get("rank_percentage_promotion") or {}).get("value")
                conv = _yuan if is_money else _float
                rows.append({
                    "date": today_iso, "metric_name": metric,
                    "industry_avg": conv(bm), "industry_top": None,
                    "shop_value": conv(shop_v), "percentile": _float(pct),
                    "industry_rank": None, "source": "doudian_diagnose",
                })
            except Exception as exc:
                errors.append(f"benchmark doudian {metric}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        errors.append(f"benchmark doudian card: {type(exc).__name__}: {exc}")

    # 4) 行业价格带分布（category_overview_price_band_distribution）—— 行业大盘结构，非自家经营。
    #    5 个价格带各一行：每行存该价格带的「行业成交占比」(industry_avg=占比中值) 做选品/定价参考。
    #    金额/件数等也是脱敏区间(lower~upper)不存真值；只存占比中值更稳。metric_name 用价格带做后缀。
    try:
        d = (raw.get("compass.category_overview_price_band_distribution") or {}).get("parsed")
        today_iso = today.isoformat()
        for c in d["data"]:
            ci = c["cell_info"]
            band = str(ci["price_band"]["price_band_value"]["value"]["value_str"])
            rank = _int(ci["rank_no"]["rank_no_value"]["value"]["value_str"])
            ratio_node = ci["cate_pay_amt_ratio"]["cate_pay_amt_ratio_index_values"]["index_values"]["extra_value"]
            lo = _float((ratio_node.get("lower_range") or {}).get("value"))
            hi = _float((ratio_node.get("upper_range") or {}).get("value"))
            mid = round((lo + hi) / 2, 4) if (lo is not None and hi is not None) else (lo if lo is not None else hi)
            # 价格带标签清洗成 metric 后缀（去空格/特殊字符）
            band_key = re.sub(r"[^\w一-鿿]", "", band)
            rows.append({
                "date": today_iso, "metric_name": f"category_price_band_gmv_ratio_{band_key}",
                "industry_avg": mid, "industry_top": None,
                "shop_value": None, "percentile": None,
                "industry_rank": rank, "source": "compass_price_band",
            })
    except Exception as exc:
        errors.append(f"benchmark price_band: {type(exc).__name__}: {exc}")

    return rows, errors


# ─────────────────────────── 抽取 metric rows ───────────────────────────────

def _extract_metrics(raw: dict[str, dict], today: date_cls) -> tuple[list[dict], list[dict]]:
    """跑全部 CFG 抽取器（核心 29 + 覆盖扩展）。返回 (metric_rows, summary)。metric_row = {metric, date, value}。"""
    rows: list[dict] = []
    summary: list[dict] = []
    for ep, metric, cn, kind, fn, tr in CFG:
        parsed = (raw.get(ep) or {}).get("parsed")
        try:
            if parsed is None:
                raise ValueError(f"端点 {ep} 无 parsed（抓取失败或无 cookies）")
            if kind == "series":
                pts = [(dt, tr(v)) for dt, v in fn(parsed, today)]
                for dt, v in pts:
                    rows.append({"metric": metric, "date": dt, "value": v})
                summary.append({"metric": metric, "cn": cn, "kind": "series",
                                "n": len(pts), "err": None})
            else:
                v = tr(fn(parsed))
                rows.append({"metric": metric, "date": today.isoformat(), "value": v})
                summary.append({"metric": metric, "cn": cn, "kind": "snap",
                                "n": 1, "err": None})
        except Exception as exc:
            summary.append({"metric": metric, "cn": cn, "kind": kind, "n": 0,
                            "err": f"{type(exc).__name__}: {exc}"})
    return rows, summary


# ─────────────────────────── DB upsert ──────────────────────────────────────

async def _ensure_shop_sentinel(conn) -> None:
    """确保 mvp_sku 有 '_SHOP_' 全店哨兵行（per-SKU 行落 mvp_daily_metric 时维度对齐用）。"""
    await conn.execute(
        """
        INSERT INTO mvp_sku (id, name, douyin_product_id, status, source)
        VALUES ($1, '全店', $1, 'active', 'shop_sentinel')
        ON CONFLICT (id) DO NOTHING
        """,
        SHOP_SENTINEL,
    )


async def _resolve_or_create_sku(conn, product_id: str, name: str | None) -> str | None:
    """抖音 product_id(19位) → 内部 mvp_sku.id。命中 douyin_product_id 用内部 'SKU-xxxxx-xxxx'
    （复用现有 RankChart/下钻的 SKU 维度，老板看到熟悉 SKU 名）；未命中懒填一行 autosku
    （id=product_id 直接当主键，下次按 douyin_product_id 即命中，幂等）。**绝不返回 _SHOP_**。"""
    if not product_id:
        return None
    row = await conn.fetchrow(
        "SELECT id FROM mvp_sku WHERE douyin_product_id = $1 LIMIT 1", str(product_id))
    if row:
        return row["id"]
    await conn.execute(
        """
        INSERT INTO mvp_sku (id, name, douyin_product_id, status, source)
        VALUES ($1, $2, $1, 'active', 'metric_ingest_autosku')
        ON CONFLICT (id) DO NOTHING
        """,
        str(product_id), (name or f"商品{product_id}")[:200],
    )
    return str(product_id)


async def _upsert_bi_scalar_rows(conn, rows: list[dict], platform: str = PLATFORM) -> int:
    """BI 批次标量 upsert（sku_ref='_SHOP_' 全店 / 否则 resolve product_id）。落 mvp_daily_metric。"""
    n = 0
    cache: dict[str, str | None] = {}
    for r in rows:
        if r.get("value") is None:
            continue
        ref = r.get("sku_ref") or SHOP_SENTINEL
        if ref == SHOP_SENTINEL:
            sku_id = SHOP_SENTINEL
        else:
            if ref not in cache:
                cache[ref] = await _resolve_or_create_sku(conn, ref, None)
            sku_id = cache[ref]
        if not sku_id:
            continue
        await conn.execute(
            """
            INSERT INTO mvp_daily_metric
                (sku_id, date, metric_name, value, platform, source_runbook)
            VALUES ($1, $2, $3, $4, $5, 'metric_ingest')
            ON CONFLICT (sku_id, date, metric_name, platform)
            DO UPDATE SET value = EXCLUDED.value,
                          source_runbook = EXCLUDED.source_runbook, created_at = NOW()
            """,
            sku_id, _as_date(r["date"]), r["metric"], _as_num(r["value"]), platform,
        )
        n += 1
    return n


async def _upsert_product_metrics(conn, rows: list[dict], platform: str = PLATFORM) -> int:
    """per-SKU 商品指标 upsert（resolve product_id→内部SKU，sku_id≠_SHOP_）。返回写入行数。"""
    n = 0
    cache: dict[str, str | None] = {}
    for r in rows:
        if r["value"] is None:
            continue
        pid = r["product_id"]
        if pid not in cache:
            cache[pid] = await _resolve_or_create_sku(conn, pid, r.get("name"))
        sku_id = cache[pid]
        if not sku_id:
            continue
        await conn.execute(
            """
            INSERT INTO mvp_daily_metric
                (sku_id, date, metric_name, value, platform, source_runbook)
            VALUES ($1, $2, $3, $4, $5, 'metric_ingest')
            ON CONFLICT (sku_id, date, metric_name, platform)
            DO UPDATE SET value = EXCLUDED.value,
                          source_runbook = EXCLUDED.source_runbook,
                          created_at = NOW()
            """,
            sku_id, _as_date(r["date"]), r["metric"], _as_num(r["value"]), platform,
        )
        n += 1
    return n


async def _upsert_metrics(conn, rows: list[dict], platform: str = PLATFORM) -> int:
    """upsert mvp_daily_metric（sku_id='_SHOP_'，platform 默认抖音、京东侧传 'jd'）。返回写入行数。"""
    n = 0
    for r in rows:
        if r["value"] is None:
            continue
        await conn.execute(
            """
            INSERT INTO mvp_daily_metric
                (sku_id, date, metric_name, value, platform, source_runbook)
            VALUES ($1, $2, $3, $4, $5, 'metric_ingest')
            ON CONFLICT (sku_id, date, metric_name, platform)
            DO UPDATE SET value = EXCLUDED.value,
                          source_runbook = EXCLUDED.source_runbook,
                          created_at = NOW()
            """,
            SHOP_SENTINEL, _as_date(r["date"]), r["metric"], _as_num(r["value"]), platform,
        )
        n += 1
    return n


async def _upsert_benchmarks(conn, rows: list[dict]) -> int:
    """upsert mvp_industry_benchmark（category_id='14'）。返回写入行数。"""
    n = 0
    for r in rows:
        # 全空行（标杆/分位都没取到）跳过，不污染表
        if r.get("industry_avg") is None and r.get("industry_top") is None and r.get("percentile") is None:
            continue
        await conn.execute(
            """
            INSERT INTO mvp_industry_benchmark
                (date, category_id, metric_name, industry_avg, industry_top,
                 shop_value, percentile, industry_rank, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (date, category_id, metric_name)
            DO UPDATE SET industry_avg = EXCLUDED.industry_avg,
                          industry_top = EXCLUDED.industry_top,
                          shop_value   = EXCLUDED.shop_value,
                          percentile   = EXCLUDED.percentile,
                          industry_rank = EXCLUDED.industry_rank,
                          source       = EXCLUDED.source
            """,
            _as_date(r["date"]), BENCHMARK_CATEGORY, r["metric_name"],
            _as_num(r.get("industry_avg")), _as_num(r.get("industry_top")),
            _as_num(r.get("shop_value")), _as_num(r.get("percentile")),
            r.get("industry_rank"), r.get("source"),
        )
        n += 1
    return n


# ─────────────────────────── 顶层入口 ───────────────────────────────────────

async def ingest_metrics(executor: LiveFetchExecutor,
                         today: date_cls | None = None) -> dict[str, Any]:
    """落库桥全量管线：实时取 10 端点 → 29 抽取器 + 同行标杆 → upsert 两表。

    Args:
        executor: 已注入 cookies/catalog 的 LiveFetchExecutor
        today: 测试可注入；默认 executor 的 today
    Returns:
        {ok, metric_rows_written, benchmark_rows_written, metrics_ok, metrics_total,
         fetch_errors, extract_errors, benchmark_errors}
    """
    # executor._today 已改为每次现算的北京时区 property (2026-06-11 修冻结日期)
    today = today or executor._today

    # 1) 一次浏览器会话连打 10 端点取 parsed JSON
    raw = await executor.batch_raw(INGEST_ENDPOINTS)
    fetch_errors = [f"{ep}: {r.get('error')}" for ep, r in raw.items()
                    if not r.get("ok")]

    # 2) 跑 29 抽取器 + 同行标杆 + per-SKU 商品抽取
    metric_rows, summary = _extract_metrics(raw, today)
    extract_errors = [f"{s['metric']}: {s['err']}" for s in summary if s["err"]]
    metrics_ok = sum(1 for s in summary if not s["err"])

    bench_rows, benchmark_errors = _extract_benchmarks(raw, today)

    product_rows, product_errors = _extract_product_metrics(raw, today)
    extract_errors += product_errors
    # 跌零告警 (2026-06-11 审计): per-SKU 抽取 6/5 起静默挂掉, fail-open 不等于不留痕
    if not product_rows:
        log.warning("metric_ingest: per-SKU product_list 抽取 0 行 (errors=%s) — "
                    "毛利×销售榜/商品榜将停更, 检查 compass cookie 或响应结构", product_errors or "无")

    # 一致性丢弃 (2026-06-11 审计): flow_source_funnel 抽出 buyer_count=0 而当日已有
    # gmv_paid>0 是抽取节点错位的典型症状, 丢弃该批 funnel 行防假数入库
    _funnel_metrics = {"buyer_count", "product_click_uv", "product_show_uv", "pay_conversion"}
    _buyer = next((r for r in metric_rows if r["metric"] == "buyer_count"), None)
    _gmv_today = next((r for r in metric_rows if r["metric"] == "gmv_paid" and str(r["date"]) == today.isoformat()), None)
    if (_buyer is not None and float(_buyer.get("value") or 0) == 0
            and _gmv_today is not None and float(_gmv_today.get("value") or 0) > 0):
        dropped = [r for r in metric_rows if r["metric"] in _funnel_metrics]
        metric_rows = [r for r in metric_rows if r["metric"] not in _funnel_metrics]
        log.warning("metric_ingest: buyer_count=0 但当日 gmv_paid>0, 丢弃 %d 行 funnel 指标 (抽取节点疑似错位)", len(dropped))

    # BI 2.0 第1批标量抽取（延迟 import 避免循环）
    from app.services import bi_batch1
    bi_rows, bi_errors = bi_batch1.extract_batch1(raw, today)
    extract_errors += bi_errors

    # 3) upsert（一个事务）+ BI 2.0 维表落库（延迟 import 避免循环：dim_ingest 反向 import 本模块 helper）
    from app.services import dim_ingest
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_shop_sentinel(conn)
            n_metrics = await _upsert_metrics(conn, metric_rows)
            n_bench = await _upsert_benchmarks(conn, bench_rows)
            n_products = await _upsert_product_metrics(conn, product_rows)
            n_bi = await _upsert_bi_scalar_rows(conn, bi_rows)
            dim_result = await dim_ingest.ingest_dims(raw, today, conn)

    result = {
        "ok": True,
        "date": today.isoformat(),
        "metric_rows_written": n_metrics,
        "benchmark_rows_written": n_bench,
        "product_rows_written": n_products,
        "bi_scalar_rows_written": n_bi,
        "dim_rows_written": dim_result.get("dim_rows_written", {}),
        "metrics_ok": metrics_ok,
        "metrics_total": len(CFG),
        "fetch_errors": fetch_errors,
        "extract_errors": extract_errors,
        "benchmark_errors": benchmark_errors,
        "dim_errors": dim_result.get("dim_errors", []),
    }
    log.info("metric_ingest: %d metric + %d benchmark + %d per-SKU + dims %s",
             n_metrics, n_bench, n_products, dim_result.get("dim_rows_written", {}))
    return result


async def fetch_series(metric_name: str, days: int = 30, platform: str | None = None) -> dict[str, Any]:
    """读 mvp_daily_metric 某 metric 的近 N 天序列（给桌面/AI 取数）。
    platform 省略时默认 douyin；jd_ 前缀指标自动切 platform='jd'（数据只在 jd 平台）。"""
    plat = platform or ("jd" if metric_name.startswith("jd_") else PLATFORM)
    pool = await get_pool()
    async with pool.acquire() as conn:
        recs = await conn.fetch(
            """
            SELECT date, value
            FROM mvp_daily_metric
            WHERE sku_id = $1 AND metric_name = $2 AND platform = $3
              AND date >= CURRENT_DATE - $4::int
            ORDER BY date ASC
            """,
            SHOP_SENTINEL, metric_name, plat, days,
        )
    points = [{"date": r["date"].isoformat(), "value": float(r["value"]) if r["value"] is not None else None}
              for r in recs]
    return {"ok": True, "metric": metric_name, "days": days,
            "n": len(points), "points": points}
