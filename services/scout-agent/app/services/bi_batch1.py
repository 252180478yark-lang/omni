"""BI 2.0 第1批抽取器（2026-06-03）：P0 诊断闭环 + 今日大盘 → 全店标量 mvp_daily_metric(_SHOP_)。

由 metric_ingest 调 extract_batch1(raw, today)，返回 [{sku_ref,metric,value,date,kind}]，统一落 _SHOP_。
全程 fail-open。homepage 抽取器由 workflow 产出（20 指标），其余手写（看真实 dump 结构）。

口径（罗盘 unit 编码）：unit=3 金额「分」÷100；unit=5 计数；unit=4 比率 0-1；unit=6 空块无 value 跳过。
抖店 statistics 好评率是 'xx.xx%' 串 → ÷100 为 0-1。金额双轨：带小数的值多已是元(禁÷100)，整数分值÷100。
"""
from __future__ import annotations

import re as _re

from app.services.metric_ingest import _yuan, _yuan_str, _int, _float

SHOP = "_SHOP_"


def _pct_str(v):
    """'98.67%' → 0.9867；'-'/'' → None。"""
    if v in (None, ""):
        return None
    s = _re.sub(r"[^\d.\-]", "", str(v))
    return round(float(s) / 100, 6) if s not in ("", "-", ".") else None


def _A(parsed, metric, idx=0, sub="value"):
    """Pattern A：data[idx].cell_info.<m>.<m>_index_value.index_values.<sub>.value。空块返 None。"""
    try:
        ci = parsed["data"][idx]["cell_info"][metric]
        iv = ci.get(f"{metric}_index_value") or ci.get(f"{metric}_index_values")
        node = iv["index_values"].get(sub) or {}
        return node["value"] if "value" in node else None
    except Exception:  # noqa: BLE001
        return None


def _B(parsed, card, metric, sub="value", extra=None):
    """Pattern B：data.module_data.<card>.compass_general_multi_index_card_value.data[0].<m>.index_value...。"""
    try:
        d0 = parsed["data"]["module_data"][card]["compass_general_multi_index_card_value"]["data"][0]
        iv = d0[metric]["index_value"]
        if extra is not None:
            node = (iv.get("extra_value") or {}).get(extra) or {}
        else:
            node = iv.get(sub) or {}
        return node["value"] if "value" in node else None
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────── 手写抽取器（_SHOP_ 全店标量）───────────────────────

def _ex_shop_rank(parsed, today):
    """compass.shop_rank 店铺行业支付排名（分渠道）。rank 越小越好。"""
    out = []
    m = [("industry_pay_rank", "pay_index_rank"),
         ("industry_card_pay_rank", "product_card_pay_index_rank"),
         ("industry_live_pay_rank", "live_pay_index_rank"),
         ("industry_video_pay_rank", "video_pay_index_rank")]
    for metric, jk in m:
        v = _B(parsed, "shop_rank", jk)
        if v is not None:
            out.append({"sku_ref": SHOP, "metric": metric, "value": _int(v), "kind": "snap"})
    chg = _B(parsed, "shop_rank", "pay_index_rank", sub="last_period_change")
    if chg is not None:
        out.append({"sku_ref": SHOP, "metric": "industry_pay_rank_change", "value": _int(chg), "kind": "snap"})
    return out


def _ex_flow_loss(parsed, today):
    """compass.flow_loss_card 流失人数（点击过但未成交）。"""
    v = _A(parsed, "flow_out_ucnt")
    return [{"sku_ref": SHOP, "metric": "flow_out_ucnt", "value": _int(v), "kind": "snap"}] if v is not None else []


def _ex_doudian_statistics(parsed, today):
    """doudian.statistics 服务健康：好评率/同行/差评/中差评/待回复/有图评价。"""
    out = []
    d = (parsed or {}).get("data") or {}
    pcr = d.get("positive_comment_rate") or {}
    push = lambda metric, v: out.append({"sku_ref": SHOP, "metric": metric, "value": v, "kind": "snap"}) if v is not None else None
    push("positive_comment_rate", _pct_str(pcr.get("last_30days_value")))          # 好评率近30天
    push("positive_comment_rate_peers", _pct_str(pcr.get("ahead_peers_value")))    # 同行好评率
    push("worst_count", _int(d.get("worst_count")))                                # 差评数
    push("negative_count", _int(d.get("negative_count")))                          # 中差评数
    push("mid_to_reply_count", _int(d.get("mid_to_reply_count")))                  # 待回复中评
    push("unreply_count", _int(d.get("unreply_count")))                            # 待回复总数
    push("has_photo_count", _int(d.get("has_photo_count")))                        # 有图评价数
    return out


def _ex_core_index_newold(parsed, today):
    """compass.core_index_v3 今日核心支付额 + 新/老客拆分 + 同行基准。金额 unit=3 分÷100。"""
    out = []
    push = lambda metric, v, tr=_yuan: out.append({"sku_ref": SHOP, "metric": metric, "value": tr(v), "kind": "snap"}) if v is not None else None
    push("new_usr_pay_amt", _B(parsed, "homepage_core_index", "pay_amt", extra="new_usr_pay_amt"))
    push("old_usr_pay_amt", _B(parsed, "homepage_core_index", "pay_amt", extra="old_usr_pay_amt"))
    push("new_usr_pay_amt_ratio", _B(parsed, "homepage_core_index", "pay_amt", extra="new_usr_pay_amt_ratio"), _float)
    push("core_pay_amt_benchmark", _B(parsed, "homepage_core_index", "pay_amt", sub="benchmark"))
    return out


def _ex_search_core(parsed, today):
    """compass.overview_data 搜索核心：搜索GMV/订单/曝光人数/点击率（unit=3 分÷100, unit=5 计数, unit=4 比率）。"""
    out = []
    card = "mall_search_core_data"
    push = lambda metric, jk, tr, sub="value": (
        lambda v: out.append({"sku_ref": SHOP, "metric": metric, "value": tr(v), "kind": "snap"}) if v is not None else None
    )(_B(parsed, card, jk, sub=sub))
    push("search_core_pay_amt", "pay_amt", _yuan)
    push("search_core_pay_cnt", "pay_cnt", _int)
    push("search_show_ucnt", "search_show_ucnt", _int)
    push("search_click_ratio", "search_click_ratio", _float)
    push("search_click_pay_ucnt_ratio", "search_click_pay_ucnt_ratio", _float)
    return out


def _ex_brand_mind(parsed, today):
    """yuntu.getoverview 品牌心智总览 → 全店标量（声量/互动/搜索/心智排名/NSR/偏好）。"""
    out = []
    d = (parsed or {}).get("data") or {}
    push = lambda metric, v: out.append({"sku_ref": SHOP, "metric": metric, "value": v, "kind": "snap"}) if v is not None else None
    push("brand_mind_association", _int(d.get("association_cnt")))     # 品牌联想人数
    push("brand_mind_content", _int(d.get("content_cnt")))            # 内容声量
    push("brand_mind_engagement", _int(d.get("engagement_cnt")))     # 互动量
    push("brand_mind_search", _int(d.get("search_cnt")))             # 搜索声量
    push("brand_nsr", _float(d.get("nsr")))                          # 品牌净推荐值
    push("brand_preference", _float(d.get("preference")))           # 品牌偏好度
    ia = d.get("industry_association") or {}
    push("brand_mind_industry_rank", _int(ia.get("rank")))          # 心智行业排名(越小越好)
    return out


def _ex_brand_nsr(parsed, today):
    """yuntu.getbrandnsrdetailstats NSR口碑日序列 → 全店 series（nsr/好评率/差评率/正负声量）。"""
    out = []
    trend = ((parsed or {}).get("data") or {}).get("trend") or []
    for p in trend:
        try:
            dt = p.get("date")
            if not dt:
                continue
            for jk, metric, tr in [("nsr", "brand_nsr_series", _float),
                                   ("positive_rate", "brand_positive_rate", _float),
                                   ("negative_rate", "brand_negative_rate", _float),
                                   ("positive_cnt", "brand_positive_cnt", _int),
                                   ("negative_cnt", "brand_negative_cnt", _int)]:
                if jk in p:
                    v = tr(p.get(jk))
                    if v is not None:
                        out.append({"sku_ref": SHOP, "metric": metric, "value": v, "kind": "series", "date": dt})
        except Exception:  # noqa: BLE001
            continue
    return out


# homepage 抽取器（workflow 产出，node 组装插入下方）
def _extract_bi_doudian_homepage(parsed, today):
    """抖店首页今日大盘(实时) → 全店标量 snap 行(_SHOP_)。

    数据源路径：
      data.lay_out_data[].cards[] 里两张关键卡：
        - operating_data_card_v4 → operating_data_card_v4_data.compass_list[] (今日经营指标, {key,title,val})
        - shop_info_card          → shop_info_card_data.expr_score (体验分 main_compass + 商品/物流/服务 compass_list)
        - todo_list_card          → todo_list_card_data.todo_list[] (待发货等运营待办)

    口径坑(已核样本)：
      金额 val 形如 '¥362.51' / '¥428.70' —— **已是元的格式化字符串**(带¥/逗号)，用 _yuan_str 仅 strip 符号，
        绝不能 _yuan(÷100)，否则偏 100 倍。
      计数 val 形如 '14' / '2462' —— 纯整数串，_int。
      转化率/费比 val 形如 '4.26%' / '21.09%' —— 百分号串，strip % 后 ÷100 落 0-1。
      体验分 val 形如 '85' / '80' —— 整数分，_int。
    全是今日单日大盘快照 → 一律 kind='snap'(date 由调用方填 today)，sku_ref='_SHOP_'。
    每项 try/except 跳过坏值；缺卡/缺字段 in 判后再取，fail-open。
    """
    import re as _re
    out: list[dict] = []

    def _push(metric, value, sku_ref="_SHOP_"):
        if value is not None:
            out.append({"sku_ref": sku_ref, "metric": metric, "value": value, "kind": "snap"})

    def _pct01(v):
        # '4.26%' -> 0.0426 ; '-' / '' -> None
        if v in (None, ""):
            return None
        s = _re.sub(r"[^\d.\-]", "", str(v))
        if s in ("", "-", "."):
            return None
        return round(float(s) / 100, 6)

    data = (parsed or {}).get("data") or {}
    layouts = data.get("lay_out_data") or []

    # 扁平化收集所有 card（按 card_name 索引）
    cards_by_name: dict = {}
    for lay in layouts:
        for c in (lay.get("cards") or []):
            nm = c.get("card_name")
            if nm:
                cards_by_name.setdefault(nm, c)

    # ── 1. operating_data_card_v4.compass_list（今日经营指标） ──
    # compass key → (registry metric_name, 类型) ; 类型: 'yuan_str' | 'int' | 'pct'
    _COMPASS_MAP = {
        "pay_amt":                            ("gmv_paid", "yuan_str"),          # 用户支付金额 ¥362.51
        "pay_cnt":                            ("pay_order_cnt", "int"),          # 成交订单数 14
        "pay_ucnt":                           ("buyer_count", "int"),            # 成交人数 14
        "income_amt":                         ("income_amt", "yuan_str"),        # 成交金额 ¥428.70
        "per_usr_pay_amt":                    ("per_customer_price", "yuan_str"),# 客单价 ¥25.89
        "product_show_ucnt":                  ("product_show_uv", "int"),        # 商品曝光人数 2462
        "product_click_ucnt":                 ("product_click_uv", "int"),       # 商品点击人数 105
        "product_show_click_ucnt_ratio":      ("show_click_rate", "pct"),        # 曝光-点击转化率 4.26%
        "product_click_pay_ucnt_ratio":       ("click_pay_rate", "pct"),         # 点击-成交转化率 13.33%
        "cost_amt":                           ("cost_amt", "yuan_str"),          # 支出金额 ¥126.87
        "ad_costed_amt":                      ("ad_costed_amt", "yuan_str"),     # 投放消耗 ¥90.43
        "ad_costed_expense_ratio_with_refund":("ad_cost_ratio", "pct"),          # 投放费比 21.09%
        "rfndsuc_amt_pay_time":               ("refund_amt", "yuan_str"),        # 退款金额(支付时间) ¥12.56
        "refund_order_cnt_pay_time":          ("refund_order_cnt", "int"),       # 退款订单数(支付时间) 1
    }
    odc = cards_by_name.get("operating_data_card_v4")
    if odc:
        clist = (((odc.get("data") or {}).get("operating_data_card_v4_data")) or {}).get("compass_list") or []
        for item in clist:
            try:
                k = item.get("key")
                if k not in _COMPASS_MAP:
                    continue
                metric, typ = _COMPASS_MAP[k]
                raw = item.get("val")
                if typ == "yuan_str":
                    val = _yuan_str(raw)
                elif typ == "int":
                    val = _int(raw)
                else:  # pct
                    val = _pct01(raw)
                _push(metric, val)
            except Exception:
                continue

    # ── 2. shop_info_card.expr_score（商家体验分 + 商品/物流/服务） ──
    sic = cards_by_name.get("shop_info_card")
    if sic:
        try:
            expr = ((sic.get("data") or {}).get("shop_info_card_data") or {}).get("expr_score") or {}
            main = expr.get("main_compass") or {}
            _push("experience_score", _int(main.get("val")))
            _SUB_MAP = {
                "商品": "experience_goods_score",
                "物流": "experience_logistics_score",
                "服务": "experience_service_score",
            }
            for sub in (expr.get("compass_list") or []):
                try:
                    title = (sub.get("title") or "").strip()
                    if title in _SUB_MAP:
                        _push(_SUB_MAP[title], _int(sub.get("val")))
                except Exception:
                    continue
        except Exception:
            pass

    # ── 3. todo_list_card（待发货积压，运营健康度信号） ──
    tlc = cards_by_name.get("todo_list_card")
    if tlc:
        try:
            todos = ((tlc.get("data") or {}).get("todo_list_card_data") or {}).get("todo_list") or []
            _TODO_MAP = {
                "unsend": "todo_unsend_cnt",          # 待发货
                "unprocess": "todo_aftersale_cnt",    # 待处理售后
            }
            for t in todos:
                try:
                    k = t.get("key")
                    if k in _TODO_MAP:
                        _push(_TODO_MAP[k], _int(t.get("val")))
                except Exception:
                    continue
        except Exception:
            pass

    return out


_BI_BATCH1_EXTRACTORS = [
    ("compass.shop_rank", _ex_shop_rank),
    ("compass.flow_loss_card", _ex_flow_loss),
    ("doudian.statistics", _ex_doudian_statistics),
    ("compass.core_index_v3", _ex_core_index_newold),
    ("compass.overview_data", _ex_search_core),
    ("yuntu.getoverview", _ex_brand_mind),
    ("yuntu.getbrandnsrdetailstats", _ex_brand_nsr),
    ("doudian.homepage", _extract_bi_doudian_homepage),  # noqa: F821  (node 插入定义)
]


def extract_batch1(raw, today):
    """跑第1批抽取器。返回 ([{sku_ref,metric,date,value}], errors)。fail-open。"""
    rows = []
    errs = []
    for ep, fn in _BI_BATCH1_EXTRACTORS:
        parsed = (raw.get(ep) or {}).get("parsed")
        if parsed is None:
            errs.append(f"{ep}: 无 parsed")
            continue
        try:
            for r in fn(parsed, today):
                date_v = r.get("date") if r.get("kind") == "series" else today.isoformat()
                if r.get("value") is not None:
                    rows.append({"sku_ref": r.get("sku_ref", SHOP), "metric": r["metric"],
                                 "date": date_v, "value": r["value"]})
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{ep}: {type(exc).__name__}: {exc}")
    return rows, errs
