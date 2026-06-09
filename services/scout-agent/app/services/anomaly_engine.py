"""
Anomaly detection — 13 rules (v1.4 + 异动引擎升级 2026-06-02).

Called after each daily data ingestion run.
Writes to mvp_anomaly + auto-creates a mvp_decision_log entry for each fired rule.

本次升级（蓝图 §6.1 命根子 + R-18 阈值治理 + R-30 数据新鲜度，纯加法向后兼容）：
- R-18 滚动基线：BASELINE_DAYS 拉到 28（env 可配，数据不足自动降到可用天数不崩）。
  "相对/趋势类"规则改成基于滚动基线统计判定（rolling mean+std z-score，偏离 > k*std
  才 fire，并保留最小变动百分比门槛防平稳指标噪声）。绝对业务规则（体验分<4.0、
  差评>=3、UV=0 等）保留原阈值。所有阈值集中进 CONFIG，别散落魔法数字。
- R-18 断更守卫：跑规则前查新鲜度——目标日(昨天)无该指标行、或最新数据过期
  (latest < 目标日 - STALE_MAX_DAYS) → 跳过该指标检出，不产异常（避免断更误报）。
- R-30 新鲜度：fire 时写 as_of / platform / baseline_days / baseline_value / today_value。
- R-18 自学习抑制：fire 前查 mvp_expected_event，命中则抑制（不插异常行，log 一笔）。

对外签名零改动：detect_all_focus_skus(run_id) / detect_anomalies_for_sku(sku_id, run_id)。
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable

from app.database import get_pool

log = logging.getLogger(__name__)


# ── 可调 config（所有阈值集中此处，别散落魔法数字）──────────────────────────────

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


# 滚动 baseline 窗口（天数）。R-18：默认 28；数据不足时自动降到实际可用天数。
BASELINE_DAYS = _env_int("ANOMALY_BASELINE_DAYS", 28)

# z-score 阈值：滚动 mean+std，|today - mean| > Z_THRESHOLD * std 才算偏离。
Z_THRESHOLD = _env_float("ANOMALY_Z_THRESHOLD", 2.5)

# 最小变动百分比门槛：平稳指标 std 极小时 z-score 易爆，必须同时偏离均值 ≥ 此比例
# 才 fire，防噪声。0.20 = 20%。
MIN_DELTA_PCT = _env_float("ANOMALY_MIN_DELTA_PCT", 0.20)

# 统计判定最少样本天数：baseline 样本不足这么多天，相对类规则跳过（样本太少不可信）。
MIN_BASELINE_SAMPLES = _env_int("ANOMALY_MIN_BASELINE_SAMPLES", 3)

# R-18 断更守卫：最新数据距目标日超过这么多天 = 过期，跳过该指标检出（不误报）。
STALE_MAX_DAYS = _env_int("ANOMALY_STALE_MAX_DAYS", 2)

# 平台维度（当前底座只 douyin；schema 已留 platform 列待多平台）。
DEFAULT_PLATFORM = os.environ.get("ANOMALY_PLATFORM", "douyin").strip() or "douyin"


@dataclass
class Rule:
    id: str
    metric: str
    severity: str
    template: str
    # check 签名按 kind 不同：
    #   kind="absolute" → check(today, avg_baseline) -> bool（绝对业务阈值，原样保留）
    #   kind="trend"    → check(values) -> bool（连续上升/下滑趋势）
    #   kind="relative" → check 不用（走滚动基线 z-score 统计判定，见 _relative_fire）
    check: Callable[..., bool] | None = None
    needs_trend: bool = False  # True = 传 list；False = 传 (today, avg)
    # kind 决定走哪条判定路径：
    #   "absolute" 绝对阈值（体验分/差评/UV=0/堆积单 等）— 保留原样
    #   "trend"    连续趋势（连续 N 天升/降）
    #   "relative" 相对偏离 — 改走滚动基线 mean+std z-score
    kind: str = "absolute"
    direction: str = "both"  # relative 用：'drop'/'surge'/'both'（只关心跌/涨/双向）


# ── Rule definitions ──────────────────────────────────────────────────────────

def _is_consecutive_decline(values: list[float], n: int) -> bool:
    """True if the last n values are strictly descending."""
    if len(values) < n:
        return False
    tail = values[-n:]
    return all(tail[i] > tail[i + 1] for i in range(len(tail) - 1))


def _is_consecutive_improve(values: list[float], n: int, pct: float = 0.05) -> bool:
    if len(values) < n:
        return False
    tail = values[-n:]
    return all(
        tail[i] > 0 and (tail[i + 1] - tail[i]) / tail[i] >= pct
        for i in range(len(tail) - 1)
    )


RULES: list[Rule] = [
    # Compass rules
    Rule(
        id="gmv_drop_25",
        metric="gmv_paid",
        severity="urgent",
        template="用户支付金额异常下跌 {delta_pct:.0f}%（今日 {today:.0f} vs 基线均值 {baseline:.0f}）",
        kind="relative",
        direction="drop",
    ),
    Rule(
        id="gmv_surge_50",
        metric="gmv_paid",
        severity="positive",
        template="用户支付金额异常上涨 {delta_pct:.0f}%（今日 {today:.0f} vs 基线均值 {baseline:.0f}）",
        kind="relative",
        direction="surge",
    ),
    Rule(
        id="ctr_3day_decline",
        metric="ctr",
        severity="urgent",
        template="CTR 连续3天下滑",
        check=lambda values: _is_consecutive_decline(values, 3),
        needs_trend=True,
        kind="trend",
    ),
    Rule(
        id="kpi_3day_improve",
        metric="gmv_paid",
        severity="positive",
        template="用户支付金额连续3天改善",
        check=lambda values: _is_consecutive_improve(values, 3),
        needs_trend=True,
        kind="trend",
    ),
    Rule(
        id="zero_traffic",
        metric="uv",
        severity="urgent",
        template="异常无流量，可能下架/限流（UV=0）",
        check=lambda today, avg7: today == 0 and avg7 > 0,
        kind="absolute",
    ),
    Rule(
        id="negative_reviews",
        metric="review_count",
        severity="warning",
        template="新增差评 {today:.0f} 条",
        check=lambda today, avg7: today >= 3,
        kind="absolute",
    ),
    # 抖店后台 rules
    Rule(
        id="logistics_overdue_alert",
        metric="logistics_overdue_orders",
        severity="warning",
        template="今日超时单 {today:.0f} 单",
        check=lambda today, avg7: today > 3,
        kind="absolute",
    ),
    Rule(
        id="experience_score_drop",
        metric="experience_score",
        severity="urgent",
        template="体验分 {today:.1f} 低于4.0",
        check=lambda today, avg7: today > 0 and today < 4.0,
        kind="absolute",
    ),
    Rule(
        id="todo_overflow",
        metric="todo_pending_ship",
        severity="warning",
        template="待发货 {today:.0f} 单堆积",
        check=lambda today, avg7: today > 5,
        kind="absolute",
    ),
    # 云图 rules
    Rule(
        id="5a_asset_3day_decline",
        metric="asset_5a_total",
        severity="urgent",
        template="5A 总资产规模连续3天下行",
        check=lambda values: _is_consecutive_decline(values, 3),
        needs_trend=True,
        kind="trend",
    ),
    Rule(
        id="flow_acquire_under_industry_30pct",
        metric="flow_acquire",
        severity="warning",
        template="拉新场景流转量异常下行 {delta_pct:.0f}%（今日 {today:.0f} vs 基线均值 {baseline:.0f}）",
        kind="relative",
        direction="drop",
    ),
    Rule(
        id="mind_3day_decline",
        metric="mind_brand_assoc",
        severity="warning",
        template="品牌联想量连续3天下行",
        check=lambda values: _is_consecutive_decline(values, 3),
        needs_trend=True,
        kind="trend",
    ),
    Rule(
        id="touchpoint_imbalance_80pct",
        metric="touchpoint_traffic_share_ad",
        severity="warning",
        template="触点结构失衡：投放占比 {today:.0%}",
        check=lambda today, avg7: today > 0.8,
        kind="absolute",
    ),
]


# ── 统计判定（R-18 滚动基线 z-score，内联算不引统计库，§1.7）──────────────────

def _mean_std(values: list[float]) -> tuple[float, float]:
    """样本均值 + 样本标准差（n-1）。内联算，不引 numpy/statistics。"""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, math.sqrt(var)


def _relative_fire(
    rule: Rule, today_val: float, baseline_values: list[float]
) -> tuple[bool, float, float]:
    """
    相对类规则的滚动基线判定。
    返回 (是否触发, baseline_mean, delta_pct)。
    判定：样本足够 → |today - mean| > Z * std 且 |delta_pct| >= MIN_DELTA_PCT，
    再按 direction（drop/surge/both）筛方向。
    """
    if len(baseline_values) < MIN_BASELINE_SAMPLES:
        return False, 0.0, 0.0

    mean, std = _mean_std(baseline_values)
    if mean <= 0:
        return False, mean, 0.0

    diff = today_val - mean
    delta_pct = diff / mean * 100.0

    # 最小变动百分比门槛：防平稳指标 std 极小时 z-score 噪声爆量。
    if abs(diff) < mean * MIN_DELTA_PCT:
        return False, mean, delta_pct

    # z-score 偏离：std 为 0（历史全相同）时只靠上面的百分比门槛兜底。
    if std > 0 and abs(diff) < Z_THRESHOLD * std:
        return False, mean, delta_pct

    # 方向筛选
    if rule.direction == "drop" and diff >= 0:
        return False, mean, delta_pct
    if rule.direction == "surge" and diff <= 0:
        return False, mean, delta_pct

    return True, mean, delta_pct


# ── Detection ─────────────────────────────────────────────────────────────────

async def detect_anomalies_for_sku(sku_id: str, run_id: str) -> list[int]:
    """Run all rules for one SKU. Returns list of new mvp_anomaly IDs."""
    pool = await get_pool()
    today = date.today() - timedelta(days=1)
    fired: list[int] = []

    async with pool.acquire() as conn:
        for rule in RULES:
            try:
                # ── R-18 断更守卫：先查该指标新鲜度，过期/缺失则跳过（不误报）──
                latest_date = await _latest_metric_date(conn, sku_id, rule.metric, today)
                if latest_date is None:
                    # 该指标从无数据 → 没法判，跳过
                    continue
                if latest_date < today - timedelta(days=STALE_MAX_DAYS):
                    # 最新数据过期（断更）→ 跳过，避免拿陈旧值误报
                    log.info(
                        "freshness skip: sku=%s metric=%s latest=%s target=%s (stale > %d days)",
                        sku_id, rule.metric, latest_date, today, STALE_MAX_DAYS,
                    )
                    continue

                baseline_value: float = 0.0  # 写入 mvp_anomaly.baseline_value 用

                if rule.kind == "trend":
                    values = await _fetch_trend(conn, sku_id, rule.metric, today, days=BASELINE_DAYS)
                    if not values:
                        continue
                    triggered = bool(rule.check(values)) if rule.check else False
                    today_val = values[-1]
                    avg_val = sum(values) / len(values)
                    baseline_value = avg_val
                    delta_pct = (today_val - avg_val) / avg_val * 100 if avg_val else 0.0

                elif rule.kind == "relative":
                    today_val, baseline_values = await _fetch_today_and_baseline_series(
                        conn, sku_id, rule.metric, today
                    )
                    if today_val is None:
                        # 目标日无当日值（虽然历史有数据）→ 断更守卫，跳过
                        continue
                    triggered, baseline_value, delta_pct = _relative_fire(
                        rule, today_val, baseline_values
                    )
                    avg_val = baseline_value

                else:  # absolute
                    today_val, avg_val = await _fetch_today_baseline(conn, sku_id, rule.metric, today)
                    if today_val is None:
                        continue
                    triggered = bool(rule.check(today_val, avg_val)) if rule.check else False
                    baseline_value = avg_val
                    delta_pct = (today_val - avg_val) / avg_val * 100 if avg_val else 0.0

                if not triggered:
                    continue

                description = rule.template.format(
                    today=today_val, avg7=avg_val, baseline=baseline_value, delta_pct=delta_pct
                )

                # ── R-18 自学习抑制：命中预期事件 → 不插异常行 ──
                if await _is_expected(conn, sku_id, rule.metric, rule.id, today):
                    log.info(
                        "anomaly suppressed (expected): sku=%s rule=%s metric=%s date=%s",
                        sku_id, rule.id, rule.metric, today,
                    )
                    continue

                # ── 幂等守卫：同 sku/metric/rule 今天已 fire 过 → 跳过（避免多次触发产生重复行）──
                dup = await conn.fetchval(
                    "SELECT 1 FROM mvp_anomaly WHERE sku_id=$1 AND metric_name=$2 "
                    "AND rule_id=$3 AND detected_at::date = CURRENT_DATE LIMIT 1",
                    sku_id, rule.metric, rule.id,
                )
                if dup:
                    continue

                # ── R-30 新鲜度戳：as_of 取该指标最新数据日 vs 最近成功 runbook，更晚者 ──
                as_of = await _resolve_as_of(conn, sku_id, latest_date)

                # Insert anomaly（新列 platform/as_of/baseline_days/baseline_value/today_value 一并写）
                anomaly_id = await conn.fetchval(
                    """
                    INSERT INTO mvp_anomaly
                        (sku_id, severity, metric_name, rule_id, description, delta_pct,
                         platform, as_of, baseline_days, baseline_value, today_value)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id
                    """,
                    sku_id, rule.severity, rule.metric, rule.id, description, delta_pct,
                    DEFAULT_PLATFORM, as_of, BASELINE_DAYS, baseline_value, today_val,
                )

                # Auto-create decision_log entry (with LLM one-liner if available)
                ai_suggestion = await _llm_one_liner(sku_id, rule.id, description, delta_pct)
                await conn.execute(
                    """
                    INSERT INTO mvp_decision_log
                        (source_module, source_run_id, sku_id, type, title, summary, full_content, status)
                    VALUES ('scout_anomaly', $1, $2, 'anomaly', $3, $4, $5, 'pending')
                    """,
                    run_id, sku_id, description,
                    f"SKU {sku_id} 触发规则 {rule.id}（严重度: {rule.severity}）",
                    ai_suggestion,
                )

                fired.append(anomaly_id)
                log.info("anomaly fired: sku=%s rule=%s severity=%s", sku_id, rule.id, rule.severity)

            except Exception as exc:
                log.warning("rule %s failed for sku %s: %s", rule.id, sku_id, exc)

    return fired


async def detect_shop_level(run_id: str) -> list[int]:
    """对全店哨兵 '_SHOP_' 跑异动检测（gmv/uv/转化/差评等全店指标）。

    分析面/问数都读 _SHOP_，但 detect_all_focus_skus 此前只扫单 SKU——全店大盘
    （如全店 GMV 暴跌）永远不产异动。这里补上；规则 fail-open，缺该指标自动跳过。
    """
    return await detect_anomalies_for_sku("_SHOP_", run_id)


async def detect_all_focus_skus(run_id: str) -> None:
    """Run anomaly detection for focus-pool SKUs + 全店大盘哨兵 _SHOP_."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM mvp_sku WHERE in_focus_pool = TRUE AND status = 'active'")
    for row in rows:
        await detect_anomalies_for_sku(row["id"], run_id)
    # 全店大盘（分析面/问数读的 _SHOP_ 哨兵）——此前漏扫，补上
    await detect_shop_level(run_id)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _llm_one_liner(sku_id: str, rule_id: str, description: str, delta_pct: float) -> str:
    """Call ai-provider-hub for a 1-sentence action suggestion. Returns '' on failure."""
    try:
        import httpx
        from app.config import settings
        prompt = (
            f"你是一位抖音小店运营专家。以下异动刚被检测到：\n"
            f"SKU: {sku_id}，规则: {rule_id}，描述: {description}，变动幅度: {delta_pct:.1f}%\n\n"
            f"请用一句话（≤40字）给出最优先的行动建议，格式：【建议】..."
        )
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.ai_hub_url}/api/v1/ai/chat/completions",
                json={
                    "provider": "gemini",
                    "model": "gemini-2.0-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 80,
                },
            )
            resp.raise_for_status()
            return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as exc:
        log.debug("_llm_one_liner failed: %s", exc)
        return ""


async def _latest_metric_date(conn, sku_id: str, metric_name: str, target_day: date) -> date | None:
    """该 sku/metric 在 target_day 当天或之前的最新有值日期。无数据返 None（R-18 断更守卫用）。"""
    row = await conn.fetchval(
        """
        SELECT MAX(date) FROM mvp_daily_metric
        WHERE sku_id = $1 AND metric_name = $2 AND value IS NOT NULL AND date <= $3
        """,
        sku_id, metric_name, target_day,
    )
    return row


async def _is_expected(conn, sku_id: str, metric_name: str, rule_id: str, target_day: date) -> bool:
    """
    R-18 自学习抑制：命中 mvp_expected_event 则视为预期。
    通配规则：sku_id/metric_name/rule_id 为 NULL 表示通配；目标日须落在 [start, end] 区间
    （end NULL = 永久）。platform 须匹配。
    """
    hit = await conn.fetchval(
        """
        SELECT 1 FROM mvp_expected_event
        WHERE platform = $1
          AND (sku_id IS NULL OR sku_id = $2)
          AND (metric_name IS NULL OR metric_name = $3)
          AND (rule_id IS NULL OR rule_id = $4)
          AND $5 BETWEEN start_date AND COALESCE(end_date, 'infinity'::date)
        LIMIT 1
        """,
        DEFAULT_PLATFORM, sku_id, metric_name, rule_id, target_day,
    )
    return hit is not None


async def _resolve_as_of(conn, sku_id: str, latest_metric_date: date | None):
    """
    R-30 新鲜度戳：取「该指标最新数据日（转当日末 UTC）」与「最近成功 runbook 的
    ended_at」中更晚者，作为这条异常所依据数据的「截至时间」。
    """
    metric_as_of = None
    if latest_metric_date is not None:
        # date → timestamptz：取该日 23:59:59（数据代表当天，用日末更贴近"截至"语义）
        metric_as_of = datetime.combine(latest_metric_date, time(23, 59, 59), tzinfo=timezone.utc)

    runbook_as_of = await conn.fetchval(
        """
        SELECT MAX(ended_at) FROM mvp_runbook_run
        WHERE status = 'success' AND ended_at IS NOT NULL
        """
    )

    candidates = [c for c in (metric_as_of, runbook_as_of) if c is not None]
    if not candidates:
        return None
    return max(candidates)


async def _fetch_today_baseline(conn, sku_id: str, metric_name: str, today: date) -> tuple[float | None, float]:
    """取 today 当日值 + 过去 BASELINE_DAYS 天滚动均值（不含今日）。absolute 类用。"""
    row = await conn.fetchrow(
        f"""
        SELECT
            MAX(value) FILTER (WHERE date = $3) AS today_val,
            AVG(value) FILTER (
                WHERE date BETWEEN $3::date - INTERVAL '{BASELINE_DAYS} days' AND $3::date - INTERVAL '1 day'
            ) AS avg_baseline
        FROM mvp_daily_metric
        WHERE sku_id = $1 AND metric_name = $2
          AND date BETWEEN $3::date - INTERVAL '{BASELINE_DAYS} days' AND $3
        """,
        sku_id, metric_name, today,
    )
    if row is None:
        return None, 0.0
    return (float(row["today_val"]) if row["today_val"] is not None else None,
            float(row["avg_baseline"]) if row["avg_baseline"] is not None else 0.0)


async def _fetch_today_and_baseline_series(
    conn, sku_id: str, metric_name: str, today: date
) -> tuple[float | None, list[float]]:
    """
    relative 类用：取 today 当日值 + 过去 BASELINE_DAYS 天的全部样本（不含今日）。
    样本是序列（不是均值），交给 _relative_fire 算 mean+std z-score。
    """
    rows = await conn.fetch(
        f"""
        SELECT date, value FROM mvp_daily_metric
        WHERE sku_id = $1 AND metric_name = $2
          AND date BETWEEN $3::date - INTERVAL '{BASELINE_DAYS} days' AND $3
        ORDER BY date ASC
        """,
        sku_id, metric_name, today,
    )
    today_val: float | None = None
    baseline_values: list[float] = []
    for r in rows:
        if r["value"] is None:
            continue
        v = float(r["value"])
        if r["date"] == today:
            today_val = v
        else:
            baseline_values.append(v)
    return today_val, baseline_values


async def _fetch_trend(conn, sku_id: str, metric_name: str, today: date, days: int) -> list[float]:
    rows = await conn.fetch(
        """
        SELECT date, value FROM mvp_daily_metric
        WHERE sku_id=$1 AND metric_name=$2
          AND date BETWEEN $3::date - INTERVAL '%s days' AND $3
        ORDER BY date ASC
        """ % days,
        sku_id, metric_name, today,
    )
    return [float(r["value"]) for r in rows if r["value"] is not None]
