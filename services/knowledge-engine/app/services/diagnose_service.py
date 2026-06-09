"""诊断官 service（蓝图 §6.2 + §6 改进半：看见 + 提议 + 决策）。

把现有 feedback_digest cron（被动聚类写 markdown）升级成**可调用能力**——
读两路反馈（体感路 👎 by category + 工具级 👎 by tool；数据路 投后 ad_metrics），
产出结构化《改进提议》入 mcp.improvement_proposals（migration 038），带生命周期。

**关键设计抉择：确定性生成，不调 LLM。**
单人系统 + 反幻觉铁律（§1.7）+ R-14 禁伪因果——LLM 最擅长把"逻辑自洽实则编造"的归因
写成断言。所以本 service **直接把聚类数据映射成结构化提议**：observation 是客观计数
（带样本/数据），hypothesis 是**模板化的"可能原因"**且强制标"假设 + 未排除混杂因子 +
要证实需对比 X"。这样既给老板可行动的参谋意见，又零幻觉、可测、无 token 成本（非 LLM tool，
不返 trace）。LLM 叙事增强留作后续（真要时再加，且必须过 R-14 分层约束）。

强制遵守：
- §6.2 越界红线：只提议不碰开关（本 service 永不改 prompt/skill，拍板权 100% 在老板）。
- R-14：observation（相关，带数据）/ hypothesis（原因，标假设 + 混杂 + 证伪条件）两层分明，
  禁"主因是 X"断言。
- R-15：sample_size < 5 → confidence='preliminary'（只能"初步观察/待验证"）。
- R-17：投后口径不清的标"含自然流量/计划级"。
- R-20：dedupe_key 去重（同议题刷新不堆叠）；priority 按频次/影响；expires_at 过期归档；
  三态 accept/ignore（不再提醒同类，静音 dedupe_key）/snooze。

复用：聚类 SQL 直接调 cron 的 `_collect_feedback_digest`（禁漂移，单一来源；
函数内懒导入避免任何 import 环）。
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from typing import Any

from app.database import get_pool

logger = logging.getLogger(__name__)

# R-15 样本量阈值：n < 此值只能输出"初步观察/待验证"
_SAMPLE_THRESHOLD = 5
# R-20 提议有效期：open 提议 N 天没拍板自动归档 expired
_PROPOSAL_TTL_DAYS = 21
# snooze 默认天数
_DEFAULT_SNOOZE_DAYS = 7

_VALID_ACTIONS = {"accept", "ignore", "snooze"}

# 体感路分类 → 模板化 hypothesis（R-14：标假设 + 未排除混杂 + 证伪条件，禁断言）
_MSG_CAT_HYPOTHESIS = {
    "prompt_bad": "假设：对应任务的 system prompt 取舍偏了。未排除混杂：样本主观/某天情绪/单条偶发。"
                  "要证实需对比：调 prompt 后同类差评是否下降。",
    "factual_error": "假设：反幻觉/来源标约束在该路径没真生效。未排除：可能是 KB 召回缺失而非 prompt 问题。"
                     "要证实需对比：补来源标/补 KB 后事实类差评是否下降。",
    "tone_off": "假设：anti_ai_voice 没覆盖到该场景。未排除：个人当下偏好波动。"
                "要证实需对比：调 anti_ai_voice 后语气类差评是否下降。",
    "wrong_tool": "假设：对应 skill 的 tool 串法/选择逻辑有误（调错或漏调）。未排除：用户表述歧义。"
                  "要证实需对比：调 skill 编排后是否还选错。",
    "tradeoff_wrong": "假设：任务的重点/取舍设定偏了。未排除：需求本身模糊。"
                      "要证实需对比：明确重点后同类是否改善。",
    "incomplete": "假设：输出结构/长度约束太紧或漏要点。未排除：单条任务复杂度高。"
                  "要证实需对比：放宽结构约束后完整度是否提升。",
    "other": "假设：未归类，需老板看样本定性后再判方向。要证实需对比：归类后复评。",
    "uncategorized": "假设：未打分类，无法定向。建议老板补分类（feedback 7 类）后再诊断。",
}

# —— 分析面（趋势归因）模板化映射（R-14：归因走模板，不调 LLM，禁伪因果）——
# 设计：先按 metric_name 关键词匹配（命中即用），命中不到再按 rule_id 关键词，
# 再不到回退通用模板。每条 hypothesis 都强制三段式：
#   假设（拆解维度，不断言主因）+ 未排除混杂因子（列清楚）+ 要证实需对比 X（一句话可证伪）。
# 不编 KB 没有的东西：只给"该往哪几个方向拆"，不给具体数值/结论。
_ANALYSIS_METRIC_HYPOTHESIS: list[tuple[tuple[str, ...], str]] = [
    # ── operator 面专属（放最前，比通用 gmv/uv 更先命中）──
    # 商品卡（gmv_paid_card_7d / pay_conversion_card_7d / uv_card_show_7d）
    (("card", "商品卡"),
     "假设（拆解环节）：商品卡指标可拆 卡片曝光 → 点击 → 转化 三段，先看是露出少了、点击率低还是承接转化弱。"
     "未排除混杂：搜索/推荐流量结构变化、主图与标题改动、同行卡位竞争、活动期。"
     "要证实需对比：拉商品卡曝光/点击/转化分段看哪段掉，对比主图标题有无改动、同行同类卡表现。"),
    # 货品结构（gmv_share_best_selling / gmv_share_normal）——含 gmv 但放在通用 gmv 前
    (("gmv_share", "货品", "爆款", "常规品", "货品结构"),
     "假设（拆解结构）：货品 GMV 占比反映爆款/常规品集中度——先看是爆款过度集中（抗风险弱）还是长尾起量。"
     "未排除混杂：单品促销周期、新品冷启动、断货、平台把流量倾斜给单品。"
     "要证实需对比：看 TOP 单品 GMV 占比与动销宽度，对比是否某爆款促销拉高了集中度。"),
    # 5A 人群资产分层（asset_5a_* / 拉新 / 流失 / a3_inflow）
    (("asset_5a", "5a", "人群资产", "拉新", "流失", "inflow"),
     "假设（拆解漏斗）：5A 要看 A1→A2→A3→A4→A5 流转——A3 互动涨但 A4 购买没跟上＝种草不收割；A4/A5 掉而 A1 涨＝拉新有效但承接弱。"
     "未排除混杂：投放放量带来 A1/A2 虚高、内容曝光波动、季节性、人群圈选变更。"
     "要证实需对比：拉各层环比 + 层间流转率，对比新增 vs 流失，看卡在种草端还是收割端。"),
    # 搜索（search_sov / search_brand_rank / 品牌词）——放在行业排名前，让 brand_rank 命中搜索
    (("search", "搜索", "sov", "声量", "品牌词"),
     "假设（拆解来源）：搜索变化可拆 品牌词 vs 行业词、自然 vs 付费——先看是品牌词搜索量降（认知弱）还是行业词排名掉（竞争）。"
     "未排除混杂：竞品投放加码、季节性搜索热度、内容种草带来的搜索回流、平台搜索权重调整。"
     "要证实需对比：分品牌词/行业词看排名与点击，对比内容投放节奏与品牌词搜索量曲线是否吻合。"),
    # 行业排名（industry_rank / industry_rank_5a）——相对位
    (("industry_rank", "行业排名", "行业第几"),
     "假设（拆解相对位）：行业排名是相对位（你动 or 同行动都会变）——先确认是自身指标降还是同行涨把你挤下去。"
     "未排除混杂：同行大促、行业大盘扩容、榜单口径/类目归属变化、单日波动。"
     "要证实需对比：自身绝对值与排名一起看（绝对值升但排名降＝同行更猛），对比同类目同行动作。"),
    # GMV / 成交额 / 支付金额
    (("gmv", "成交", "支付金额", "销售额", "营收"),
     "假设（拆解口径）：GMV 变化可拆 UV × 转化率 × 客单价 三因子——先看是流量掉了、转化掉了还是客单降了。"
     "未排除混杂：大盘季节性（节假日/月初月末）、竞品价格战、自然流量波动、单日偶发。"
     "要证实需对比：把同窗口的 UV/转化/客单分别拉出来看哪个因子动得最大，再对比上月同期排季节性。"),
    # 转化率 / 成交率
    (("转化", "成交率", "cvr", "conversion"),
     "假设（拆解维度）：转化率变化可能来自详情页/主图/价格/评价/库存某一环。"
     "未排除混杂：流量结构变了（新进人群转化天然低）、活动券到期、客服响应、单日样本小。"
     "要证实需对比：分人群/分渠道看转化是否一致下滑，还是某来源拉低；对比详情页/价格有无改动。"),
    # 点击率 / CTR / 曝光点击
    (("ctr", "点击率", "点击", "曝光"),
     "假设（拆解维度）：点击率连降常见于素材疲劳、定向漂移、竞争加剧三类。"
     "未排除混杂：行业大盘 CTR 同步下行、投放时段变化、新素材冷启动期。"
     "要证实需对比：看同素材跑了多久（疲劳）、定向人群包有无变更（漂移）、同行 CTR 是否同跌（竞争）。"),
    # ROI / 投产比
    (("roi", "投产", "roas"),
     "假设（拆解口径，R-17）：ROI 变化要先确认口径——是单素材 ROI 还是计划级/含自然流量。"
     "未排除混杂：预算放量摊薄、人群圈错、出价策略变更、归因窗口差异。"
     "要证实需对比：固定预算/人群做 A/B，或用 pipeline_get_asset_lineage 反查高低 ROI 那套的卖点+人群差异。"),
    # UV / 访客 / 流量
    (("uv", "访客", "流量", "进店", "曝光人数"),
     "假设（拆解来源）：访客变化可拆自然流量 vs 付费流量 vs 私域，先看哪条流量主路动了。"
     "未排除混杂：平台推荐算法调整、季节性、内容更新频率、竞品挤压。"
     "要证实需对比：分流量来源看占比变化，对比内容发布节奏与自然流量曲线是否吻合。"),
    # 客单价
    (("客单", "客单价", "aov"),
     "假设（拆解结构）：客单价变化可能来自连带率、SKU 结构（高价款占比）、券折扣力度。"
     "未排除混杂：促销活动周期、新客占比（新客客单常低）、单日大单偶发。"
     "要证实需对比：看连带件数与高价款销量占比，对比活动券设置有无改动。"),
    # 完播率 / 观看
    (("完播", "播放", "观看", "视频"),
     "假设（拆解环节）：完播率变化常来自前 3 秒钩子、内容节奏、人群匹配。"
     "未排除混杂：投放人群变化、平台流量池变化、单条内容偶发。"
     "要证实需对比：分内容看完播是否一致，对比新老钩子版本的留存曲线。"),
    # 退款 / 退货
    (("退款", "退货", "售后", "refund"),
     "假设（拆解归因）：退款率上升可能来自物流时效、商品质量反馈、详情页预期与实物差。"
     "未排除混杂：大促后集中退、单批次问题、平台规则变化。"
     "要证实需对比：看退款理由分布（质量/物流/不喜欢），对比是否集中在某批次/某时段。"),
]

# 通用兜底（metric/rule 都没命中关键词时）
_ANALYSIS_GENERIC_HYPOTHESIS = (
    "假设（需先拆解）：该指标异动尚无对应拆解模板，建议老板先把它拆成更细的可观测因子再判方向。"
    "未排除混杂：季节性、大盘波动、竞品动作、单日样本偶发、数据口径变化。"
    "要证实需对比：拉该指标近 28 天序列看是趋势性还是单点；与上月同期/同行对比排季节性。"
)


def _match_analysis_hypothesis(metric_name: str | None, rule_id: str | None) -> str:
    """metric/rule 关键词 → 模板化 hypothesis（R-14：纯查表，不调 LLM，禁伪因果）。"""
    hay = f"{(metric_name or '').lower()} {(rule_id or '').lower()}"
    for keys, tmpl in _ANALYSIS_METRIC_HYPOTHESIS:
        if any(k.lower() in hay for k in keys):
            return tmpl
    return _ANALYSIS_GENERIC_HYPOTHESIS


def _fmt_num(v) -> str:
    """数值友好打印（None→缺；整数去小数尾）。"""
    if v is None:
        return "缺"
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f:.4g}"
    except Exception:
        return str(v)


def _fmt_ts(v) -> str | None:
    return v.isoformat() if (v is not None and hasattr(v, "isoformat")) else (str(v) if v else None)


def _confidence(n: int) -> str:
    return "observed" if n >= _SAMPLE_THRESHOLD else "preliminary"


def _conf_prefix(n: int) -> str:
    """R-15：样本不足的提议前缀，避免说成"最优/砍掉"的断言。"""
    return "" if n >= _SAMPLE_THRESHOLD else "（初步观察 · 样本 n<%d 待验证）" % _SAMPLE_THRESHOLD


def _build_proposals(data: dict, lookback_days: int) -> list[dict]:
    """把聚类数据确定性映射成提议列表（不落库，纯计算，可测）。"""
    proposals: list[dict] = []

    # —— 体感路①：消息级负反馈 by category ——
    for r in data.get("msg_by_cat") or []:
        cat = r.get("category") or "uncategorized"
        n = int(r.get("n") or 0)
        if n <= 0:
            continue
        samples = [s for s in (r.get("samples") or []) if s]
        obs = (f"最近 {lookback_days} 天有 {n} 条 AI 回复被标差评，分类「{cat}」。"
               + (f"样本：{' / '.join(repr(s) for s in samples[:3])}" if samples else ""))
        proposals.append({
            "mode": "content",
            "source": "msg_feedback",
            "dedupe_key": f"content:msg_feedback:{cat}",
            "title": f"{_conf_prefix(n)}消息级负反馈聚集：{cat} × {n}",
            "observation": obs,
            "hypothesis": _MSG_CAT_HYPOTHESIS.get(cat, _MSG_CAT_HYPOTHESIS["other"]),
            "evidence": {"category": cat, "count": n, "samples": samples[:3],
                         "window_days": lookback_days, "path": "体感路/消息级"},
            "sample_size": n,
            "confidence": _confidence(n),
            "priority": float(n),
            "priority_reason": f"按出现频次（{n} 次差评）",
        })

    # —— 体感路②：工具级负反馈 by tool × rating_category ——
    for r in data.get("tool_by_cat") or []:
        tool = r.get("tool_name") or "unknown"
        cat = r.get("rating_category") or "uncategorized"
        n = int(r.get("n") or 0)
        if n <= 0:
            continue
        proposals.append({
            "mode": "content",
            "source": "tool_feedback",
            "dedupe_key": f"content:tool_feedback:{tool}:{cat}",
            "title": f"{_conf_prefix(n)}工具被踩：{tool} / {cat} × {n}",
            "observation": f"最近 {lookback_days} 天 `{tool}` 被标差评 {n} 次，分类「{cat}」。",
            "hypothesis": (f"假设：`{tool}` 的 config/prompts/{tool}.{{system,user}}.md 或调用它的 skill "
                           f"串法该调。未排除：单次调用上下文特殊/样本少。"
                           f"要证实需对比：调整后该 tool 的差评率是否下降。"),
            "evidence": {"tool_name": tool, "rating_category": cat, "count": n,
                         "window_days": lookback_days, "path": "体感路/工具级"},
            "sample_size": n,
            "confidence": _confidence(n),
            "priority": float(n),
            "priority_reason": f"按出现频次（{n} 次差评）",
        })

    # —— 数据路：投后 ad_metrics（哪套内容真带货）——
    perf = data.get("asset_perf") or []
    if perf:
        k = len(perf)
        # 只给一条汇总提议（避免逐资产噪声）；R-17 标口径不清
        lines = []
        for r in perf[:5]:
            m = r.get("ad_metrics") or {}
            # 把 _validation/_suspect 这类元数据剔出展示
            clean = {kk: vv for kk, vv in m.items() if not kk.startswith("_")}
            lines.append(f"sku={r.get('sku_id')} asset={str(r.get('asset_id'))[:8]} metrics={clean}")
        proposals.append({
            "mode": "content",
            "source": "asset_perf",
            "dedupe_key": "content:asset_perf:summary",
            "title": f"{_conf_prefix(k)}投后回传：{k} 套内容有数据，复盘高低 ROI",
            "observation": (f"最近 30 天有 {k} 套内容回传了投后数据。明细：\n  - "
                            + "\n  - ".join(lines)),
            "hypothesis": ("假设：高 ROI/完播那套的卖点+人群+脚本值得固化（用 pipeline_get_asset_lineage 反查链路）；"
                           "低的复盘是卖点选错还是人群圈错。未排除混杂：投放预算/时段/自然流量差异（R-17："
                           "若 ad_metrics 未标 data_level，数据可能含自然流量/计划级，不进单素材 ROI 榜）。"
                           "要证实需对比：同卖点不同人群 A/B，或加大样本量。"),
            "evidence": {"asset_count": k, "window_days": 30, "path": "数据路/投后",
                         "caveat": "R-17 口径：未标 data_level 的视为含自然流量/计划级"},
            "sample_size": k,
            "confidence": _confidence(k),
            # 投后是钱的事，给个高于纯频次的基线权重，但样本小仍由 confidence 压住语气
            "priority": float(k) + 2.0,
            "priority_reason": f"投后数据（钱口径），{k} 套内容；样本小时仅作初步观察",
        })

    return proposals


async def _collect_anomalies(
    now: _dt.datetime, lookback_days: int, platform: str = "douyin", limit: int = 50,
) -> dict:
    """分析面聚类（§8.5 单平台抖音最小可用）：读近 N 天 unhandled 异动 + denorm 039 新列。

    每段独立 try（表/列缺失容忍，fail-open）；返 {anomalies:[...], errors:[...]}。
    """
    pool = get_pool()
    out: dict = {"anomalies": [], "errors": []}
    try:
        rows = await pool.fetch(
            """
            SELECT id, sku_id, metric_name, rule_id, severity, description,
                   delta_pct, baseline_value, today_value, baseline_days,
                   as_of, detected_at, platform
            FROM mvp_anomaly
            WHERE handled = FALSE
              AND COALESCE(expected, FALSE) = FALSE
              AND platform = $1
              AND detected_at > $2
            ORDER BY detected_at DESC
            LIMIT $3
            """,
            platform, now - _dt.timedelta(days=lookback_days), limit,
        )
        out["anomalies"] = [dict(r) for r in rows]
    except Exception as exc:
        out["errors"].append(f"anomalies: {exc}")
    return out


def _build_analysis_proposals(
    data: dict, lookback_days: int, platform: str,
) -> list[dict]:
    """把异动确定性映射成 analysis 提议（R-14 强制分层，不调 LLM）。

    聚合策略（R-20 防 inbox 噪声）：同 metric 的多条异动合并成 1 条提议
    （observation 列每条 delta/baseline/today/as_of，sample_size=条数）。
    dedupe_key='analysis:anomaly:{metric}:{rule}'（rule 取该 metric 下最常见 rule）。
    """
    anomalies = data.get("anomalies") or []
    if not anomalies:
        return []

    # 按 metric_name 分组聚合
    groups: dict[str, list[dict]] = {}
    for a in anomalies:
        m = a.get("metric_name") or "unknown_metric"
        groups.setdefault(m, []).append(a)

    proposals: list[dict] = []
    for metric, items in groups.items():
        n = len(items)
        # 该 metric 下最常见 rule_id（用于 dedupe_key + 模板匹配）
        rule_counts: dict[str, int] = {}
        for a in items:
            r = a.get("rule_id") or "none"
            rule_counts[r] = rule_counts.get(r, 0) + 1
        top_rule = max(rule_counts, key=rule_counts.get)

        # —— R-14 第①层 observation：客观、带数据、不含因果 ——
        lines = []
        latest_as_of = None
        for a in items[:5]:
            delta = a.get("delta_pct")
            delta_s = (f"{float(delta):+.2%}" if delta is not None else "缺delta")
            as_of = a.get("as_of")
            if as_of and (latest_as_of is None or as_of > latest_as_of):
                latest_as_of = as_of
            lines.append(
                f"sku={a.get('sku_id')} {delta_s}"
                f"（今值 {_fmt_num(a.get('today_value'))} vs 基线 {_fmt_num(a.get('baseline_value'))}"
                f"，窗口 {_fmt_num(a.get('baseline_days'))}天，数据截至 {_fmt_ts(a.get('as_of')) or '未标'}）"
            )
        obs = (
            f"最近 {lookback_days} 天 {platform} 平台「{metric}」指标有 {n} 条未处理异动"
            f"（规则 {top_rule}）。明细：\n  - " + "\n  - ".join(lines)
        )

        hyp = _match_analysis_hypothesis(metric, top_rule)

        proposals.append({
            "mode": "analysis",
            "source": "anomaly",
            "dedupe_key": f"analysis:anomaly:{metric}:{top_rule}",
            "title": f"{_conf_prefix(n)}趋势异动：{platform}/{metric} × {n} 条待归因",
            "observation": obs,
            "hypothesis": hyp,
            "evidence": {
                "metric_name": metric,
                "rule_id": top_rule,
                "anomaly_count": n,
                "platform": platform,
                "window_days": lookback_days,
                "sample_days": n,  # R-15：异动条数当样本量
                "as_of": _fmt_ts(latest_as_of),
                "anomaly_ids": [int(a["id"]) for a in items if a.get("id") is not None][:20],
                "path": "数据路/趋势异动",
                "caveat": ("R-14：observation 是相关不是因果；hypothesis 是模板化假设需老板对比验证。"
                           "R-17：跨平台/含自然流量口径未拉通，单平台抖音下钻。"),
            },
            "sample_size": n,
            "confidence": _confidence(n),
            # 趋势异动是经营信号，给比纯频次稍高的基线权重；样本小仍由 confidence 压住语气
            "priority": float(n) + 1.0,
            "priority_reason": f"按异动条数（{n} 条）；样本不足 n<{_SAMPLE_THRESHOLD} 时仅作初步观察",
        })

    proposals.sort(key=lambda p: p["priority"], reverse=True)
    return proposals


async def _upsert_proposal(pool, p: dict, now: _dt.datetime) -> str:
    """落一条提议（R-20 dedupe）：
    - 同 dedupe_key 已 ignored（不再提醒同类）→ 静音，跳过（返 'muted'）。
    - 同 dedupe_key 有活态（open / snooze 已到期）→ 刷新 occurrences/evidence/priority（返 'refreshed'）。
    - 同 dedupe_key snooze 未到期 → 不 resurface（返 'snoozed_skip'）。
    - 否则新插入（返 'created'）。
    """
    dk = p["dedupe_key"]
    # 1. ignored 静音？（不再提醒同类，直接跳过）
    muted = await pool.fetchval(
        "SELECT 1 FROM mcp.improvement_proposals WHERE dedupe_key=$1 AND status='ignored' LIMIT 1",
        dk,
    )
    if muted:
        return "muted"
    # 2. 还在 snooze 窗内？不打扰（snooze 已到期的留给下面 upsert resurface）
    active_snooze = await pool.fetchrow(
        "SELECT snooze_until FROM mcp.improvement_proposals "
        "WHERE dedupe_key=$1 AND status='snoozed' LIMIT 1",
        dk,
    )
    if active_snooze and active_snooze["snooze_until"] and active_snooze["snooze_until"] > now:
        return "snoozed_skip"

    expires_at = now + _dt.timedelta(days=_PROPOSAL_TTL_DAYS)
    ev = json.dumps(p["evidence"], ensure_ascii=False)
    # 3. 原子 upsert（ON CONFLICT 命中部分唯一索引 uq_proposal_dedupe_active，
    #    避免 SELECT-then-INSERT 在并发下撞唯一约束抛 IntegrityError 静默丢提议）。
    #    xmax=0 → 本次是 INSERT（created）；否则是 DO UPDATE（refreshed）。
    #    注：DO UPDATE 里 `mcp.improvement_proposals.occurrences` 引用旧行值已实测正确增量
    #    （schema 限定的目标表引用在 PG DO UPDATE 合法）。
    #    ignored 是终态、不在部分索引内，靠上面第 1 步 muted 预检拦截（单人顺序场景正确）；
    #    极端并发下可能出现同 dedupe_key 的 ignored+open 共存，单人场景概率近 0 且自愈
    #    （下轮 diagnose 预检不再生成同议题，游离 open 到期 expired）——不上行锁（§1.7 不过度工程）。
    row = await pool.fetchrow(
        """
        INSERT INTO mcp.improvement_proposals
            (mode, source, title, observation, hypothesis, evidence, sample_size,
             confidence, priority, priority_reason, dedupe_key, status,
             expires_at, first_seen_at, last_seen_at, created_at, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,'open',$12,$13,$13,$13,$13)
        ON CONFLICT (dedupe_key) WHERE status IN ('open','snoozed')
        DO UPDATE SET
            status='open', title=EXCLUDED.title, observation=EXCLUDED.observation,
            hypothesis=EXCLUDED.hypothesis, evidence=EXCLUDED.evidence,
            sample_size=EXCLUDED.sample_size, confidence=EXCLUDED.confidence,
            priority=EXCLUDED.priority, priority_reason=EXCLUDED.priority_reason,
            occurrences = mcp.improvement_proposals.occurrences + 1,
            last_seen_at=$13, expires_at=$12, snooze_until=NULL, updated_at=$13
        RETURNING (xmax = 0) AS is_insert
        """,
        p["mode"], p["source"], p["title"], p["observation"], p["hypothesis"], ev,
        p["sample_size"], p["confidence"], p["priority"], p["priority_reason"], dk,
        expires_at, now,
    )
    return "created" if (row and row["is_insert"]) else "refreshed"


async def _expire_stale(pool, now: _dt.datetime) -> int:
    """R-20 生命周期维护（不堆积淹没老板）：
    ① open 过 expires_at → expired（归档）。
    ② snoozed 过 snooze_until → 重新 open（resurface），避免到期 snooze 永远 dormant
       泄漏在库（diagnose 长期不跑时也能复活，等老板回来看到）。
    返回归档（open→expired）的行数。"""
    res = await pool.execute(
        "UPDATE mcp.improvement_proposals SET status='expired', updated_at=$1 "
        "WHERE status='open' AND expires_at IS NOT NULL AND expires_at < $1",
        now,
    )
    try:
        await pool.execute(
            "UPDATE mcp.improvement_proposals "
            "SET status='open', snooze_until=NULL, updated_at=$1 "
            "WHERE status='snoozed' AND snooze_until IS NOT NULL AND snooze_until < $1",
            now,
        )
    except Exception:
        logger.warning("_expire_stale snooze 到期复活失败（继续）", exc_info=True)
    # asyncpg execute() 返 "UPDATE N"——用正则取末尾数字，比 split()[-1] 稳
    m = re.search(r"(\d+)\s*$", str(res))
    return int(m.group(1)) if m else 0


async def run_diagnose(
    mode: str = "content",
    lookback_days: int = 7,
    persist: bool = True,
    platform: str = "douyin",
) -> dict:
    """跑一轮诊断：确定性生成《改进提议》→ （可选）入库 + 去重 + 过期归档。

    mode：
      - 'content'（作战面/内容改进）：读体感路（消息级/工具级 👎）+ 数据路（投后 ad_metrics）。
      - 'analysis'（分析面/趋势归因，§8.5 单平台抖音最小可用）：读近 N 天 unhandled 异动
        （mvp_anomaly + 039 新列 as_of/baseline/today/delta），按 metric 聚合出归因提议。
        归因走**模板化映射**（R-14 禁伪因果，不调 LLM）：每条标"假设 + 未排除混杂因子 +
        要证实需对比 X"，禁"主因是 X"断言。跨平台口径未拉通（京东/淘天数据未入库）→ 单平台下钻。

    返 {ok, mode, generated, created, refreshed, muted, snoozed_skip, expired,
        total_open, top: [Top3], digestion_rate_7d, note, collect_errors}。
    """
    now = _dt.datetime.now(_dt.timezone.utc)

    if mode not in ("content", "analysis"):
        return {"ok": False, "error": "invalid_mode",
                "hint": "mode 需 ∈ {content, analysis}"}

    # —— 1. 聚类 + 确定性生成提议（两 mode 各走各路，禁漂移）——
    if mode == "content":
        from app.mcp.cron import _collect_feedback_digest  # 懒导入避免 import 环
        try:
            data = await _collect_feedback_digest(now, lookback_days=lookback_days)
        except Exception as exc:
            logger.exception("run_diagnose content 聚类失败")
            return {"ok": False, "error": f"collect_failed: {exc}"}
        proposals = _build_proposals(data, lookback_days)
        note = ("只提议不碰开关（§6.2）：拍板权 100% 在老板。用 resolve_proposal 接受/忽略(不再提醒同类)/snooze。"
                "归因严格分层（R-14 observation/hypothesis），样本不足标 preliminary（R-15）。")
    else:  # analysis
        try:
            data = await _collect_anomalies(now, lookback_days, platform=platform)
        except Exception as exc:
            logger.exception("run_diagnose analysis 聚类失败")
            return {"ok": False, "error": f"collect_failed: {exc}"}
        proposals = _build_analysis_proposals(data, lookback_days, platform)
        note = ("分析面单平台抖音最小可用（§8.5）：跨平台/含自然流量口径未拉通，京东淘天数据待接入。"
                "归因是模板化假设（R-14 禁伪因果，不调 LLM）——observation 是相关不是因果，"
                "hypothesis 需老板按'要证实需对比 X'自行验证。样本不足标 preliminary（R-15）。"
                "只提议不碰开关（§6.2），用 resolve_proposal 拍板。"
                + ("" if proposals else "（本期无未处理异动可归因——异动引擎尚未 fire 或已全处理。）"))

    # —— 2. 落库 + 去重 + 过期归档（两 mode 共用同一基建，禁漂移）——
    counts = {"created": 0, "refreshed": 0, "muted": 0, "snoozed_skip": 0}
    expired = 0
    if persist:
        pool = get_pool()
        expired = await _expire_stale(pool, now)
        for p in proposals:
            try:
                outcome = await _upsert_proposal(pool, p, now)
                counts[outcome] = counts.get(outcome, 0) + 1
            except Exception:
                logger.exception("upsert proposal failed dedupe=%s", p.get("dedupe_key"))

    # —— 3. 列本 mode 的 open 提议，返 Top 3（R-20：本周只看最值钱的）——
    listing = await list_proposals(status="open", mode=mode, limit=100) if persist else {}
    top = (listing.get("proposals") or [])[:3]

    return {
        "ok": True,
        "mode": mode,
        "generated": len(proposals),
        "refreshed": counts["refreshed"],
        "created": counts["created"],
        "muted": counts["muted"],
        "snoozed_skip": counts["snoozed_skip"],
        "expired": expired,
        "total_open": listing.get("open_count", 0),
        "digestion_rate_7d": listing.get("digestion_rate_7d"),
        "top": top,
        "note": note,
        "collect_errors": data.get("errors") or [],
    }


def _row_to_proposal(r) -> dict:
    d = dict(r)
    for k in ("id",):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("evidence",):
        v = d.get(k)
        if isinstance(v, str):
            try:
                d[k] = json.loads(v)
            except Exception:
                pass
    for k in ("first_seen_at", "last_seen_at", "created_at", "updated_at",
              "expires_at", "snooze_until", "resolved_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    if d.get("priority") is not None:
        d["priority"] = float(d["priority"])
    return d


async def list_proposals(
    status: str = "open",
    mode: str | None = None,
    limit: int = 50,
) -> dict:
    """列提议（默认 open，按 priority 倒序）+ 统计（open_count + 7 天消化率 R-20）。

    listing 前先把过期 open 归档（保持 inbox 干净）。
    status='all' 列全部状态。
    """
    pool = get_pool()
    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        await _expire_stale(pool, now)
    except Exception:
        logger.warning("list_proposals 过期归档失败（继续）", exc_info=True)

    where = []
    params: list[Any] = []
    if status and status != "all":
        params.append(status)
        where.append(f"status = ${len(params)}")
    if mode:
        params.append(mode)
        where.append(f"mode = ${len(params)}")
    params.append(limit)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        rows = await pool.fetch(
            f"""
            SELECT id, mode, source, title, observation, hypothesis, evidence,
                   sample_size, confidence, priority, priority_reason, dedupe_key,
                   occurrences, status, snooze_until, expires_at, resolved_at,
                   resolution_note, resolved_by, first_seen_at, last_seen_at,
                   created_at, updated_at
            FROM mcp.improvement_proposals
            {where_sql}
            ORDER BY priority DESC, last_seen_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    except Exception as exc:
        logger.exception("list_proposals failed")
        return {"ok": False, "error": str(exc), "proposals": [], "open_count": 0}

    proposals = [_row_to_proposal(r) for r in rows]
    open_count = await pool.fetchval(
        "SELECT count(*) FROM mcp.improvement_proposals WHERE status='open'"
    )
    # R-20 消化率：近 7 天创建的提议里，已拍板（accepted/ignored）的占比
    digestion = await pool.fetchrow(
        """
        SELECT count(*) FILTER (WHERE status IN ('accepted','ignored')) AS digested,
               count(*) AS total
        FROM mcp.improvement_proposals
        WHERE created_at > $1
        """,
        now - _dt.timedelta(days=7),
    )
    total7 = int(digestion["total"] or 0)
    digested7 = int(digestion["digested"] or 0)
    rate = round(digested7 / total7, 3) if total7 else None
    return {
        "ok": True,
        "proposals": proposals,
        "count": len(proposals),
        "open_count": int(open_count or 0),
        "digestion_rate_7d": rate,
        "digestion_detail_7d": {"digested": digested7, "total": total7},
    }


async def resolve_proposal(
    proposal_id: str,
    action: str,
    note: str | None = None,
    snooze_days: int = _DEFAULT_SNOOZE_DAYS,
    actor_id: str = "yark",
) -> dict:
    """R-20 三态：accept（采纳，去改了）/ ignore（不再提醒同类，静音 dedupe_key）/ snooze（暂不看）。

    诊断官只提议——resolve 是老板的拍板动作（不自动改任何 prompt/skill）。
    """
    if action not in _VALID_ACTIONS:
        return {"ok": False, "error": "invalid_action",
                "hint": f"action 需 ∈ {sorted(_VALID_ACTIONS)}"}
    pool = get_pool()
    now = _dt.datetime.now(_dt.timezone.utc)
    status = {"accept": "accepted", "ignore": "ignored", "snooze": "snoozed"}[action]
    snooze_until = now + _dt.timedelta(days=snooze_days) if action == "snooze" else None
    try:
        row = await pool.fetchrow(
            """
            UPDATE mcp.improvement_proposals
               SET status=$2, resolution_note=$3, resolved_by=$4,
                   resolved_at = CASE WHEN $2='snoozed' THEN resolved_at ELSE $5 END,
                   snooze_until=$6, updated_at=$5
             WHERE id=$1::uuid
            RETURNING id::text AS id, status, dedupe_key
            """,
            proposal_id, status, note, actor_id, now, snooze_until,
        )
    except Exception as exc:
        logger.exception("resolve_proposal failed")
        return {"ok": False, "error": str(exc)}
    if not row:
        return {"ok": False, "error": "not_found", "hint": f"提议 {proposal_id} 不存在"}
    logger.info("resolve_proposal %s → %s（%s）", proposal_id[:8], status, action)
    return {"ok": True, "id": row["id"], "status": row["status"],
            "action": action, "dedupe_key": row["dedupe_key"]}


# ───────────────────────── 问数工具（确定性查询，不调 LLM）─────────────────────
# explain_anomaly / query_metric_trend：老板"为啥这指标动了/这指标最近啥趋势"时调。
# 与 diagnose 同一反幻觉铁律——R-14 分层归因走模板，趋势序列是真实库数据原样返回。
# MCP tool 与 REST endpoint 共用这两个函数（禁漂移）。


async def _metric_series(
    pool, metric_name: str, sku_id: str | None, platform: str, days: int,
) -> dict:
    """读某指标近 days 天序列 + 基线 mean/std（mvp_daily_metric）。返 {series, baseline, ...}。"""
    now = _dt.datetime.now(_dt.timezone.utc)
    since = (now - _dt.timedelta(days=days)).date()
    params: list[Any] = [metric_name, platform, since]
    sku_clause = ""
    if sku_id:
        params.append(sku_id)
        sku_clause = f"AND sku_id = ${len(params)}"
    # 多 SKU 时同日聚合（SUM）成大盘序列；单 SKU 时即该 SKU 序列。
    rows = await pool.fetch(
        f"""
        SELECT date, SUM(value) AS value, count(*) AS sku_n
        FROM mvp_daily_metric
        WHERE metric_name = $1 AND platform = $2 AND date >= $3 {sku_clause}
        GROUP BY date
        ORDER BY date ASC
        """,
        *params,
    )
    series = [
        {"date": r["date"].isoformat() if r["date"] else None,
         "value": float(r["value"]) if r["value"] is not None else None,
         "sku_n": int(r["sku_n"] or 0)}
        for r in rows
    ]
    vals = [s["value"] for s in series if s["value"] is not None]
    baseline: dict[str, Any] = {"n": len(vals), "mean": None, "std": None,
                                "min": None, "max": None}
    if vals:
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals) if len(vals) > 1 else 0.0
        baseline.update({
            "mean": round(mean, 6),
            "std": round(var ** 0.5, 6),
            "min": round(min(vals), 6),
            "max": round(max(vals), 6),
            "latest": vals[-1],
        })
    return {"series": series, "baseline": baseline}


async def query_metric_trend(
    metric_name: str,
    sku_id: str | None = None,
    platform: str = "douyin",
    days: int = 28,
) -> dict:
    """某指标近 days 天序列 + 基线 mean/std（确定性，不调 LLM）。

    sku_id 省略 = 同日聚合全 SKU（大盘口径）；给值 = 单 SKU 序列。
    返 {ok, metric_name, sku_id, platform, days, series:[{date,value,sku_n}], baseline:{mean,std,min,max,latest,n}}。
    """
    if not metric_name:
        return {"ok": False, "error": "metric_name_required"}
    pool = get_pool()
    try:
        out = await _metric_series(pool, metric_name, sku_id, platform, days)
    except Exception as exc:
        logger.exception("query_metric_trend failed metric=%s", metric_name)
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "metric_name": metric_name,
        "sku_id": sku_id,
        "platform": platform,
        "days": days,
        "series": out["series"],
        "baseline": out["baseline"],
        "note": ("序列为库内真实数据原样返回（mvp_daily_metric）；单平台抖音口径（§8.5）。"
                 "基线 mean/std 为该窗口统计，非滚动基线，仅供参考。"),
    }


async def explain_anomaly(anomaly_id: int) -> dict:
    """读某条异动 + 其指标近 28 天趋势，返分层归因（R-14，确定性不调 LLM）。

    返 {ok, anomaly:{...}, observation, hypothesis, unaddressed_confounders,
        falsification, recent_series, baseline}。
    - observation：客观相关（带 delta/baseline/today/as_of），不含因果断言。
    - hypothesis：模板化假设（按 metric/rule 映射），标"假设 + 未排除混杂 + 要证实需对比 X"。
    """
    pool = get_pool()
    try:
        a = await pool.fetchrow(
            """
            SELECT id, sku_id, metric_name, rule_id, severity, description,
                   delta_pct, baseline_value, today_value, baseline_days,
                   as_of, detected_at, platform, handled, expected
            FROM mvp_anomaly WHERE id = $1
            """,
            int(anomaly_id),
        )
    except Exception as exc:
        logger.exception("explain_anomaly fetch failed id=%s", anomaly_id)
        return {"ok": False, "error": str(exc)}
    if not a:
        return {"ok": False, "error": "not_found", "hint": f"异动 {anomaly_id} 不存在"}

    metric = a["metric_name"]
    rule = a["rule_id"]
    platform = a["platform"] or "douyin"
    delta = a["delta_pct"]
    delta_s = (f"{float(delta):+.2%}" if delta is not None else "缺delta")

    observation = (
        f"{platform} 平台 sku={a['sku_id']} 的「{metric}」指标触发异动（规则 {rule}，"
        f"严重度 {a['severity']}）：{delta_s}"
        f"（今值 {_fmt_num(a['today_value'])} vs 基线 {_fmt_num(a['baseline_value'])}"
        f"，滚动窗口 {_fmt_num(a['baseline_days'])} 天，数据截至 {_fmt_ts(a['as_of']) or '未标'}）。"
        + (f"引擎描述：{a['description']}" if a["description"] else "")
    )

    # 模板化 hypothesis（拆成三段返回，前端可分别渲染）
    full_hyp = _match_analysis_hypothesis(metric, rule)
    parts = {"hypothesis": full_hyp, "unaddressed_confounders": None, "falsification": None}
    # 拆三段（按"未排除混杂"/"要证实需对比"切，纯文本切分，失败回退整段）
    try:
        hyp_part = full_hyp
        if "未排除混杂" in full_hyp:
            hyp_part, rest = full_hyp.split("未排除混杂", 1)
            conf_rest = "未排除混杂" + rest
            if "要证实需对比" in conf_rest:
                conf_part, fals_part = conf_rest.split("要证实需对比", 1)
                parts["unaddressed_confounders"] = conf_part.strip()
                parts["falsification"] = "要证实需对比" + fals_part.strip()
            else:
                parts["unaddressed_confounders"] = conf_rest.strip()
        parts["hypothesis"] = hyp_part.strip()
    except Exception:
        pass

    # 近 28 天该指标趋势（同 SKU 口径）
    series_out: dict = {"series": [], "baseline": {}}
    try:
        series_out = await _metric_series(pool, metric, a["sku_id"], platform, 28)
    except Exception as exc:
        logger.warning("explain_anomaly 趋势序列失败（继续）: %s", exc)

    return {
        "ok": True,
        "anomaly": {
            "id": int(a["id"]),
            "sku_id": a["sku_id"],
            "metric_name": metric,
            "rule_id": rule,
            "severity": a["severity"],
            "platform": platform,
            "delta_pct": float(delta) if delta is not None else None,
            "baseline_value": float(a["baseline_value"]) if a["baseline_value"] is not None else None,
            "today_value": float(a["today_value"]) if a["today_value"] is not None else None,
            "baseline_days": a["baseline_days"],
            "as_of": _fmt_ts(a["as_of"]),
            "detected_at": _fmt_ts(a["detected_at"]),
            "handled": a["handled"],
            "expected": a["expected"],
        },
        "observation": observation,
        "hypothesis": parts["hypothesis"],
        "unaddressed_confounders": parts["unaddressed_confounders"],
        "falsification": parts["falsification"],
        "recent_series": series_out["series"],
        "baseline": series_out["baseline"],
        "note": ("R-14：observation 是库内相关事实，hypothesis 是模板化假设（非 LLM 生成、非断言）。"
                 "未排除混杂因子需老板按 falsification 自行对比验证。单平台抖音口径（§8.5）。"),
    }
