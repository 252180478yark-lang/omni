"""投后 ad_metrics 入库校验（蓝图 §1.4 留痕+入库校验 / §5 白名单 / R-4 拒手填 roi）。

蓝图把宪法第 4 条从"留痕"升级为"留痕 + 入库校验"：所有人工/抓取注入的关键指标
（ad_metrics / 成本 / 抓来的 GMV）入库时必须过**合理性校验关卡**（上下界、非负等），
越界的标 `存疑` **不进分析面聚合**。

设计原则（**fail-open**，对齐现有 record_ad_metrics 的容错风格）：
- **绝不拒收/丢数据**——所有 key 照常入库（保持 record_ad_metrics 的 jsonb `||` 合并不变），
  只在合并体里多挂一个 `_validation` 元数据块标出哪些 key 存疑/未知，
  分析层据此把存疑 key 排除出聚合（蓝图 §1.4「越界的标存疑不进聚合」）。
- **显式告警不静默**（蓝图 §4 L0-3）：存疑 key 走 logger.warning。
- **R-4 拒手填 roi**：roi 应由后端按唯一口径算，不接受手填。手填的 roi 标 suspect
  （reason=hand_filled_roi），仍保留原值可见，但不进聚合——既守 R-4 又不暗自丢老板的数据。

不改任何现有列/返回字段；纯加 `_validation` 软元数据 + 返回一份 report 给调用方看。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── 白名单：key -> (kind, 下界, 上界) ────────────────────────────────────────
# kind: rate(比率 0..1) / pct(百分数 0..100) / money(金额 >=0) / count(计数 >=0) /
#       computed(后端算的，拒手填) / meta(文本/标注，不校验数值)
# 上界用宽松工程上界（防脏数据 NaN/天文数字），不是业务硬约束。None = 不设上界。
_WHITELIST: dict[str, tuple[str, float | None, float | None]] = {
    # —— 后端算、拒手填（R-4）——
    "roi": ("computed", 0.0, 1000.0),
    "roas": ("computed", 0.0, 1000.0),
    # —— 金额（>=0）——
    "gmv": ("money", 0.0, None),
    "gmv_paid": ("money", 0.0, None),
    "spend": ("money", 0.0, None),
    "cost": ("money", 0.0, None),
    "ad_cost": ("money", 0.0, None),
    "revenue": ("money", 0.0, None),
    "profit": ("money", None, None),  # 利润可负
    # —— 计数（>=0）——
    "plays": ("count", 0.0, None),
    "play_count": ("count", 0.0, None),
    "impressions": ("count", 0.0, None),
    "views": ("count", 0.0, None),
    "clicks": ("count", 0.0, None),
    "orders": ("count", 0.0, None),
    "conversions": ("count", 0.0, None),
    "likes": ("count", 0.0, None),
    "comments": ("count", 0.0, None),
    "shares": ("count", 0.0, None),
    "follows": ("count", 0.0, None),
    # —— 比率类（单位约定 0..1 还是 0..100 由老板口径决定、未钉死=T2，故用宽松 0..100 上界：
    #    只拦明确垃圾（负数 / NaN / >100 的绝对越界），不按假定单位误判 5% 写成 5 的情况）——
    "ctr": ("rate", 0.0, 100.0),
    "cvr": ("rate", 0.0, 100.0),
    "completion_rate": ("rate", 0.0, 100.0),
    "play_rate": ("rate", 0.0, 100.0),
    "like_rate": ("rate", 0.0, 100.0),
    "conversion_rate": ("rate", 0.0, 100.0),
    "a3_ratio": ("rate", 0.0, 100.0),
    "play_3s_rate": ("rate", 0.0, 100.0),
    "play_5s_rate": ("rate", 0.0, 100.0),
    "play_25pct_rate": ("rate", 0.0, 100.0),
    "play_50pct_rate": ("rate", 0.0, 100.0),
    "play_75pct_rate": ("rate", 0.0, 100.0),
    "ctr_pct": ("pct", 0.0, 100.0),
    "cvr_pct": ("pct", 0.0, 100.0),
    "completion_rate_pct": ("pct", 0.0, 100.0),
    # —— 投放成本类（对齐 ad-review csv_parser 的 decimal_fields；金额 >=0）——
    "cost_per_result": ("money", 0.0, None),
    "a3_cost": ("money", 0.0, None),
    "direct_pay_amount": ("money", 0.0, None),
    "cpm": ("money", 0.0, None),
    "cpc": ("money", 0.0, None),
    "gpm": ("money", 0.0, None),
    # 后端算的 ROI 类（R-4 拒手填，同 roi/roas）
    "direct_pay_roi": ("computed", 0.0, 1000.0),
    # 计数类（对齐 csv_parser int_fields）
    "front_impressions": ("count", 0.0, None),
    "effective_plays": ("count", 0.0, None),
    "play_complete": ("count", 0.0, None),
    "play_3s": ("count", 0.0, None),
    "play_25pct": ("count", 0.0, None),
    "play_50pct": ("count", 0.0, None),
    "play_75pct": ("count", 0.0, None),
    "new_a3": ("count", 0.0, None),
    "new_followers": ("count", 0.0, None),
    "direct_orders": ("count", 0.0, None),
    "shares_7d": ("count", 0.0, None),
    # —— 标注/文本（不校验数值）——
    "platform": ("meta", None, None),
    "campaign": ("meta", None, None),
    "campaign_id": ("meta", None, None),
    "note": ("meta", None, None),
    "data_level": ("meta", None, None),  # R-17：计划级/含自然流量 标注
    "as_of": ("meta", None, None),       # R-30：数据新鲜度
    "source": ("meta", None, None),
    "currency": ("meta", None, None),
}

# 内部元数据 key，跳过校验（本模块自己写的 / 历史保留）
_INTERNAL_KEYS = {"_validation", "_suspect"}


def _to_number(value: Any) -> float | None:
    """尽量转 float；转不了返 None（非数值 key 自然落到这里）。"""
    if isinstance(value, bool):
        # bool 是 int 子类，但当指标值多半是误传 → 不当数值
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
            return None
        return f
    if isinstance(value, str):
        s = value.strip().rstrip("%").replace(",", "")
        try:
            f = float(s)
        except ValueError:
            return None
        # 字符串 'NaN'/'inf' 也能被 float() 接受 → 同样拦掉（否则滑过边界检查进 ok）
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    return None


def validate_ad_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """校验一批 ad_metrics，返回 report（不改入参）。

    返回:
      {
        "suspect": {key: {"value":..., "reason":...}},   # 越界/手填roi/NaN → 不进聚合
        "unknown_keys": [key, ...],                        # 不在白名单（拼写漂移嫌疑），仍入库
        "ok_keys": [key, ...],                             # 通过校验
        "checked_at": iso 字符串（由调用侧补，留空这里不依赖时钟）
      }
    """
    suspect: dict[str, Any] = {}
    unknown: list[str] = []
    ok: list[str] = []

    for key, raw in (metrics or {}).items():
        if key in _INTERNAL_KEYS:
            continue
        spec = _WHITELIST.get(key)
        if spec is None:
            unknown.append(key)
            continue
        kind, lo, hi = spec

        if kind == "meta":
            ok.append(key)
            continue

        if kind == "computed":
            # R-4：roi/roas 应后端算，拒手填。标 suspect 不进聚合，但保留原值可见。
            suspect[key] = {
                "value": raw,
                "reason": f"hand_filled_{key}（R-4：{key} 应由后端按唯一口径算，不接受手填，不进聚合）",
            }
            continue

        num = _to_number(raw)
        if num is None:
            suspect[key] = {"value": raw, "reason": "not_a_number（NaN/inf/非数值，不进聚合）"}
            continue
        if lo is not None and num < lo:
            suspect[key] = {"value": raw, "reason": f"below_min（< {lo}）"}
            continue
        if hi is not None and num > hi:
            suspect[key] = {"value": raw, "reason": f"above_max（> {hi}，疑脏数据）"}
            continue
        ok.append(key)

    report: dict[str, Any] = {"suspect": suspect, "unknown_keys": unknown, "ok_keys": ok}
    if suspect:
        logger.warning(
            "ad_metrics 校验：%d 个 key 存疑不进聚合 → %s",
            len(suspect),
            {k: v["reason"] for k, v in suspect.items()},
        )
    if unknown:
        logger.warning(
            "ad_metrics 校验：%d 个未知 key（不在白名单，疑拼写漂移，仍入库）→ %s",
            len(unknown), unknown,
        )
    return report
