"""W4-B 切片 4 + 11：后台 cron 任务集合。

切片 4：weekly_self_review — design doc §7.4 反馈循环
切片 11：daily_pulse + dynamic_block_refresh — design doc §4.3/§9 W4 验收

每个 cron 各自独立的 loop + last_run 文件，互不影响。

设计取舍（个人自用，禁止过度工程）：
- 不引入 APScheduler / celery；KE 容器 lifespan startup 起多个后台 asyncio
  task，各自每小时唤醒一次检查 last_run，距今 ≥ 周期天数就跑
- last_run 持久化到 data/agent_state/last_*.txt（ISO 时间戳），容器重启
  不丢节奏
- 老板关电脑/容器停 → 不跑就不跑（不是 SLA 服务）
- 失败不抛、log warning 后 sleep 继续（不能因为单次错误把容器拉挂）
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

AGENT_STATE_DIR = Path("/app/agent_state")

# 切片 4：weekly_self_review
LAST_RUN_FILE = AGENT_STATE_DIR / "last_weekly_review.txt"
WEEKLY_REPORT_FILE = AGENT_STATE_DIR / "weekly_review.md"
WEEKLY_REVIEW_INTERVAL_DAYS = 7
REVIEW_PERIOD_DAYS = 7

# 切片 11：daily_pulse
DAILY_PULSE_LAST_FILE = AGENT_STATE_DIR / "last_daily_pulse.txt"
DAILY_PULSE_REPORT_FILE = AGENT_STATE_DIR / "daily_pulse.md"
DAILY_PULSE_INTERVAL_DAYS = 1

# 切片 11：dynamic_block_refresh
DYNAMIC_REFRESH_LAST_FILE = AGENT_STATE_DIR / "last_dynamic_refresh.txt"
DYNAMIC_REFRESH_INTERVAL_DAYS = 7

CHECK_INTERVAL_SECONDS = 3600  # 每小时检查一次（所有 cron 共享）


def _read_last_run(path: Path | None = None) -> datetime | None:
    """读 last_run 文件返 aware datetime；解析失败或文件不存在返 None。

    path 默认为切片 4 weekly_self_review 的 LAST_RUN_FILE；切片 11 daily_pulse /
    dynamic_refresh 显式传 path。注意默认参数在调用时解析（不固定绑定），方便
    测试 monkeypatch 模块级 LAST_RUN_FILE。
    """
    target = path if path is not None else LAST_RUN_FILE
    if not target.exists():
        return None
    try:
        text = target.read_text(encoding="utf-8").strip()
        # 支持 "2026-05-07T12:34:56+00:00" 与 "2026-05-07T12:34:56Z" 两种
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        logger.warning("%s 解析失败，视为从未跑过", target.name, exc_info=True)
        return None


def _write_last_run(ts: datetime, path: Path | None = None) -> None:
    target = path if path is not None else LAST_RUN_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ts.astimezone(timezone.utc).isoformat(), encoding="utf-8")


def _should_run_now(
    last_run: datetime | None,
    now: datetime,
    interval_days: int = WEEKLY_REVIEW_INTERVAL_DAYS,
) -> bool:
    """从未跑过 → True；距今 ≥ interval_days → True；否则 False。"""
    if last_run is None:
        return True
    return (now - last_run) >= timedelta(days=interval_days)


def _render_weekly_markdown(review_result: dict, ts: datetime) -> str:
    """把 agent_self_review 的 result 渲染成 markdown 周报。"""
    r = review_result.get("result") or {}
    period = r.get("period_days", REVIEW_PERIOD_DAYS)
    total = r.get("total_calls", 0)
    by_tool = r.get("by_tool", {}) or {}
    by_status = r.get("by_status", {}) or {}
    by_rating = r.get("by_rating", {}) or {}
    candidates = r.get("candidate_patterns", []) or []

    ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    parts = [
        f"# Weekly Self Review · {ts_str}",
        "",
        f"窗口：最近 **{period} 天**；总调用 **{total}** 次。",
        "",
        "## 按 tool",
    ]
    if by_tool:
        for name, cnt in sorted(by_tool.items(), key=lambda x: -x[1]):
            parts.append(f"- `{name}`: {cnt}")
    else:
        parts.append("- _无_")

    parts.extend(["", "## 按 status"])
    if by_status:
        for k, v in sorted(by_status.items()):
            parts.append(f"- `{k}`: {v}")
    else:
        parts.append("- _无_")

    parts.extend(["", "## 按 user_rating"])
    if by_rating:
        for k, v in sorted(by_rating.items()):
            parts.append(f"- `{k}`: {v}")
    else:
        parts.append("- _无_")

    parts.extend(["", "## 候选 pattern（≥3 次重复 3-tool 滑窗）"])
    if candidates:
        for cand in candidates[:10]:
            seq = " → ".join(cand.get("sequence", []))
            occ = cand.get("occurrences", 0)
            parts.append(f"- {seq}（{occ} 次）")
        parts.append("")
        parts.append("> 高频组合可考虑用 `codify_pattern_to_skill` 升级成 skill。")
    else:
        parts.append("- _无_")

    parts.extend(["", "---", "_由 KE cron weekly_self_review 后台任务自动写入。_"])
    return "\n".join(parts) + "\n"


async def _run_one_cycle(now: datetime | None = None) -> dict:
    """单次执行：调 agent_self_review + 写 markdown + 更新 last_run。

    返回 {"ran": bool, "reason": str, "report_path": str?}。
    """
    if now is None:
        now = datetime.now(timezone.utc)
    last_run = _read_last_run()
    if not _should_run_now(last_run, now):
        delta = now - last_run if last_run else None
        return {
            "ran": False,
            "reason": (
                f"距上次仅 {delta.days}d {delta.seconds // 3600}h，未到周期"
                if delta else "unknown"
            ),
        }

    # 真跑（延迟 import 避开 module 加载循环 + 给测试 mock 入口）
    from app.mcp.tools.agent_meta import agent_self_review

    try:
        review = await agent_self_review(period_days=REVIEW_PERIOD_DAYS)
    except Exception:
        logger.exception("weekly_self_review 调 agent_self_review 失败")
        return {"ran": False, "reason": "agent_self_review_failed"}

    if not review.get("ok"):
        logger.warning("agent_self_review 返非 ok：%s", review.get("error"))
        return {"ran": False, "reason": review.get("error", "review_not_ok")}

    md = _render_weekly_markdown(review, now)
    WEEKLY_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_REPORT_FILE.write_text(md, encoding="utf-8")
    _write_last_run(now)
    logger.info("weekly_self_review 写入 %s", WEEKLY_REPORT_FILE)
    return {"ran": True, "reason": "ok", "report_path": str(WEEKLY_REPORT_FILE)}


async def weekly_self_review_loop(
    *,
    check_interval_seconds: int = CHECK_INTERVAL_SECONDS,
) -> None:
    """后台无限循环：每 check_interval 唤醒一次检查是否到期。

    设计：永远不抛异常出循环（异常 log 后 sleep 继续）。被 cancel 时正常退出。
    """
    logger.info(
        "weekly_self_review cron 启动：每 %ds 检查一次，周期 %dd",
        check_interval_seconds,
        WEEKLY_REVIEW_INTERVAL_DAYS,
    )
    while True:
        try:
            res = await _run_one_cycle()
            if res.get("ran"):
                logger.info("weekly review 已写入：%s", res.get("report_path"))
            else:
                logger.debug("weekly review 跳过：%s", res.get("reason"))
        except asyncio.CancelledError:
            logger.info("weekly_self_review cron 被取消")
            raise
        except Exception:
            logger.exception("weekly_self_review cron 单次循环异常（继续）")
        await asyncio.sleep(check_interval_seconds)


# ============================================================
# 切片 11：daily_pulse cron — 每日店铺脉搏
# ============================================================

def _render_daily_pulse_markdown(
    store_daily: dict,
    brand_mind: dict,
    ts: datetime,
) -> str:
    """渲染店铺脉搏日报 markdown。

    store_daily / brand_mind 是 fetch_compass_store_daily / fetch_yuntu_brand_mind
    的原始返回；本函数容忍它们任一失败，失败时该段写"无数据/拉取失败"。
    """
    ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    parts = [f"# Daily Pulse · {ts_str}", ""]

    # 罗盘全店日报
    parts.append("## 罗盘全店日报（compass）")
    if store_daily.get("ok"):
        r = store_daily.get("result") or {}
        date = r.get("date", "?")
        metrics = r.get("metrics", []) or []
        parts.append(f"日期：**{date}**；共 {len(metrics)} 项指标。")
        parts.append("")
        if metrics:
            for m in metrics:
                name = m.get("metric_name", "?")
                value = m.get("value", "?")
                parts.append(f"- `{name}`: {value}")
        else:
            parts.append("- _无 metrics_")
    else:
        err = store_daily.get("error", "unknown")
        hint = store_daily.get("hint", "")
        parts.append(f"- ❌ 拉取失败：`{err}`")
        if hint:
            parts.append(f"  - hint: {hint}")

    # 云图品牌心智
    parts.extend(["", "## 云图品牌心智（yuntu）"])
    if brand_mind.get("ok"):
        r = brand_mind.get("result") or {}
        date = r.get("date", "?")
        rows = r.get("rows", []) or []
        count = r.get("count", 0)
        parts.append(f"日期：**{date}**；共 {count} 行品牌×SKU 数据。")
        parts.append("")
        # 只列前 5 行避免噪音
        for row in rows[:5]:
            brand = row.get("brand_id", "?")
            sku = row.get("sku_id", "?")
            rep = row.get("reputation", "?")
            pref = row.get("preference", "?")
            conn = row.get("connection", "?")
            parts.append(
                f"- brand=`{brand}` sku=`{sku}`: "
                f"reputation={rep} / preference={pref} / connection={conn}"
            )
        if len(rows) > 5:
            parts.append(f"- _（省略 {len(rows) - 5} 行；查 mvp_brand_mind_daily 全表）_")
    else:
        err = brand_mind.get("error", "unknown")
        hint = brand_mind.get("hint", "")
        parts.append(f"- ❌ 拉取失败：`{err}`")
        if hint:
            parts.append(f"  - hint: {hint}")

    parts.extend([
        "",
        "---",
        "_由 KE cron daily_pulse 后台任务自动写入；数据日期来自 DB 最新一行，"
        "可能不是今日（取决于 scout-agent runbook 抓数频率）。_",
    ])
    return "\n".join(parts) + "\n"


async def _run_daily_pulse_cycle(now: datetime | None = None) -> dict:
    """daily_pulse 单次执行：调 fetch_compass_store_daily + fetch_yuntu_brand_mind
    + 渲染 markdown + 更新 last_run。

    返回 {"ran": bool, "reason": str, "report_path": str?}。
    """
    if now is None:
        now = datetime.now(timezone.utc)
    last_run = _read_last_run(DAILY_PULSE_LAST_FILE)
    if not _should_run_now(last_run, now, DAILY_PULSE_INTERVAL_DAYS):
        delta = now - last_run if last_run else None
        return {
            "ran": False,
            "reason": (
                f"距上次仅 {delta.seconds // 3600}h，未到周期"
                if delta else "unknown"
            ),
        }

    # 真跑（延迟 import 避开 module 加载循环）
    from app.mcp.tools.scout import fetch_compass_store_daily, fetch_yuntu_brand_mind

    try:
        store_daily = await fetch_compass_store_daily()
    except Exception:
        logger.exception("daily_pulse 调 fetch_compass_store_daily 失败")
        store_daily = {"ok": False, "error": "exception", "hint": "见日志"}

    try:
        brand_mind = await fetch_yuntu_brand_mind()
    except Exception:
        logger.exception("daily_pulse 调 fetch_yuntu_brand_mind 失败")
        brand_mind = {"ok": False, "error": "exception", "hint": "见日志"}

    md = _render_daily_pulse_markdown(store_daily, brand_mind, now)
    DAILY_PULSE_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAILY_PULSE_REPORT_FILE.write_text(md, encoding="utf-8")
    _write_last_run(now, DAILY_PULSE_LAST_FILE)
    logger.info("daily_pulse 写入 %s", DAILY_PULSE_REPORT_FILE)
    return {"ran": True, "reason": "ok", "report_path": str(DAILY_PULSE_REPORT_FILE)}


async def daily_pulse_loop(
    *,
    check_interval_seconds: int = CHECK_INTERVAL_SECONDS,
) -> None:
    logger.info(
        "daily_pulse cron 启动：每 %ds 检查一次，周期 %dd",
        check_interval_seconds,
        DAILY_PULSE_INTERVAL_DAYS,
    )
    while True:
        try:
            res = await _run_daily_pulse_cycle()
            if res.get("ran"):
                logger.info("daily_pulse 已写入：%s", res.get("report_path"))
            else:
                logger.debug("daily_pulse 跳过：%s", res.get("reason"))
        except asyncio.CancelledError:
            logger.info("daily_pulse cron 被取消")
            raise
        except Exception:
            logger.exception("daily_pulse cron 单次循环异常（继续）")
        await asyncio.sleep(check_interval_seconds)


# ============================================================
# 切片 11：dynamic_block_refresh cron — 每周刷新 dynamic_block.md
# ============================================================

async def _run_dynamic_refresh_cycle(now: datetime | None = None) -> dict:
    """dynamic_refresh 单次执行：调 _refresh_impl 写 dynamic_block.md + 更新 last_run。

    绕过 require_approval（cron 不能等 approval），直接调 agent_meta._refresh_impl。
    老板看到 dynamic_block.md 被刷新后**手动**粘到 CLAUDE.md（marker 之间）。

    返回 {"ran": bool, "reason": str, "stats": dict?}。
    """
    if now is None:
        now = datetime.now(timezone.utc)
    last_run = _read_last_run(DYNAMIC_REFRESH_LAST_FILE)
    if not _should_run_now(last_run, now, DYNAMIC_REFRESH_INTERVAL_DAYS):
        delta = now - last_run if last_run else None
        return {
            "ran": False,
            "reason": (
                f"距上次仅 {delta.days}d，未到周期"
                if delta else "unknown"
            ),
        }

    from app.mcp.tools.agent_meta import _refresh_impl

    try:
        result = await _refresh_impl()
    except Exception:
        logger.exception("dynamic_refresh 调 _refresh_impl 失败")
        return {"ran": False, "reason": "refresh_failed"}

    if not result.get("ok"):
        logger.warning("_refresh_impl 返非 ok：%s", result.get("error"))
        return {"ran": False, "reason": result.get("error", "refresh_not_ok")}

    _write_last_run(now, DYNAMIC_REFRESH_LAST_FILE)
    stats = (result.get("result") or {}).get("stats") or {}
    logger.info("dynamic_refresh 已写 dynamic_block.md（stats=%s）", stats)
    return {"ran": True, "reason": "ok", "stats": stats}


async def dynamic_block_refresh_loop(
    *,
    check_interval_seconds: int = CHECK_INTERVAL_SECONDS,
) -> None:
    logger.info(
        "dynamic_block_refresh cron 启动：每 %ds 检查一次，周期 %dd",
        check_interval_seconds,
        DYNAMIC_REFRESH_INTERVAL_DAYS,
    )
    while True:
        try:
            res = await _run_dynamic_refresh_cycle()
            if res.get("ran"):
                logger.info("dynamic_refresh 已写入（stats=%s）", res.get("stats"))
            else:
                logger.debug("dynamic_refresh 跳过：%s", res.get("reason"))
        except asyncio.CancelledError:
            logger.info("dynamic_block_refresh cron 被取消")
            raise
        except Exception:
            logger.exception("dynamic_block_refresh cron 单次循环异常（继续）")
        await asyncio.sleep(check_interval_seconds)
