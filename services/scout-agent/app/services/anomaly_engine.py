"""
Anomaly detection — 13 rules (v1.4 final).

Called after each daily data ingestion run.
Writes to mvp_anomaly + auto-creates a mvp_decision_log entry for each fired rule.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from app.database import get_pool

log = logging.getLogger(__name__)


# 异动检测滚动 baseline 窗口（天数）。
# 设为 3 让冷启动后第 3 天即可全量触发；后续若数据稳定可调回 7。
BASELINE_DAYS = 3


@dataclass
class Rule:
    id: str
    metric: str
    severity: str
    template: str
    check: Callable[..., bool]
    needs_trend: bool = False  # True = pass list of daily values, False = (today, avg_baseline)


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
        template="用户支付金额跌幅 {delta_pct:.0f}% vs 近3日均值",
        check=lambda today, avg7: avg7 > 0 and today < avg7 * 0.75,
    ),
    Rule(
        id="gmv_surge_50",
        metric="gmv_paid",
        severity="positive",
        template="用户支付金额涨幅 {delta_pct:.0f}%",
        check=lambda today, avg7: avg7 > 0 and today > avg7 * 1.5,
    ),
    Rule(
        id="ctr_3day_decline",
        metric="ctr",
        severity="urgent",
        template="CTR 连续3天下滑",
        check=lambda values: _is_consecutive_decline(values, 3),
        needs_trend=True,
    ),
    Rule(
        id="kpi_3day_improve",
        metric="gmv_paid",
        severity="positive",
        template="用户支付金额连续3天改善",
        check=lambda values: _is_consecutive_improve(values, 3),
        needs_trend=True,
    ),
    Rule(
        id="zero_traffic",
        metric="uv",
        severity="urgent",
        template="异常无流量，可能下架/限流（UV=0）",
        check=lambda today, avg7: today == 0 and avg7 > 0,
    ),
    Rule(
        id="negative_reviews",
        metric="review_count",
        severity="warning",
        template="新增差评 {today:.0f} 条",
        check=lambda today, avg7: today >= 3,
    ),
    # 抖店后台 rules
    Rule(
        id="logistics_overdue_alert",
        metric="logistics_overdue_orders",
        severity="warning",
        template="今日超时单 {today:.0f} 单",
        check=lambda today, avg7: today > 3,
    ),
    Rule(
        id="experience_score_drop",
        metric="experience_score",
        severity="urgent",
        template="体验分 {today:.1f} 低于4.0",
        check=lambda today, avg7: today > 0 and today < 4.0,
    ),
    Rule(
        id="todo_overflow",
        metric="todo_pending_ship",
        severity="warning",
        template="待发货 {today:.0f} 单堆积",
        check=lambda today, avg7: today > 5,
    ),
    # 云图 rules
    Rule(
        id="5a_asset_3day_decline",
        metric="asset_5a_total",
        severity="urgent",
        template="5A 总资产规模连续3天下行",
        check=lambda values: _is_consecutive_decline(values, 3),
        needs_trend=True,
    ),
    Rule(
        id="flow_acquire_under_industry_30pct",
        metric="flow_acquire",
        severity="warning",
        template="拉新场景流转量低于行业均值30%",
        check=lambda today, avg7: today > 0 and avg7 > 0 and today < avg7 * 0.7,
    ),
    Rule(
        id="mind_3day_decline",
        metric="mind_brand_assoc",
        severity="warning",
        template="品牌联想量连续3天下行",
        check=lambda values: _is_consecutive_decline(values, 3),
        needs_trend=True,
    ),
    Rule(
        id="touchpoint_imbalance_80pct",
        metric="touchpoint_traffic_share_ad",
        severity="warning",
        template="触点结构失衡：投放占比 {today:.0%}",
        check=lambda today, avg7: today > 0.8,
    ),
]


# ── Detection ─────────────────────────────────────────────────────────────────

async def detect_anomalies_for_sku(sku_id: str, run_id: str) -> list[int]:
    """Run all rules for one SKU. Returns list of new mvp_anomaly IDs."""
    pool = await get_pool()
    today = date.today() - timedelta(days=1)
    fired: list[int] = []

    async with pool.acquire() as conn:
        for rule in RULES:
            try:
                if rule.needs_trend:
                    values = await _fetch_trend(conn, sku_id, rule.metric, today, days=BASELINE_DAYS)
                    if not values:
                        continue
                    triggered = rule.check(values)
                    today_val = values[-1] if values else 0.0
                    avg7_val = sum(values) / len(values) if values else 0.0
                else:
                    today_val, avg7_val = await _fetch_today_baseline(conn, sku_id, rule.metric, today)
                    if today_val is None:
                        continue
                    triggered = rule.check(today_val, avg7_val)

                if not triggered:
                    continue

                delta_pct = (
                    (today_val - avg7_val) / avg7_val * 100
                    if avg7_val else 0.0
                )
                description = rule.template.format(
                    today=today_val, avg7=avg7_val, delta_pct=delta_pct
                )

                # Insert anomaly
                anomaly_id = await conn.fetchval(
                    """
                    INSERT INTO mvp_anomaly
                        (sku_id, severity, metric_name, rule_id, description, delta_pct)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """,
                    sku_id, rule.severity, rule.metric, rule.id, description, delta_pct,
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


async def detect_all_focus_skus(run_id: str) -> None:
    """Run anomaly detection for all SKUs in the focus pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM mvp_sku WHERE in_focus_pool = TRUE AND status = 'active'")
    for row in rows:
        await detect_anomalies_for_sku(row["id"], run_id)


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


async def _fetch_today_baseline(conn, sku_id: str, metric_name: str, today: date) -> tuple[float | None, float]:
    """取 today 当日值 + 过去 BASELINE_DAYS 天滚动均值（不含今日）。"""
    row = await conn.fetchrow(
        f"""
        SELECT
            MAX(value) FILTER (WHERE date = $3) AS today_val,
            AVG(value) FILTER (
                WHERE date BETWEEN $3 - INTERVAL '{BASELINE_DAYS} days' AND $3 - INTERVAL '1 day'
            ) AS avg_baseline
        FROM mvp_daily_metric
        WHERE sku_id = $1 AND metric_name = $2
          AND date BETWEEN $3 - INTERVAL '{BASELINE_DAYS} days' AND $3
        """,
        sku_id, metric_name, today,
    )
    if row is None:
        return None, 0.0
    return (float(row["today_val"]) if row["today_val"] is not None else None,
            float(row["avg_baseline"]) if row["avg_baseline"] is not None else 0.0)


async def _fetch_trend(conn, sku_id: str, metric_name: str, today: date, days: int) -> list[float]:
    rows = await conn.fetch(
        """
        SELECT date, value FROM mvp_daily_metric
        WHERE sku_id=$1 AND metric_name=$2
          AND date BETWEEN $3 - INTERVAL '%s days' AND $3
        ORDER BY date ASC
        """ % days,
        sku_id, metric_name, today,
    )
    return [float(r["value"]) for r in rows if r["value"] is not None]
