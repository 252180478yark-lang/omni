"""全量 BI 2.0 维表落库（2026-06-03）：7 个非 SKU 维度抽取器 + 通用 upsert + 编排。

由 metric_ingest.ingest_metrics 顶层调用（共用同一 batch_raw 会话取的 raw），全程 fail-open：
单表/单行坏只收进 errors，不挂整批。落 migration 040 建的 7 张维表。

口径铁律（逐表不同，见 _extract_* 注释）：
- compass 数值端点「分」→ _yuan ÷100 为元；compass.list 达人榜「¥xxx」元字符串 → _yuan_str 禁÷100；
  yuntu bestseller/价格带商品价已是元禁÷100。
- rate/占比存原始 0-1；rank 越小越靠前；脱敏区间(价格带 GMV)落 lower/upper 不当精确值。
- 空块(罗盘 index_values unit=6 无 value / unit='nan' 本期无数据)必须判 'value' in node 再取。

抽取器（_extract_*）由 workflow agent 各看一个真实 dump 写成，路径基于真实结构。
"""
from __future__ import annotations

import json
import logging
from datetime import date as date_cls, datetime
from typing import Any, Callable

# 复用 metric_ingest 的口径/类型 helper（禁重定义，保证口径一致）
from app.services.metric_ingest import (
    _yuan, _yuan_str, _int, _float, _as_date, _as_num, _mmdd,
)

log = logging.getLogger(__name__)
PLATFORM = "douyin"


# ─────────────────────────── 通用 upsert（按表配置驱动）───────────────────────
# 每表：cols=插入列(业务列,platform 自动补)、conflict=UNIQUE 列、各类型列名集合（决定转型）。
_DIM_TABLES: dict[str, dict] = {
    "flow_source": {
        "table": "mvp_flow_source_metric",
        "cols": ["stat_date", "platform", "source_channel_code", "source_channel_name",
                 "entity_type", "entity_id", "entity_name", "metric_name", "value"],
        "conflict": ["stat_date", "source_channel_code", "entity_type", "entity_id", "metric_name"],
        "date": {"stat_date"}, "num": {"value"}, "int": set(), "json": set(), "bool": set(),
    },
    "author": {
        "table": "mvp_author_daily_metric",
        "cols": ["date", "platform", "author_id", "nickname", "aweme_id", "metric_name", "value"],
        "conflict": ["date", "author_id", "metric_name"],
        "date": {"date"}, "num": {"value"}, "int": set(), "json": set(), "bool": set(),
    },
    "search_keyword": {
        "table": "mvp_search_keyword_rank",
        "cols": ["keyword", "stat_date_start", "stat_date_end", "platform", "rank", "pay_amt",
                 "product_show_ucnt", "prod_show_click_ratio", "prod_click_pay_ratio", "shop_product_ids"],
        "conflict": ["keyword", "stat_date_end", "platform"],
        "date": {"stat_date_start", "stat_date_end"},
        "num": {"pay_amt", "prod_show_click_ratio", "prod_click_pay_ratio"},
        "int": {"rank", "product_show_ucnt"}, "json": {"shop_product_ids"}, "bool": set(),
    },
    "crowd_big8_profile": {
        "table": "mvp_crowd_big8_profile",
        "cols": ["date", "platform", "stage_idx", "stage_label", "big8_name", "profile_type",
                 "cover_cnt", "cover_pct", "permeability"],
        "conflict": ["date", "stage_idx", "big8_name", "profile_type"],
        "date": {"date"}, "num": {"cover_pct", "permeability"},
        "int": {"stage_idx", "cover_cnt"}, "json": set(), "bool": set(),
    },
    "crowd_asset_trend": {
        "table": "mvp_crowd_asset_trend",
        "cols": ["date", "crowd_name", "scope", "cnt", "asset_percent", "permeab", "platform"],
        "conflict": ["date", "crowd_name", "scope"],
        "date": {"date"}, "num": {"asset_percent", "permeab"}, "int": {"cnt"}, "json": set(), "bool": set(),
    },
    "price_band_product": {
        "table": "mvp_price_band_product",
        "cols": ["date", "platform", "category_id", "band_label", "rank", "product_id",
                 "product_name", "product_image_url", "gmv_lower_yuan", "gmv_upper_yuan", "addable"],
        "conflict": ["date", "category_id", "band_label", "product_id"],
        "date": {"date"}, "num": {"gmv_lower_yuan", "gmv_upper_yuan"},
        "int": {"rank"}, "json": set(), "bool": {"addable"},
    },
    "bestseller": {
        "table": "mvp_industry_bestseller",
        "cols": ["snapshot_date", "platform", "dimension", "rank", "spu_id", "spu_name",
                 "display_price", "category_l1", "category_l2", "category_l3", "image_url"],
        "conflict": ["snapshot_date", "dimension", "rank"],
        "date": {"snapshot_date"}, "num": {"display_price"}, "int": {"rank"}, "json": set(), "bool": set(),
    },
    # ── 第3批维表（migration 041）──
    "live_room_rank": {
        "table": "mvp_live_room_rank",
        "cols": ["date", "platform", "rank", "author_name", "live_pay_amt", "live_pay_ratio"],
        "conflict": ["date", "rank"],
        "date": {"date"}, "num": {"live_pay_amt", "live_pay_ratio"}, "int": {"rank"}, "json": set(), "bool": set(),
    },
    "industry_author": {
        "table": "mvp_industry_author_rank",
        "cols": ["snapshot_date", "platform", "rank", "author_id", "author_name", "fans_num", "main_category", "price_range"],
        "conflict": ["snapshot_date", "rank"],
        "date": {"snapshot_date"}, "num": set(), "int": {"rank", "fans_num"}, "json": set(), "bool": set(),
    },
    "brand_keyword": {
        "table": "mvp_brand_keyword",
        "cols": ["date", "platform", "keyword", "association_cnt", "content_cnt", "engagement_cnt",
                 "search_cnt", "brand_assoc_rank", "industry_assoc_rank"],
        "conflict": ["date", "keyword"],
        "date": {"date"}, "num": set(),
        "int": {"association_cnt", "content_cnt", "engagement_cnt", "search_cnt", "brand_assoc_rank", "industry_assoc_rank"},
        "json": set(), "bool": set(),
    },
    "shop_ticket": {
        "table": "mvp_shop_ticket",
        "cols": ["ticket_id", "platform", "ticket_type", "standard_ticket_type", "violation_reason",
                 "circumstances_level", "ticket_status", "object_name", "create_date"],
        "conflict": ["ticket_id"],
        "date": {"create_date"}, "num": set(),
        "int": {"ticket_type", "circumstances_level", "ticket_status"}, "json": set(), "bool": set(),
    },
    "compete_product": {
        "table": "mvp_compete_product",
        "cols": ["date", "platform", "rank", "comp_product_id", "comp_name", "pay_amt_lower", "pay_amt_upper", "pay_ucnt"],
        "conflict": ["date", "rank", "comp_product_id"],
        "date": {"date"}, "num": {"pay_amt_lower", "pay_amt_upper"}, "int": {"rank", "pay_ucnt"}, "json": set(), "bool": set(),
    },
    "video_aftersearch": {
        "table": "mvp_video_aftersearch",
        "cols": ["date", "platform", "video_id", "video_title", "aftersearch_uv", "aftersearch_rate"],
        "conflict": ["date", "video_id"],
        "date": {"date"}, "num": {"aftersearch_rate"}, "int": {"aftersearch_uv"}, "json": set(), "bool": set(),
    },
    "realtime_hotword": {
        "table": "mvp_realtime_hotword",
        "cols": ["date", "platform", "keyword", "opportunity_score", "search_index", "rank"],
        "conflict": ["date", "keyword"],
        "date": {"date"}, "num": {"opportunity_score"}, "int": {"search_index", "rank"}, "json": set(), "bool": set(),
    },
}


def _coerce(cfg: dict, col: str, v: Any) -> Any:
    """按表配置把值转成 asyncpg 能吃的类型（NUMERIC→Decimal, DATE→date, JSONB→str, INT→int）。"""
    if v is None:
        return None
    if col in cfg["date"]:
        return v if isinstance(v, date_cls) else _as_date(v)
    if col in cfg["num"]:
        return _as_num(v)
    if col in cfg["int"]:
        try:
            return int(v)
        except (ValueError, TypeError):
            return None
    if col in cfg["json"]:
        return json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    if col in cfg["bool"]:
        return bool(v)
    return v


async def _upsert_dim(conn, name: str, rows: list[dict]) -> tuple[int, list[str]]:
    """按 _DIM_TABLES[name] 配置 upsert。返回 (写入行数, errors)。fail-open 单行坏跳过。"""
    cfg = _DIM_TABLES[name]
    cols = cfg["cols"]
    update_cols = [c for c in cols if c not in cfg["conflict"]]
    ph = ", ".join(f"${i + 1}" for i in range(len(cols)))
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols) or cols[0] + " = EXCLUDED." + cols[0]
    sql = (f"INSERT INTO {cfg['table']} ({', '.join(cols)}) VALUES ({ph}) "
           f"ON CONFLICT ({', '.join(cfg['conflict'])}) DO UPDATE SET {set_clause}, fetched_at = NOW()")
    n = 0
    errs: list[str] = []
    for r in rows:
        vals = []
        for c in cols:
            raw = PLATFORM if c == "platform" else r.get(c)
            vals.append(_coerce(cfg, c, raw))
        try:
            await conn.execute(sql, *vals)
            n += 1
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{cfg['table']} row: {type(exc).__name__}: {exc}")
    return n, errs


# ─────────────────────────── 抽取器（workflow agent 各写一个，下方组装）─────────
# 每个 _extract_<name>(parsed, today) -> list[dict]，dict key 严格等于 _DIM_TABLES[name].cols 的业务列。

# compass__flow_data_v2 流量来源拆解 → mvp_flow_source_metric（长表，每 entity×每指标一行）。
# 结构：parsed["data"] = 4 个一级渠道节点(video/product_card/live/other_content)。
#   每个渠道: base_info.identity_base_info.{code,name} + metrics(渠道级标量块) + 可选 child_rows。
#   只有 video 渠道的 child_rows 是单视频榜：base_info.video_base_info.{video_id,video_title}
#     + base_info.extra_info.{finish_watch_ratio,watch_cnt,comment_cnt}(裸 value 块)
#     + metrics.{pay_amt(=带货gmv),pay_cnt,dh_product_show_pv}。
#   (product_card/live 也有 child_rows 但是渠道二级来源/达人/直播间——本表只按要点取 video 单视频，不下钻它们)
# 口径：金额(pay_amt/refund_sucess_amt/gpm)单位「分」→ _yuan ÷100（实测 121890→1218.9 整数分，确认÷100对）；
#   计数(pay_cnt/show_pv/uv/watch_cnt/comment_cnt)→ _int；rate/ratio/完播率 0-1 原样 → _float。
# 该端点是「当期快照」无 stat_date 字段 → stat_date=today（同 _extract_product_metrics 口径）。
# 空块兜底：metrics 子块 unit="nan" 或缺 'value' 字段必跳过（'value' in node 判定 + unit!="nan"）。

# 渠道级标量：(原始 metric key, 落库 metric_name, transform)
_FLOW_CH_METRICS = [
    ("pay_amt", "gmv_paid", _yuan),                       # 用户支付金额（分→元）
    ("pay_cnt", "pay_cnt", _int),                         # 商品成交订单数
    ("pay_ucnt", "pay_ucnt", _int),                       # 支付人数
    ("dh_product_show_pv", "product_show_pv", _int),      # 商品曝光次数
    ("dh_product_show_uv", "product_show_uv", _int),      # 商品曝光人数
    ("dh_product_click_pv", "product_click_pv", _int),    # 商品点击次数
    ("dh_product_click_uv", "product_click_uv", _int),    # 商品点击人数
    ("gpm", "gpm", _yuan),                                # 千次曝光支付额（分/千→元/千）
    ("refund_sucess_amt", "refund_amt", _yuan),           # 退款成功金额（分→元）
    ("click_add_to_cart_uv", "add_to_cart_uv", _int),     # 加购人数
    ("dh_pay_conversion_show_ratio_uv", "pay_conv_show_ratio_uv", _float),  # 曝光-支付转化率(0-1)
    ("dh_product_click_ratio_uv", "product_click_ratio_uv", _float),        # 商品点击率(0-1)
]


def _extract_flow_source(parsed, today):
    rows = []
    if not isinstance(parsed, dict):
        return rows
    data = parsed.get("data")
    if not isinstance(data, list):
        return rows
    stat = today  # 快照端点无日期，as-of today

    def _scalar(metrics, jkey, sub="value"):
        # metrics[jkey][sub] 安全取值；空块(unit="nan" / 无 value 字段)返 None。
        node = (metrics.get(jkey) or {}).get(sub)
        if not isinstance(node, dict):
            return None
        if node.get("unit") == "nan":
            return None
        if "value" not in node:
            return None
        return node["value"]

    for ch in data:
        try:
            ch_base = ((ch.get("base_info") or {}).get("identity_base_info")) or {}
            ch_code = (ch_base.get("code") or "").strip()
            ch_name = (ch_base.get("name") or "").strip()
            if not ch_code:
                continue
            ch_metrics = ch.get("metrics") or {}

            # ---- 渠道级（entity_type=channel，entity_id=渠道码）----
            for jkey, mname, tr in _FLOW_CH_METRICS:
                try:
                    raw_v = _scalar(ch_metrics, jkey, "value")
                    if raw_v is None:
                        continue
                    v = tr(raw_v)
                    if v is None:
                        continue
                    rows.append({
                        "stat_date": stat,
                        "source_channel_code": ch_code,
                        "source_channel_name": ch_name,
                        "entity_type": "channel",
                        "entity_id": ch_code,
                        "entity_name": ch_name,
                        "metric_name": mname,
                        "value": v,
                    })
                except Exception:  # noqa: BLE001  单指标坏跳过（fail-open）
                    continue

            # ---- video 渠道下单视频榜（entity_type=video，entity_id=video_id）----
            if ch_code == "video":
                for cr in (ch.get("child_rows") or []):
                    try:
                        cb = cr.get("base_info") or {}
                        vbi = cb.get("video_base_info") or {}
                        ibi = cb.get("identity_base_info") or {}
                        vid = str(vbi.get("video_id") or ibi.get("code") or "").strip()
                        if not vid:
                            continue
                        vtitle = (vbi.get("video_title") or ibi.get("name") or "").strip() or vid
                        extra = cb.get("extra_info") or {}
                        cr_metrics = cr.get("metrics") or {}

                        vid_items = []
                        # finish_watch_ratio / watch_cnt / comment_cnt 在 extra_info（裸 value 块）
                        fw = extra.get("finish_watch_ratio") or {}
                        if "value" in fw and fw.get("unit") != "nan":
                            vid_items.append(("finish_watch_ratio", _float(fw["value"])))
                        wc = extra.get("watch_cnt") or {}
                        if "value" in wc and wc.get("unit") != "nan":
                            vid_items.append(("watch_cnt", _int(wc["value"])))
                        cc = extra.get("comment_cnt") or {}
                        if "value" in cc and cc.get("unit") != "nan":
                            vid_items.append(("comment_cnt", _int(cc["value"])))
                        # gmv（带货支付额，分→元）/ 订单 / 曝光 在 metrics
                        gmv = _scalar(cr_metrics, "pay_amt", "value")
                        if gmv is not None:
                            vid_items.append(("gmv_paid", _yuan(gmv)))
                        pc = _scalar(cr_metrics, "pay_cnt", "value")
                        if pc is not None:
                            vid_items.append(("pay_cnt", _int(pc)))
                        sp = _scalar(cr_metrics, "dh_product_show_pv", "value")
                        if sp is not None:
                            vid_items.append(("product_show_pv", _int(sp)))

                        for mname, v in vid_items:
                            if v is None:
                                continue
                            rows.append({
                                "stat_date": stat,
                                "source_channel_code": "video",
                                "source_channel_name": ch_name,
                                "entity_type": "video",
                                "entity_id": vid,
                                "entity_name": vtitle,
                                "metric_name": mname,
                                "value": v,
                            })
                    except Exception:  # noqa: BLE001  单视频坏跳过（fail-open）
                        continue
        except Exception:  # noqa: BLE001  单渠道坏跳过（fail-open）
            continue
    return rows


def _extract_author(parsed, today):
    # 端点: compass 达人榜 (compass__list.json)
    # 路径: parsed["data"]["data_result"][] = 每行一个达人
    #   行内字段: author_id / nickname / aweme_id + 6 个指标字段
    # 落长表: 每达人 × 6 指标 → 一行 {date, author_id, nickname, aweme_id, metric_name, value}
    #
    # 口径关键:
    #   - pay_gmv / refund_success_gmv 是「¥xxx」元字符串(如 "¥890" / "¥239.2" / "¥25.69")
    #     → 用 _yuan_str **禁÷100**(样本带小数 ¥239.2/¥25.69 证明已是元不是分)
    #   - pay_user_nums / pay_combo_nums / pay_product_nums / purchase_ucnt 是 str int(如 "30")
    #     → _int 转型
    #   - date 用 today(榜单是某日快照, dump 无自带日期列)
    rows = []
    data = (parsed or {}).get("data") or {}
    result = data.get("data_result") or []

    # 指标定义: (源字段名, 落库 metric_name, 取值函数)
    # 金额走 _yuan_str(¥串不÷100); 计数走 _int
    metric_defs = [
        ("pay_gmv",          "author_pay_gmv",       _yuan_str),  # GMV (¥元串)
        ("pay_user_nums",    "author_pay_user_nums", _int),       # 成交人数
        ("pay_combo_nums",   "author_pay_combo_nums", _int),      # 成交件数
        ("pay_product_nums", "author_pay_product_nums", _int),    # 成交商品数
        ("purchase_ucnt",    "author_purchase_ucnt", _int),       # 种草人数
        ("refund_success_gmv", "author_refund_gmv",  _yuan_str),  # 退款金额 (¥元串)
    ]

    for node in result:
        try:
            if not isinstance(node, dict):
                continue
            author_id = node.get("author_id")
            nickname = node.get("nickname")
            aweme_id = node.get("aweme_id")
            if author_id is None:
                continue
            for src_key, metric_name, conv in metric_defs:
                try:
                    # 空块兜底: 字段缺失就跳过该指标(不强落 None)
                    if src_key not in node:
                        continue
                    raw = node.get(src_key)
                    if raw is None:
                        continue
                    val = conv(raw)
                    if val is None:
                        continue
                    rows.append({
                        "date": today,            # date_cls (榜单快照日, dump 无日期列用 today)
                        "author_id": str(author_id),
                        "nickname": nickname,
                        "aweme_id": str(aweme_id) if aweme_id is not None else None,
                        "metric_name": metric_name,
                        "value": val,
                    })
                except Exception:
                    # 单指标坏: 跳过该指标, 不影响同达人其它指标 (fail-open)
                    continue
        except Exception:
            # 单达人坏: 跳过整行, 不抛到外层 (fail-open)
            continue

    # TODO(翻页): 本 dump 单页 page_result.total=18 全在 data_result[] 内。
    #   若 total > len(data_result), scout 侧需带 page_no 递增重抓 compass 达人榜,
    #   把各页 data_result 合并后再喂本抽取器 (本函数只消费已合并的单个 parsed)。
    return rows


def _extract_search_keyword(parsed, today):
    """罗盘「搜索词排行」(word_rank) 宽表抽取器 → mvp_search_keyword_rank。

    口径/路径(基于 catalog/_bi_probe/compass__word_rank.json 真实结构核对):
      - 每个关键词 = data[i] 一行；只落 data[i].metrics.* 聚合行，
        child_rows[](按 extra.content_type=product_card/... 细分)不落。
      - 取值统一走 .value.value(metrics[k].value.value)，**不是 .value**(那是 dict)。
        空块/unit=nan/unit=6 等无 'value' 子键时先判 'value' in node 再取，缺则 None。
      - pay_amt: unit='price' 是「分」(样本 30750/5980/2990 皆整数无小数)→ _yuan ÷100 → 元。
        (实测 30750→¥307.50，符合搜索词带来的真实成交量级，未偏 100 倍)
      - prod_show_click_ratio / prod_click_pay_ratio: unit='ratio' 原始 0-1，
        **实测可 >1(如 1.5 / 2)，勿截断**(搜索词窗口内点击/成交比)。
      - product_show_ucnt / rank: unit='number' 原样 int。
      - keyword: base_info.query_word_info.word。
      - shop_product_ids: tables.shop_show_product.product_list[].product_id(字符串数组)，没有→[]。
      - stat_date_start: extra.date_range '2026/05/26-2026/06/02' 取前段斜杠日期；解析失败→None。
        stat_date_end: 用 today(传入 date 对象)。
    """
    rows = []
    extra = parsed.get("extra") or {}

    # 统计窗口起始日(date_range 前段，斜杠日期 YYYY/MM/DD)；失败 fail-open 给 None
    stat_date_start = None
    dr = extra.get("date_range")
    if dr:
        try:
            start_str = str(dr).split("-")[0].strip()  # '2026/05/26'
            y, mo, dd = (int(x) for x in start_str.split("/"))
            stat_date_start = date_cls(y, mo, dd)
        except Exception:
            stat_date_start = None
    stat_date_end = today  # 要点：end 用 today

    def _mval(metrics, key):
        # metrics[key].value.value；空块/nan/无 'value' 安全返 None
        node = (metrics.get(key) or {}).get("value")
        if not isinstance(node, dict) or "value" not in node:
            return None
        return node.get("value")

    for item in (parsed.get("data") or []):
        try:
            bi = item.get("base_info") or {}
            keyword = (bi.get("query_word_info") or {}).get("word")
            if not keyword:
                continue  # 没词的行无意义，跳过

            m = item.get("metrics") or {}

            # 本店曝光商品 id 数组(没有就 [])
            ssp = (item.get("tables") or {}).get("shop_show_product") or {}
            shop_product_ids = [
                str(p.get("product_id"))
                for p in (ssp.get("product_list") or [])
                if p.get("product_id") is not None
            ]

            rows.append({
                "keyword": keyword,
                "stat_date_start": stat_date_start,
                "stat_date_end": stat_date_end,
                "rank": _int(_mval(m, "rank")),
                "pay_amt": _yuan(_mval(m, "pay_amt")),                              # 分→元
                "product_show_ucnt": _int(_mval(m, "product_show_ucnt")),
                "prod_show_click_ratio": _float(_mval(m, "prod_show_click_ratio")),  # 原始比例勿截断
                "prod_click_pay_ratio": _float(_mval(m, "prod_click_pay_ratio")),    # 原始比例勿截断(可>1)
                "shop_product_ids": shop_product_ids,
            })
        except Exception:
            # 单行坏跳过，fail-open 不抛外层
            continue

    # TODO(分页): page_result.total=318 但本次只抓 page_no=1 / page_size=10 共 10 行；
    #   全量需翻页(page_no 递增直到累计 >= total)，由上游 fetch 串多页 parsed 后
    #   逐页调本抽取器汇总(本函数对单页 parsed 幂等)。
    return rows


def _extract_crowd_big8_profile(parsed, today):
    # 云图 getAudienceAssetBig8Profile：5A 各阶段 × 7 种 profile_type × 8 big8 人群画像。
    # 嵌套结构（已核对 dump）：
    #   parsed["data"]["ax_big8_profile"]["0".."5"]            <- stage 键，原始数字字符串
    #     [<X>_profile]                                        <- self/compete/top5/top20/top50/top100/avg
    #       [ {big8_name, big8_cnt(str), big8_percent(0-1), big8_permeab(0-1)}, ... ]  <- 8 个 big8
    # 口径：big8_cnt 是【人数】（无小数，整数字符串如 "9964"/"16001771"），int 化，绝不 ÷100；
    #       big8_percent / big8_permeab 已是 0-1，原样存。
    # stage_idx 存 stage 键的原始数字（int），stage_label 固定 None（无中文标签来源）。
    rows = []
    try:
        big8_root = (parsed or {}).get("data", {}).get("ax_big8_profile", {})
    except Exception:
        return rows
    if not isinstance(big8_root, dict):
        return rows

    # profile_type 落库值 -> JSON 里的 list 键名（后缀 _profile）
    PROFILE_KEYS = {
        "self":   "self_profile",
        "compete": "compete_profile",
        "top5":   "top5_profile",
        "top20":  "top20_profile",
        "top50":  "top50_profile",
        "top100": "top100_profile",
        "avg":    "avg_profile",
    }

    for stage_key, stage_node in big8_root.items():
        # stage 键应是 "0".."5"；解析成 int 存 stage_idx
        try:
            stage_idx = int(stage_key)
        except Exception:
            continue
        if not isinstance(stage_node, dict):
            continue

        for profile_type, list_key in PROFILE_KEYS.items():
            profile_list = stage_node.get(list_key)
            if not isinstance(profile_list, list):
                continue
            for node in profile_list:
                # 单行坏 try/except 跳过（fail-open，不抛外层）
                try:
                    if not isinstance(node, dict):
                        continue
                    name = node.get("big8_name")
                    if not name:
                        continue
                    # 人数：int 化（非金额，不 ÷100）；空块/缺字段判 in 再取
                    cover_cnt = _int(node["big8_cnt"]) if "big8_cnt" in node else None
                    cover_pct = _float(node["big8_percent"]) if "big8_percent" in node else None
                    permeability = _float(node["big8_permeab"]) if "big8_permeab" in node else None
                    rows.append({
                        "date": today if isinstance(today, date_cls) else _as_date(today),
                        "stage_idx": stage_idx,
                        "stage_label": None,
                        "big8_name": name,
                        "profile_type": profile_type,
                        "cover_cnt": cover_cnt,
                        "cover_pct": cover_pct,
                        "permeability": permeability,
                    })
                except Exception:
                    continue
    return rows


def _extract_crowd_asset_trend(parsed, today):
    """yuntu getaudienceassetbig8trend → mvp_crowd_asset_trend 行。

    结构（实测，基于真实 dump）：
      parsed["data"]["trend"] = [ {date:"YYYYMMDD",
                                   self_profile:{big8_name,big8_cnt,big8_percent,big8_permeab},
                                   compete_profile:{...}, top5_profile:{...}, top20_profile:{...},
                                   top50_profile:{...}, top100_profile:{...}, avg_profile:{...}}, ... ]

    迭代：trend[] 按【日期】迭代（非按人群展开），每天循环 7 个 profile/scope key 落 7 行。
    crowd_name 取当天该 profile 节点里的 big8_name（dump 里恒 "新锐白领"，从 JSON 实际字段拿，不写死）。

    口径：
      - cnt：big8_cnt 是字符串人数（如 "2765"），_int 化，**不 ÷100**（人数非金额，无小数）。
      - asset_percent / permeab：big8_percent/big8_permeab 已是 0-1 原始浮点，原样取，**不换算**。
      - date："YYYYMMDD" → datetime.strptime(s,'%Y%m%d').date()（date_cls 对象，asyncpg DATE 列吃）。

    fail-open：单行（某天某 scope）坏就 try/except 跳过，不抛到外层；空块（无 big8_cnt 等键）判
    'key' in node 再取。
    """
    rows = []
    # data 块可能整体缺失/形状异常 → 整体兜底返空，不抛外层
    try:
        trend = (parsed.get("data") or {}).get("trend") or []
    except Exception:
        return rows

    # profile key（JSON 实际命名） → 目标 scope 短名
    scope_map = [
        ("self_profile", "self"),
        ("compete_profile", "compete"),
        ("top5_profile", "top5"),
        ("top20_profile", "top20"),
        ("top50_profile", "top50"),
        ("top100_profile", "top100"),
        ("avg_profile", "avg"),
    ]

    for day in trend:
        # 一天一个 date，7 个 scope 共用
        try:
            ds = day.get("date")
            if not ds:
                continue
            dt = datetime.strptime(str(ds), "%Y%m%d").date()
        except Exception:
            # 这一天 date 坏 → 跳过整天（7 行），不抛外层
            continue

        for pkey, scope in scope_map:
            try:
                node = day.get(pkey)
                if not isinstance(node, dict):
                    continue
                # 空块/缺字段防御：必须有 big8_cnt 才算有效行
                if "big8_cnt" not in node:
                    continue
                crowd_name = node.get("big8_name")
                rows.append({
                    "date": dt,
                    "crowd_name": crowd_name,
                    "scope": scope,
                    "cnt": _int(node.get("big8_cnt")),          # 人数：int 化，不 ÷100
                    "asset_percent": _float(node.get("big8_percent")),  # 已 0-1，原样
                    "permeab": _float(node.get("big8_permeab")),        # 已 0-1，原样
                })
            except Exception:
                # 单 scope 行坏 → 跳过该行，继续下一个 scope（fail-open）
                continue

    return rows


def _extract_price_band_product(parsed, today):
    """罗盘·类目大盘 价格分析-商品榜 → mvp_price_band_product 行。

    端点真实结构（每个 data[] 元素）：
      el["cell_info"]["rank_no"]["rank_no_value"]["value"]["value_str"]            -> "1"  (排名, 文本需转 int)
      el["cell_info"]["product_info"]["product_id_value"]["value"]["value_str"]    -> 商品ID (19位文本数字, 留字符串不转 int 防溢出)
      el["cell_info"]["product_info"]["product_name_value"]["value"]["value_str"]  -> 商品名
      el["cell_info"]["product_info"]["product_image_value"]["value"]["value_str"] -> 主图 alicdn url
      el["cell_info"]["cate_pay_amt"]["cate_pay_amt_index_values"]["index_values"]
          ["extra_value"]["lower_range"|"upper_range"]["value"]                    -> GMV 脱敏区间(分, unit=3)
          ["out_period_ratio"]                                                     -> {"unit":6} 无 value, 空块跳过
      el["cell_info"]["add_competition_info"]["is_addable_value"]["value"]["value_str"] -> "true"/"false"

    口径：
      - GMV 是 lower/upper **脱敏区间**（cate_pay_amt 区间分 → ÷100 落 lower+upper 两列，禁当精确值）。
        样本 lower=100000000 / upper=250000000 均为整数无小数 → 单位是「分」→ _yuan ÷100 = 1,000,000 / 2,500,000 元。
      - band_label / category_id payload 内无 → category_id 用 "14"，band_label 用 "_ALL_"（后续按入参细分）。
      - rank / product_id 在 value_str 文本里：rank 转 int；product_id 保留字符串（19 位防 int64 语义损失）。
      - out_period_ratio unit=6 且无 'value' → 不取（GMV 只取 lower_range/upper_range）。
    """
    rows = []
    data = parsed.get("data") or []
    for el in data:
        try:
            ci = (el or {}).get("cell_info") or {}

            # --- rank（文本 → int）---
            rank = None
            try:
                rk = (((ci.get("rank_no") or {}).get("rank_no_value") or {}).get("value") or {})
                if "value_str" in rk:
                    rank = _int(rk.get("value_str"))
            except Exception:
                rank = None

            # --- product 基础信息 ---
            pinfo = ci.get("product_info") or {}
            def _pv(key):
                try:
                    node = ((pinfo.get(key) or {}).get("value") or {})
                    return node.get("value_str") if "value_str" in node else None
                except Exception:
                    return None
            product_id = _pv("product_id_value")          # 留字符串（19 位）
            product_name = _pv("product_name_value")
            product_image_url = _pv("product_image_value")

            # --- GMV 脱敏区间（分 → 元，÷100）；out_period_ratio(unit=6 无 value) 跳过 ---
            gmv_lower_yuan = None
            gmv_upper_yuan = None
            try:
                ev = ((((ci.get("cate_pay_amt") or {}).get("cate_pay_amt_index_values") or {})
                       .get("index_values") or {}).get("extra_value") or {})
                lr = ev.get("lower_range") or {}
                ur = ev.get("upper_range") or {}
                if "value" in lr:
                    gmv_lower_yuan = _yuan(lr.get("value"))   # 分 → 元
                if "value" in ur:
                    gmv_upper_yuan = _yuan(ur.get("value"))   # 分 → 元
            except Exception:
                gmv_lower_yuan = gmv_upper_yuan = None

            # --- addable bool ---
            addable = False
            try:
                av = ((((ci.get("add_competition_info") or {}).get("is_addable_value") or {})
                       .get("value") or {}))
                if "value_str" in av:
                    addable = str(av.get("value_str")).strip().lower() == "true"
            except Exception:
                addable = False

            # 没商品 id 视为坏行跳过（其余字段允许 None）
            if not product_id:
                continue

            rows.append({
                "date": today,                # date_cls=today（入参 today 已是 date 对象）
                "category_id": "14",          # payload 内无 → 固定 "14"
                "band_label": "_ALL_",        # 从入参注入，dump 无 → 占位 "_ALL_"
                "rank": rank,
                "product_id": product_id,
                "product_name": product_name,
                "product_image_url": product_image_url,
                "gmv_lower_yuan": gmv_lower_yuan,
                "gmv_upper_yuan": gmv_upper_yuan,
                "addable": addable,
            })
        except Exception:
            # fail-open：单行坏跳过，不抛到外层
            continue
    return rows


def _extract_bestseller(parsed, today):
    # 端点: yuntu bestsellingproduct —— 云图行业热销/新品/常规品榜单
    # 真实结构(已对照 dump): parsed["data"] = list[dict]，每个 item 扁平:
    #   id / name / url / price / dimension / categories[0..2]
    # 无显式 rank 字段 → rank = 数组下标 + 1
    rows = []
    data = parsed.get("data")
    if not isinstance(data, list):
        return rows
    for i, item in enumerate(data):
        try:
            if not isinstance(item, dict):
                continue
            # categories 是 [l1, l2, l3] 字符串数组；防越界/缺位
            cats = item.get("categories")
            if not isinstance(cats, list):
                cats = []
            c1 = cats[0] if len(cats) > 0 else None
            c2 = cats[1] if len(cats) > 1 else None
            c3 = cats[2] if len(cats) > 2 else None
            # display_price: 样本带小数(1361.67/3498.2/25.8)已是「元」→ 禁 ÷100，直接 _float
            row = {
                "snapshot_date": today,                       # date_cls=today
                "dimension": item.get("dimension"),           # 原样存(BEST_SELLING/NEW_ARRIVAL/NORMAL_PRODUCT)
                "rank": i + 1,                                 # 无显式 rank → 下标+1
                "spu_id": item.get("id"),                      # data[i].id
                "spu_name": item.get("name"),
                "display_price": _float(item.get("price")),    # 已是元，不 ÷100
                "category_l1": c1,
                "category_l2": c2,
                "category_l3": c3,
                "image_url": item.get("url"),
            }
            rows.append(row)
        except Exception:
            # 单行坏 → 跳过(fail-open)，不抛外层
            continue
    return rows


# 抽取器名 → (端点 key, 抽取函数)
def _extract_flow_source_self(parsed, today):
    """compass flow_source_detail_v2 -> mvp_flow_source_metric (自营流量源, entity_type=self_channel).
    长表: 每流量源 × 每指标一行. 路径:
      data[].cell_info.flow_source.flow_source_value.value.value_str = 流量源名
      data[].cell_info.<m>.<m>_index_value.index_values.value.value  = 指标值
      data[].cell_info.<m>.<m>_index_value.index_values.value.unit   = 单位(3金额分÷100/4比率原始/5计数/6空)
    自营图文行全 unit=6 空 -> 该源不产行. fail-open: 单源/单指标坏跳过, 不抛外层.
    """
    rows = []
    if not isinstance(parsed, dict):
        return rows
    data = parsed.get("data")
    if not isinstance(data, list):
        return rows

    # 非指标键(流量源名维度), 遍历指标时跳过
    _DIM_KEYS = {"flow_source"}

    for item in data:
        try:
            if not isinstance(item, dict):
                continue
            cell_info = item.get("cell_info")
            if not isinstance(cell_info, dict):
                continue

            # 流量源名
            fs = cell_info.get("flow_source")
            if not isinstance(fs, dict):
                continue
            fsv = fs.get("flow_source_value")
            if not isinstance(fsv, dict):
                continue
            v = fsv.get("value")
            if not isinstance(v, dict):
                continue
            source_name = v.get("value_str")
            if not source_name or not isinstance(source_name, str):
                continue
            source_name = source_name.strip()
            if not source_name:
                continue

            # 每指标一行
            for m_key, m_block in cell_info.items():
                if m_key in _DIM_KEYS:
                    continue
                try:
                    if not isinstance(m_block, dict):
                        continue
                    # 指标内层 key = <m>_index_value
                    idx_block = m_block.get(m_key + "_index_value")
                    if not isinstance(idx_block, dict):
                        continue
                    iv = idx_block.get("index_values")
                    if not isinstance(iv, dict):
                        continue
                    val_node = iv.get("value")
                    if not isinstance(val_node, dict):
                        continue
                    if "value" not in val_node:
                        # 空块 (unit=6 占位, 无 value) -> 跳过
                        continue
                    raw = val_node.get("value")
                    if raw is None:
                        continue
                    unit = val_node.get("unit")
                    # 单位归一: 3金额分÷100 / 5计数取整 / 4比率原始 / 其它当数值
                    if unit == 3:
                        value = _yuan(raw)
                    elif unit == 5:
                        value = _int(raw)
                    elif unit == 4:
                        value = _float(raw)
                    else:
                        value = _float(raw)
                    if value is None:
                        continue
                    rows.append({
                        "stat_date": today,
                        "source_channel_code": source_name,
                        "source_channel_name": source_name,
                        "entity_type": "self_channel",
                        "entity_id": source_name,
                        "entity_name": source_name,
                        "metric_name": m_key,
                        "value": value,
                    })
                except Exception:
                    continue
        except Exception:
            continue

    return rows


def _extract_live_room_rank(parsed, today):
    """compass 直播间/达人 top_list → mvp_live_room_rank（每行一直播间）。

    结构：parsed["data"]["data_result"] = 直播间列表。data_head 定义列含义：
      rank(排名) / author_item(达人，取 name 或 nickname) / val(直播用户支付金额)
      / ratio(直播用户支付金额占比 0-1) / opt(操作，忽略)。
    rank 优先用行内 rank 字段，缺则用下标+1。
    口径：val 是达人/直播间榜金额——这类 list 端点金额**已是元，禁 ÷100**
      （样本 val.value=5180 整数 + ratio=0.2708 → 全榜合计≈19130；19130 元合理，
      若按分÷100=191 元荒谬，故确认已是元）→ _float；ratio 原始 0-1 → _float。
    空块/缺字段判 in 再取；单行坏 try/except 跳过（fail-open 不抛外层）。
    该端点是当期快照无日期字段 → date=today（date 对象）。
    """
    rows = []
    if not isinstance(parsed, dict):
        return rows
    data = parsed.get("data")
    if not isinstance(data, dict):
        return rows
    results = data.get("data_result")
    if not isinstance(results, list):
        return rows
    for idx, it in enumerate(results):
        try:
            if not isinstance(it, dict):
                continue
            author = it.get("author_item") or {}
            name = (author.get("name") or author.get("nickname") or "").strip()
            if not name:
                continue
            rank = _int(it.get("rank")) if "rank" in it and it.get("rank") is not None else (idx + 1)
            val_node = it.get("val")
            if isinstance(val_node, dict):
                amt = _float(val_node.get("value")) if "value" in val_node else None
            else:
                amt = _float(val_node)
            ratio_node = it.get("ratio")
            if isinstance(ratio_node, dict):
                ratio = _float(ratio_node.get("value")) if "value" in ratio_node else None
            else:
                ratio = _float(ratio_node)
            rows.append({
                "date": today,
                "rank": rank,
                "author_name": name,
                "live_pay_amt": amt,
                "live_pay_ratio": ratio,
            })
        except Exception:  # noqa: BLE001  单行坏跳过（fail-open）
            continue
    return rows


def _extract_industry_author(parsed, today):
    rows = []
    if not isinstance(parsed, dict):
        return rows
    data = parsed.get("data")
    if not isinstance(data, list):
        return rows
    for idx, item in enumerate(data):
        try:
            if not isinstance(item, dict):
                continue
            author_id = item.get("id")
            if author_id is None:
                continue
            rows.append({
                "snapshot_date": today,
                "rank": idx + 1,
                "author_id": str(author_id),
                "author_name": item.get("name") if "name" in item else None,
                "fans_num": _int(item.get("fansNum")) if "fansNum" in item else None,
                "main_category": item.get("mainCategoryName") if "mainCategoryName" in item else None,
                "price_range": item.get("mainPriceRange") if "mainPriceRange" in item else None,
            })
        except Exception:
            continue
    return rows


def _extract_brand_keyword(parsed, today):
    # path: data.keyword_stats[] —— 每行一心智词
    # keyword 名在 keyword_name 字段（keyword 字段是 UUID cluster id，别用）
    # 所有数值字段都是字符串 → _int；全是计数/排名，无金额，不÷100
    rows = []
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(data, dict):
        return rows
    stats = data.get("keyword_stats")
    if not isinstance(stats, list):
        return rows
    for it in stats:
        if not isinstance(it, dict):
            continue
        try:
            kw = it.get("keyword_name")
            if not kw:
                continue
            rows.append({
                "date": today,
                "keyword": kw,
                "association_cnt": _int(it.get("association_cnt")),
                "content_cnt": _int(it.get("content_cnt")),
                "engagement_cnt": _int(it.get("engagement_cnt")),
                "search_cnt": _int(it.get("search_cnt")),
                "brand_assoc_rank": _int(it.get("brand_association_rank")),
                "industry_assoc_rank": _int(it.get("industry_association_rank")),
            })
        except Exception:
            continue
    return rows


def _extract_shop_ticket(parsed, today):
    """抖店罚单列表 doudian get_ticket_list → mvp_shop_ticket。
    data.tickets[] 每行一罚单。object_name 在 info.object.object_name。
    无创建时间字段(只有 info.violation_time 是违规时间戳,非创建),create_date 一律 None。
    circumstances_level 在 JSON 里是字符串("3"/"1") → _int 转 int。"""
    rows = []
    if not isinstance(parsed, dict):
        return rows
    data = parsed.get("data")
    if not isinstance(data, dict):
        return rows
    tickets = data.get("tickets")
    if not isinstance(tickets, list):
        return rows
    for t in tickets:
        try:
            if not isinstance(t, dict):
                continue
            info = t.get("info") or {}
            obj = info.get("object") or {}
            object_name = obj.get("object_name")

            # 无创建时间字段：violation_time 是违规时间戳(epoch),非创建时间 → None
            create_date = None

            rows.append({
                "ticket_id": t.get("ticket_id"),
                "ticket_type": _int(t.get("ticket_type")),
                "standard_ticket_type": t.get("standard_ticket_type"),
                "violation_reason": t.get("violation_reason"),
                "circumstances_level": _int(t.get("circumstances_level")),
                "ticket_status": _int(t.get("ticket_status")),
                "object_name": object_name,
                "create_date": create_date,
            })
        except Exception:
            continue
    return rows


def _extract_compete_product(parsed, today):
    """罗盘竞品商品榜抽取。
    path: data.module_data.good_compete_product_list.compass_general_table_value.data[]
    每行一竞品: product_info.product{product_id,product_name} +
               pay_amt.index_values.extra_value.{lower,upper}.value (unit=3 分 -> _yuan 元) +
               pay_ucnt.index_values.extra_value.{lower,upper}.value (unit=5 件数, 取 lower 单值)
    fail-open: 缺字段判 in 再取, 单行坏 try/except 跳过。"""
    rows = []
    if not isinstance(parsed, dict):
        return rows
    data = parsed.get("data")
    if not isinstance(data, dict) or "module_data" not in data:
        return rows
    md = data["module_data"]
    if not isinstance(md, dict) or "good_compete_product_list" not in md:
        return rows
    block = md["good_compete_product_list"]
    if not isinstance(block, dict) or "compass_general_table_value" not in block:
        return rows
    table = block["compass_general_table_value"]
    if not isinstance(table, dict) or "data" not in table:
        return rows
    items = table["data"]
    if not isinstance(items, list):
        return rows

    def _range_bounds(cell):
        # cell_info.<idx>.index_values.extra_value.{lower,upper}.value
        lo = up = None
        if isinstance(cell, dict):
            iv = cell.get("index_values")
            if isinstance(iv, dict):
                ev = iv.get("extra_value")
                if isinstance(ev, dict):
                    lwr = ev.get("lower")
                    upr = ev.get("upper")
                    if isinstance(lwr, dict):
                        lo = lwr.get("value")
                    if isinstance(upr, dict):
                        up = upr.get("value")
        return lo, up

    for idx, item in enumerate(items):
        try:
            if not isinstance(item, dict):
                continue
            cell = item.get("cell_info")
            if not isinstance(cell, dict):
                continue

            # product_info
            comp_product_id = None
            comp_name = None
            pinfo = cell.get("product_info")
            if isinstance(pinfo, dict):
                prod = pinfo.get("product")
                if isinstance(prod, dict):
                    comp_product_id = prod.get("product_id")
                    comp_name = prod.get("product_name")

            # 至少要有 id 或 name, 否则这行没意义跳过
            if comp_product_id is None and comp_name is None:
                continue

            # pay_amt 脱敏区间 -> 元 (unit=3 分 ÷100)
            amt_lo, amt_up = _range_bounds(cell.get("pay_amt"))
            pay_amt_lower = _yuan(amt_lo) if amt_lo is not None else None
            pay_amt_upper = _yuan(amt_up) if amt_up is not None else None

            # pay_ucnt 区间 -> 取 lower 单值 (件数非金额, 不除)
            ucnt_lo, _ucnt_up = _range_bounds(cell.get("pay_ucnt"))
            pay_ucnt = _int(ucnt_lo) if ucnt_lo is not None else None

            rows.append({
                "date": today,
                "rank": idx + 1,
                "comp_product_id": comp_product_id,
                "comp_name": comp_name,
                "pay_amt_lower": pay_amt_lower,
                "pay_amt_upper": pay_amt_upper,
                "pay_ucnt": pay_ucnt,
            })
        except Exception:
            continue
    return rows


def _extract_realtime_hotword(parsed, today):
    """行业实时热词榜 -> mvp_realtime_hotword.
    结构: parsed['data'] (list, 已按 hot_value 降序) ->
          每项 {'hot_spot_list':[{'word_name','hot_value','hot_text','word_code','tag_name_list'}]}.
    口径: hot_value 是整数热度指数(0~1147万,无小数无¥)-> 当 search_index,用 _int 不换算单位.
          本端点无 opportunity_score / 搜索指数 / 趋势字段 -> opportunity_score 取 None (不编造).
          data 本身已降序, rank = 命中下标+1. 取前 50 避免爆量.
    """
    rows = []
    if not isinstance(parsed, dict):
        return rows
    data = parsed.get("data")
    if not isinstance(data, list):
        return rows
    rank = 0
    for entry in data:
        if len(rows) >= 50:
            break
        try:
            if not isinstance(entry, dict):
                continue
            hsl = entry.get("hot_spot_list")
            if not isinstance(hsl, list) or not hsl:
                continue
            h = hsl[0]
            if not isinstance(h, dict):
                continue
            kw = h.get("word_name")
            if not kw:
                continue
            rank += 1
            rows.append({
                "date": today,
                "keyword": kw,
                "opportunity_score": _float(h.get("opportunity_score")),
                "search_index": _int(h.get("hot_value")),
                "rank": rank,
            })
        except Exception:
            continue
    return rows


_EXTRACTORS: list[tuple[str, str, Callable]] = [
    ("flow_source", "compass.flow_source_detail_v2", _extract_flow_source_self),
    ("live_room_rank", "compass.top_list", _extract_live_room_rank),
    ("industry_author", "yuntu.bestsellingauthor", _extract_industry_author),
    ("brand_keyword", "yuntu.listbrandtopkeyword", _extract_brand_keyword),
    ("shop_ticket", "doudian.get_ticket_list", _extract_shop_ticket),
    ("compete_product", "compass.good_compete_product_list", _extract_compete_product),
    ("realtime_hotword", "compass.realtime_word_overview_v2", _extract_realtime_hotword),
    ("flow_source", "compass.flow_data_v2", _extract_flow_source),
    ("author", "compass.list", _extract_author),
    ("search_keyword", "compass.word_rank", _extract_search_keyword),
    ("crowd_big8_profile", "yuntu.getaudienceassetbig8profile", _extract_crowd_big8_profile),
    ("crowd_asset_trend", "yuntu.getaudienceassetbig8trend", _extract_crowd_asset_trend),
    ("price_band_product", "compass.category_overview_price_analysis_product", _extract_price_band_product),
    ("bestseller", "yuntu.bestsellingproduct", _extract_bestseller),
]


# ─────────────────────────── 顶层编排 ───────────────────────────────────────

async def ingest_dims(raw: dict[str, dict], today: date_cls, conn) -> dict[str, Any]:
    """跑 7 个维表抽取器 + upsert（fail-open）。返回 {dim_rows_written:{name:count}, dim_errors:[...]}。
    raw 是 metric_ingest 已取的 batch_raw 结果（共用会话，不额外开浏览器）。conn 在同一事务里。"""
    written: dict[str, int] = {}
    errors: list[str] = []
    for name, ep, fn in _EXTRACTORS:
        try:
            parsed = (raw.get(ep) or {}).get("parsed")
            if parsed is None:
                errors.append(f"{name}: 端点 {ep} 无 parsed")
                written[name] = 0
                continue
            rows = fn(parsed, today)
            n, errs = await _upsert_dim(conn, name, rows)
            written[name] = n
            errors += [f"{name}: {e}" for e in errs[:5]]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            written[name] = 0
    log.info("dim_ingest: %s", ", ".join(f"{k}={v}" for k, v in written.items()))
    return {"dim_rows_written": written, "dim_errors": errors}
