"""29 核心 metric 的元信息注册表（综合经营分析 + 临时问数共用，禁漂移）。

唯一来源：抽取器 services/scout-agent/scripts/_ingest_kpi.py 的 CFG（已验证 29/29 抽取通过）。
本表只补"分析/问数侧"需要的元信息（中文名 / 口径 / 方向 / 同义词），**不重复抽取逻辑**。

口径约定（与落库桥 metric_ingest.py 一致）：
- 罗盘金额「分」→ 已 ÷100 元落库；rate/sov/占比 存原始 0-1；rank 越小越好。
- 全店行 sku_id='_SHOP_'，platform='douyin'。

方向（direction）：
- 'up_good'   越大越好（gmv/buyer/uv/转化/资产…）
- 'down_good' 越小越好（排名 rank / 流失 / 排名变动里"上升名次=负差值"语义复杂，统一用 down_good 表示"值越小越靠前"）
- 'neutral'   无单一好坏方向（环比变动差值等，靠正负号自解释）
"""
from __future__ import annotations

import re

# metric_name → {cn, unit, direction, aliases}
# aliases：临时问数 NL 解析用的中文/口语同义词（命中即映射到该 metric）。
METRIC_REGISTRY: dict[str, dict] = {
    "gmv_paid": {
        "cn": "成交金额(支付)", "unit": "元", "direction": "up_good",
        "aliases": ["gmv", "成交额", "成交金额", "支付金额", "销售额", "营收", "卖了多少", "成交"],
    },
    "buyer_count": {
        "cn": "成交人数", "unit": "人", "direction": "up_good",
        "aliases": ["买家数", "成交人数", "下单人数", "购买人数", "成交用户"],
    },
    "product_click_uv": {
        "cn": "商品点击人数", "unit": "人", "direction": "up_good",
        "aliases": ["点击人数", "点击uv", "商品点击", "点击访客"],
    },
    "product_show_uv": {
        "cn": "商品曝光人数", "unit": "人", "direction": "up_good",
        "aliases": ["曝光人数", "曝光uv", "商品曝光", "展现人数"],
    },
    "pay_conversion": {
        "cn": "曝光支付转化率", "unit": "比率", "direction": "up_good",
        "aliases": ["转化率", "支付转化", "成交转化率", "转化", "cvr"],
    },
    "experience_score": {
        "cn": "店铺体验分", "unit": "分", "direction": "up_good",
        "aliases": ["体验分", "店铺体验分", "店铺评分"],
    },
    "experience_goods_score": {
        "cn": "商品体验分", "unit": "分", "direction": "up_good",
        "aliases": ["商品体验分", "商品分"],
    },
    "experience_logistics_score": {
        "cn": "物流体验分", "unit": "分", "direction": "up_good",
        "aliases": ["物流体验分", "物流分"],
    },
    "experience_service_score": {
        "cn": "服务体验分", "unit": "分", "direction": "up_good",
        "aliases": ["服务体验分", "服务分", "客服分"],
    },
    "gmv_paid_card_7d": {
        "cn": "近7天商品卡成交额", "unit": "元", "direction": "up_good",
        "aliases": ["商品卡成交额", "商品卡gmv", "商品卡7天成交"],
    },
    "pay_conversion_card_7d": {
        "cn": "近7天商品卡转化率", "unit": "比率", "direction": "up_good",
        "aliases": ["商品卡转化率", "商品卡转化"],
    },
    "uv_card_show_7d": {
        "cn": "近7天商品卡曝光人数", "unit": "人", "direction": "up_good",
        "aliases": ["商品卡曝光人数", "商品卡曝光"],
    },
    "asset_5a_a1": {
        "cn": "A1认知人群资产", "unit": "人", "direction": "up_good",
        "aliases": ["a1", "a1人群", "认知人群"],
    },
    "asset_5a_a2": {
        "cn": "A2种草人群资产", "unit": "人", "direction": "up_good",
        "aliases": ["a2", "a2人群", "种草人群"],
    },
    "asset_5a_a3": {
        "cn": "A3互动人群资产", "unit": "人", "direction": "up_good",
        "aliases": ["a3", "a3人群", "互动人群"],
    },
    "asset_5a_a4": {
        "cn": "A4购买人群资产", "unit": "人", "direction": "up_good",
        "aliases": ["a4", "a4人群", "购买人群"],
    },
    "asset_5a_a5": {
        "cn": "A5拥护人群资产", "unit": "人", "direction": "up_good",
        "aliases": ["a5", "a5人群", "拥护人群"],
    },
    "asset_5a_total": {
        "cn": "5A总人群资产", "unit": "人", "direction": "up_good",
        "aliases": ["5a总资产", "5a人群资产", "人群资产", "5a总量", "总人群资产"],
    },
    "industry_rank_5a": {
        "cn": "5A资产行业排名", "unit": "名", "direction": "down_good",
        "aliases": ["5a排名", "5a行业排名", "人群资产排名"],
    },
    "asset_5a_day_added": {
        "cn": "5A当日新增", "unit": "人", "direction": "up_good",
        "aliases": ["5a新增", "当日新增人群", "人群新增"],
    },
    "asset_5a_day_loss": {
        "cn": "5A当日流失", "unit": "人", "direction": "down_good",
        "aliases": ["5a流失", "当日流失人群", "人群流失"],
    },
    "asset_5a_a3_cover": {
        "cn": "A3当前覆盖人数", "unit": "人", "direction": "up_good",
        "aliases": ["a3覆盖", "a3覆盖人数"],
    },
    "asset_5a_a3_inflow_rate": {
        "cn": "A3净流入转化率", "unit": "比率", "direction": "up_good",
        "aliases": ["a3流入率", "a3净流入", "a3转化"],
    },
    "industry_rank": {
        "cn": "行业品牌总排名", "unit": "名", "direction": "down_good",
        "aliases": ["行业排名", "品牌排名", "行业总排名", "排名"],
    },
    "industry_rank_diff": {
        "cn": "行业排名环比变动", "unit": "名", "direction": "neutral",
        "aliases": ["排名变动", "排名环比", "行业排名变动"],
    },
    "search_sov": {
        "cn": "品牌搜索声量份额SOV", "unit": "比率", "direction": "up_good",
        "aliases": ["sov", "声量份额", "搜索声量", "搜索份额"],
    },
    "search_brand_rank": {
        "cn": "品牌搜索声量排名", "unit": "名", "direction": "down_good",
        "aliases": ["搜索排名", "声量排名", "品牌搜索排名"],
    },
    "gmv_share_best_selling": {
        "cn": "爆款GMV占比", "unit": "比率", "direction": "neutral",
        "aliases": ["爆款占比", "爆款gmv占比"],
    },
    "gmv_share_normal": {
        "cn": "常规品GMV占比", "unit": "比率", "direction": "neutral",
        "aliases": ["常规品占比", "常规品gmv占比"],
    },
    # ── BI 2.0 补注册（2026-06-03，已落库但 registry 漏注册 + per-SKU 新增）──
    "gmv_net": {
        "cn": "退款后支付金额(净额)", "unit": "元", "direction": "up_good",
        "aliases": ["净支付额", "退款后支付", "净成交", "净gmv", "退款后gmv"],
    },
    "gmv_paid_wow_ratio": {
        "cn": "支付金额环比", "unit": "比率", "direction": "up_good",
        "aliases": ["支付环比", "成交环比", "gmv环比"],
    },
    "top_sku_gmv_paid": {
        "cn": "Top1商品支付金额", "unit": "元", "direction": "up_good",
        "aliases": ["榜首商品支付额", "top1商品gmv", "卖最好的商品成交"],
    },
    "top_sku_gmv_net": {
        "cn": "Top1商品退款后支付金额", "unit": "元", "direction": "up_good",
        "aliases": ["榜首退款后支付额", "top1净支付", "榜首净成交"],
    },
    "listed_sku_gmv_paid_total": {
        "cn": "在榜商品支付金额合计", "unit": "元", "direction": "up_good",
        "aliases": ["在榜商品支付合计", "商品榜总支付额"],
    },
    "listed_sku_gmv_net_total": {
        "cn": "在榜商品退款后支付金额合计", "unit": "元", "direction": "up_good",
        "aliases": ["在榜商品净支付合计", "商品榜净成交"],
    },
    "listed_sku_count": {
        "cn": "在榜商品数", "unit": "个", "direction": "up_good",
        "aliases": ["在榜商品数", "动销商品数", "上榜商品数"],
    },
    "top_author_gmv_paid": {
        "cn": "Top1达人支付金额", "unit": "元", "direction": "up_good",
        "aliases": ["榜首达人gmv", "带货最强达人成交", "top1达人支付额"],
    },
    "author_gmv_paid_total": {
        "cn": "达人渠道支付金额合计", "unit": "元", "direction": "up_good",
        "aliases": ["达人渠道支付合计", "达人带货总成交", "达人总gmv"],
    },
    "author_refund_amt_total": {
        "cn": "达人渠道退款金额合计", "unit": "元", "direction": "down_good",
        "aliases": ["达人退款合计", "达人渠道退款"],
    },
    "author_purchase_ucnt_total": {
        "cn": "达人渠道种草人数合计", "unit": "人", "direction": "up_good",
        "aliases": ["达人种草人数", "达人渠道种草合计"],
    },
    "author_count": {
        "cn": "在榜带货达人数", "unit": "人", "direction": "up_good",
        "aliases": ["在榜达人数", "合作达人数", "带货达人数"],
    },
    "live_product_show_uv": {
        "cn": "直播商品曝光人数", "unit": "人", "direction": "up_good",
        "aliases": ["直播曝光人数", "直播商品曝光", "直播间曝光"],
    },
    "product_card_show_uv": {
        "cn": "商品卡商品曝光人数", "unit": "人", "direction": "up_good",
        "aliases": ["商品卡曝光人数", "商品卡曝光", "货架曝光"],
    },
    "category_top_band_gmv_ratio": {
        "cn": "类目主力价格带成交占比", "unit": "比率", "direction": "neutral",
        "aliases": ["主力价格带占比", "类目最高占比价格带", "行业主流价格带"],
    },
    # ── BI 2.0 第1批补注册（2026-06-03，今日大盘/行业排名/流失/服务/新老客/搜索核心）──
    "pay_order_cnt": {"cn": "成交订单数", "unit": "单", "direction": "up_good",
                      "aliases": ["订单数", "成交单数", "出单数"]},
    "income_amt": {"cn": "成交金额(下单口径)", "unit": "元", "direction": "up_good",
                   "aliases": ["下单金额", "成交额下单口径"]},
    "per_customer_price": {"cn": "客单价", "unit": "元", "direction": "up_good",
                           "aliases": ["客单价", "人均支付", "每人花多少", "件单价"]},
    "show_click_rate": {"cn": "曝光-点击转化率", "unit": "比率", "direction": "up_good",
                        "aliases": ["曝光点击率", "点击率"]},
    "click_pay_rate": {"cn": "点击-成交转化率", "unit": "比率", "direction": "up_good",
                       "aliases": ["点击成交率", "点击转化率"]},
    "cost_amt": {"cn": "支出金额", "unit": "元", "direction": "neutral",
                 "aliases": ["支出", "花了多少"]},
    "ad_costed_amt": {"cn": "投放消耗", "unit": "元", "direction": "neutral",
                      "aliases": ["千川消耗", "广告消耗", "投放花费", "广告花了多少"]},
    "ad_cost_ratio": {"cn": "投放费比", "unit": "比率", "direction": "down_good",
                      "aliases": ["费比", "广告费比", "投放费比", "广告成本占比"]},
    "refund_amt": {"cn": "退款金额", "unit": "元", "direction": "down_good",
                   "aliases": ["退款", "退款额", "退了多少"]},
    "refund_order_cnt": {"cn": "退款订单数", "unit": "单", "direction": "down_good",
                         "aliases": ["退款单数", "退款订单"]},
    "todo_unsend_cnt": {"cn": "待发货数", "unit": "单", "direction": "down_good",
                        "aliases": ["待发货", "未发货", "积压待发"]},
    "todo_aftersale_cnt": {"cn": "待处理售后数", "unit": "单", "direction": "down_good",
                           "aliases": ["待处理售后", "待售后", "售后待处理"]},
    "industry_pay_rank": {"cn": "行业支付排名", "unit": "名", "direction": "down_good",
                          "aliases": ["行业排名", "支付排名", "排第几", "行业第几"]},
    "industry_pay_rank_change": {"cn": "行业支付排名变动", "unit": "名", "direction": "neutral",
                                 "aliases": ["排名变动", "排名涨跌"]},
    "industry_card_pay_rank": {"cn": "商品卡支付行业排名", "unit": "名", "direction": "down_good",
                               "aliases": ["商品卡排名"]},
    "industry_live_pay_rank": {"cn": "直播支付行业排名", "unit": "名", "direction": "down_good",
                               "aliases": ["直播排名"]},
    "industry_video_pay_rank": {"cn": "短视频支付行业排名", "unit": "名", "direction": "down_good",
                                "aliases": ["视频排名", "短视频排名"]},
    "flow_out_ucnt": {"cn": "流量流失人数", "unit": "人", "direction": "down_good",
                      "aliases": ["流失人数", "流失", "点击没买的人", "流量流失"]},
    "positive_comment_rate": {"cn": "好评率(近30天)", "unit": "比率", "direction": "up_good",
                              "aliases": ["好评率", "好评", "评价好不好"]},
    "positive_comment_rate_peers": {"cn": "同行好评率", "unit": "比率", "direction": "up_good",
                                    "aliases": ["同行好评率", "同行好评"]},
    "worst_count": {"cn": "差评数", "unit": "条", "direction": "down_good",
                    "aliases": ["差评数", "差评", "几个差评"]},
    "negative_count": {"cn": "中差评数", "unit": "条", "direction": "down_good",
                       "aliases": ["中差评", "中差评数"]},
    "mid_to_reply_count": {"cn": "待回复中评数", "unit": "条", "direction": "down_good",
                           "aliases": ["待回复中评"]},
    "unreply_count": {"cn": "待回复评价数", "unit": "条", "direction": "down_good",
                      "aliases": ["待回复", "未回复评价", "待回复评价"]},
    "has_photo_count": {"cn": "有图评价数", "unit": "条", "direction": "up_good",
                        "aliases": ["有图评价", "带图评价"]},
    "new_usr_pay_amt": {"cn": "新客支付金额", "unit": "元", "direction": "up_good",
                        "aliases": ["新客成交", "新客户支付", "新用户gmv", "新客gmv"]},
    "old_usr_pay_amt": {"cn": "老客支付金额", "unit": "元", "direction": "up_good",
                        "aliases": ["老客成交", "老客户支付", "复购gmv", "老客gmv"]},
    "new_usr_pay_amt_ratio": {"cn": "新客成交占比", "unit": "比率", "direction": "neutral",
                              "aliases": ["新客占比", "新客户占比"]},
    "core_pay_amt_benchmark": {"cn": "核心支付额同行基准", "unit": "元", "direction": "neutral",
                               "aliases": ["支付额同行基准", "同行支付基准"]},
    "search_core_pay_amt": {"cn": "搜索核心支付金额", "unit": "元", "direction": "up_good",
                            "aliases": ["搜索成交", "搜索核心gmv"]},
    "search_core_pay_cnt": {"cn": "搜索成交订单数", "unit": "单", "direction": "up_good",
                            "aliases": ["搜索订单数"]},
    "search_show_ucnt": {"cn": "搜索曝光人数", "unit": "人", "direction": "up_good",
                         "aliases": ["搜索曝光", "搜索展现人数"]},
    "search_click_ratio": {"cn": "搜索点击率", "unit": "比率", "direction": "up_good",
                           "aliases": ["搜索点击率"]},
    "search_click_pay_ucnt_ratio": {"cn": "搜索点击-成交转化率", "unit": "比率", "direction": "up_good",
                                    "aliases": ["搜索转化率", "搜索点击成交率"]},
    # ── BI 2.0 第3批补注册（2026-06-03，品牌心智/NSR口碑）──
    "brand_mind_association": {"cn": "品牌联想人数", "unit": "人", "direction": "up_good",
                              "aliases": ["品牌联想", "心智联想人数", "品牌声量"]},
    "brand_mind_content": {"cn": "品牌内容声量", "unit": "条", "direction": "up_good",
                          "aliases": ["内容声量", "品牌内容数"]},
    "brand_mind_engagement": {"cn": "品牌互动量", "unit": "次", "direction": "up_good",
                             "aliases": ["品牌互动", "互动量"]},
    "brand_mind_search": {"cn": "品牌搜索声量", "unit": "次", "direction": "up_good",
                         "aliases": ["品牌搜索声量", "搜索声量"]},
    "brand_nsr": {"cn": "品牌净推荐值NSR", "unit": "比率", "direction": "up_good",
                  "aliases": ["nsr", "净推荐", "净推荐值", "口碑"]},
    "brand_preference": {"cn": "品牌偏好度", "unit": "比率", "direction": "up_good",
                        "aliases": ["品牌偏好", "偏好度"]},
    "brand_mind_industry_rank": {"cn": "品牌心智行业排名", "unit": "名", "direction": "down_good",
                                "aliases": ["心智排名", "品牌心智排名"]},
    "brand_nsr_series": {"cn": "品牌NSR(日序列)", "unit": "比率", "direction": "up_good",
                        "aliases": ["nsr走势", "口碑走势"]},
    "brand_positive_rate": {"cn": "品牌正面声量率", "unit": "比率", "direction": "up_good",
                           "aliases": ["正面率", "正面声量率"]},
    "brand_negative_rate": {"cn": "品牌负面声量率", "unit": "比率", "direction": "down_good",
                           "aliases": ["负面率", "负面声量率"]},
    "brand_positive_cnt": {"cn": "品牌正面声量数", "unit": "条", "direction": "up_good",
                          "aliases": ["正面声量", "正面数"]},
    "brand_negative_cnt": {"cn": "品牌负面声量数", "unit": "条", "direction": "down_good",
                          "aliases": ["负面声量", "负面数"]},
    # 抖店 homepage 今日实时口径（与罗盘 canonical 趋势指标解耦：canonical 由罗盘 series/snap 单源拥有，
    # 这些是抖店今日实时单独落、互不覆盖。详见 bi_batch1 §双写消歧）。
    "gmv_paid_realtime": {"cn": "用户支付金额(抖店今日实时)", "unit": "元", "direction": "up_good",
                          "aliases": ["今日实时gmv", "抖店实时支付金额", "实时成交额", "今日实时成交"]},
    "buyer_count_realtime": {"cn": "成交人数(抖店今日实时)", "unit": "人", "direction": "up_good",
                          "aliases": ["今日实时成交人数", "实时买家数"]},
    "product_show_uv_realtime": {"cn": "商品曝光人数(抖店今日实时)", "unit": "人", "direction": "up_good",
                          "aliases": ["今日实时曝光人数"]},
    "product_click_uv_realtime": {"cn": "商品点击人数(抖店今日实时)", "unit": "人", "direction": "up_good",
                          "aliases": ["今日实时点击人数"]},
    "experience_score_realtime": {"cn": "店铺体验分(抖店今日实时)", "unit": "分", "direction": "up_good",
                          "aliases": ["今日实时体验分"]},
}

# 同行标杆表 mvp_industry_benchmark 实际存的 metric_name（落库桥 metric_ingest._extract_benchmarks）。
# 综合经营分析"你 vs 同行"读这些。
BENCHMARK_METRICS = {
    "gmv_paid",          # 罗盘 GMV 同行标杆（industry_avg）
    "asset_5a_total",    # 5A 行业 TOP5/均值 + rank（industry_top / industry_avg / industry_rank）
    "gmv_paid_card_7d",  # 抖店同行分位（percentile）
    "pay_conversion_card_7d",
    "uv_card_show_7d",
}

# 老板面（经营状况）优先看的"北极星 + 健康"指标（综合经营分析老板面主轴）
OWNER_FACE_METRICS = [
    "gmv_paid", "buyer_count", "pay_conversion", "product_click_uv", "product_show_uv",
    "experience_score", "industry_rank", "search_sov",
]

# 操盘手面（人群/产品/价格）优先看的指标
OPERATOR_FACE_METRICS = [
    "asset_5a_total", "asset_5a_a1", "asset_5a_a2", "asset_5a_a3", "asset_5a_a4", "asset_5a_a5",
    "asset_5a_day_added", "asset_5a_day_loss", "industry_rank_5a", "asset_5a_a3_inflow_rate",
    "gmv_share_best_selling", "gmv_share_normal", "gmv_paid_card_7d", "search_brand_rank",
]


def cn(metric_name: str) -> str:
    """metric_name → 中文名（缺则回原名）。"""
    m = METRIC_REGISTRY.get(metric_name)
    return m["cn"] if m else metric_name


def direction(metric_name: str) -> str:
    m = METRIC_REGISTRY.get(metric_name)
    return m["direction"] if m else "up_good"


def unit(metric_name: str) -> str:
    m = METRIC_REGISTRY.get(metric_name)
    return m["unit"] if m else ""


def resolve_metric(text: str) -> str | None:
    """NL 文本 → metric_name（临时问数解析）。先精确 metric_name，再 cn 全词，再 alias 子串。

    匹配优先级（避免误命中）：
      1. 文本里直接出现 metric_name（如 'gmv_paid'）→ 直返。
      2. 文本里出现完整中文名（如 '成交金额'）→ 返对应 metric。
      3. alias 子串匹配，按 alias 长度倒序（长词优先，'商品卡成交额' 先于 'gmv'）。
    """
    if not text:
        return None
    low = text.lower()
    # 空白不敏感：口语里常带空格（"5A 总资产""GMV 走势"），紧凑版用于子串匹配避免漏命中
    compact = re.sub(r"\s+", "", low)
    # 1. 直接 metric_name
    for name in METRIC_REGISTRY:
        if name in low or name in compact:
            return name
    # 2. 完整中文名
    for name, meta in METRIC_REGISTRY.items():
        cn_l = (meta["cn"] or "").lower()
        if cn_l and (cn_l in low or re.sub(r"\s+", "", cn_l) in compact):
            return name
    # 3. alias 子串（长词优先）
    candidates: list[tuple[int, str]] = []
    for name, meta in METRIC_REGISTRY.items():
        for a in meta.get("aliases", []):
            if not a:
                continue
            al = a.lower()
            if al in low or re.sub(r"\s+", "", al) in compact:
                candidates.append((len(a), name))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    return None
