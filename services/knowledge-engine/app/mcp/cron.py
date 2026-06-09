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

# 飞轮 Phase B：feedback_digest — 每周聚类负反馈 + 投后数据，出"本周该改啥"草稿
FEEDBACK_DIGEST_LAST_FILE = AGENT_STATE_DIR / "last_feedback_digest.txt"
FEEDBACK_DIGEST_REPORT_FILE = AGENT_STATE_DIR / "feedback_digest.md"
FEEDBACK_DIGEST_INTERVAL_DAYS = 7

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

    # 顺带预热综合经营分析缓存（owner+operator × 常用窗口 28/30），桌面 AiAnalysisPanel 打开秒返。
    # 独立 try，失败不影响 pulse。
    warmed = 0
    try:
        from app.services import business_analysis_service as _ba, ba_cache as _bac
        for _face in ("owner", "operator"):
            for _days in (28, 30):
                _r = await _ba.generate_business_analysis(face=_face, days=_days, polish=True)
                if _r.get("ok"):
                    _bac.put(_bac.key(_face, _days, "douyin", True, None), _r)
                    warmed += 1
        logger.info("daily_pulse: 预热经营分析缓存 %d 项", warmed)
    except Exception:
        logger.exception("daily_pulse: 预热分析缓存失败（不影响 pulse）")

    return {"ran": True, "reason": "ok", "report_path": str(DAILY_PULSE_REPORT_FILE),
            "analysis_cache_warmed": warmed}


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


# ============================================================
# 飞轮 Phase B：feedback_digest cron — 每周聚类负反馈 + 投后数据出改进草稿
# ============================================================
#
# 设计取舍（关键）：**只聚类 + 出草稿，绝不自动改 prompt/skill**。
# 老板看完 feedback_digest.md 自己决定改哪个 prompt（三通道改）。
# 这是"可改进"层的入口，但改的决定权留在老板手里（反幻觉 + 反过度自动化）。

async def _collect_feedback_digest(now: datetime, lookback_days: int | None = None) -> dict:
    """跑 3 段 SQL 聚类，返 {msg_by_cat, tool_by_cat, asset_perf}。每段独立 try，
    单段失败不影响其他段（表/列缺失容忍）。

    lookback_days：消息级/工具级负反馈的回看窗口（天）。None → 用 cron 默认
    FEEDBACK_DIGEST_INTERVAL_DAYS（7）。diagnose tool 传自定义值时按它取窗口，
    保证"observation 文案标的 N 天"与"实际聚类窗口"一致。投后 asset_perf 固定 30 天。"""
    from app.database import get_pool
    pool = get_pool()
    window = lookback_days if (lookback_days and lookback_days > 0) else FEEDBACK_DIGEST_INTERVAL_DAYS
    out: dict = {"msg_by_cat": [], "tool_by_cat": [], "asset_perf": [], "errors": []}

    # 1. 消息级负反馈 by category（7 天）
    try:
        rows = await pool.fetch(
            """
            SELECT COALESCE(category, 'uncategorized') AS category,
                   count(*) AS n,
                   (array_agg(left(message_text_snapshot, 80)
                              ORDER BY created_at DESC)
                    FILTER (WHERE message_text_snapshot IS NOT NULL))[1:3] AS samples
            FROM mcp.message_feedback
            WHERE rating = 'bad' AND created_at > $1
            GROUP BY 1 ORDER BY n DESC
            """,
            now - timedelta(days=window),
        )
        out["msg_by_cat"] = [dict(r) for r in rows]
    except Exception as exc:
        out["errors"].append(f"msg_by_cat: {exc}")

    # 2. 工具级负反馈 by tool + rating_category（7 天）
    try:
        rows = await pool.fetch(
            """
            SELECT tool_name,
                   COALESCE(rating_category, 'uncategorized') AS rating_category,
                   count(*) AS n
            FROM mcp.tool_calls
            WHERE user_rating = 'bad' AND created_at > $1
            GROUP BY tool_name, 2 ORDER BY n DESC LIMIT 20
            """,
            now - timedelta(days=window),
        )
        out["tool_by_cat"] = [dict(r) for r in rows]
    except Exception as exc:
        out["errors"].append(f"tool_by_cat: {exc}")

    # 3. 投后数据（30 天内有回传的资产，给老板看效果对应哪套内容）
    try:
        rows = await pool.fetch(
            """
            SELECT a.id::text AS asset_id, a.sku_id, a.ad_metrics,
                   a.last_metrics_at,
                   a.script_id::text AS script_id,
                   a.audience_record_id::text AS audience_record_id
            FROM pipeline.assets a
            WHERE a.ad_metrics <> '{}'::jsonb
              AND a.last_metrics_at > $1
            ORDER BY a.last_metrics_at DESC LIMIT 20
            """,
            now - timedelta(days=30),
        )
        out["asset_perf"] = [dict(r) for r in rows]
    except Exception as exc:
        out["errors"].append(f"asset_perf: {exc}")

    return out


def _render_feedback_digest_markdown(data: dict, ts: datetime) -> str:
    ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    parts = [
        f"# Feedback Digest · {ts_str}",
        "",
        f"窗口：最近 **{FEEDBACK_DIGEST_INTERVAL_DAYS} 天**负反馈 + 30 天投后数据。",
        "",
        "> 这是**草稿**：只聚类不自动改。老板看完决定改哪个 prompt（三通道）/ 哪个 skill。",
        "",
        "## 1. 消息级负反馈（按分类）",
    ]
    msg = data.get("msg_by_cat") or []
    if msg:
        for r in msg:
            cat, n = r.get("category"), r.get("n")
            parts.append(f"- **{cat}** × {n}")
            for s in (r.get("samples") or []):
                if s:
                    parts.append(f"  - “{s}”")
        parts.append("")
        parts.append("> 某分类反复出现 → 对应改：prompt_bad 改系统提示 / factual_error 查反幻觉约束 / "
                     "wrong_tool 改 skill 的 tool 串法 / tone_off 查 anti_ai_voice。")
    else:
        parts.append("- _本周无消息级负反馈_")

    parts.extend(["", "## 2. 工具级负反馈（按 tool × 分类）"])
    tools = data.get("tool_by_cat") or []
    if tools:
        for r in tools:
            parts.append(f"- `{r.get('tool_name')}` / {r.get('rating_category')} × {r.get('n')}")
        parts.append("")
        parts.append("> 同一 tool 高频被踩 → 看它的 config/prompts/<tool>.{system,user}.md 是不是该调。")
    else:
        parts.append("- _本周无工具级负反馈（注：桌面工具级 👍👎 若未挂 UI，数据可能偏少）_")

    parts.extend(["", "## 3. 投后数据回传（30 天，哪套内容真带货）"])
    perf = data.get("asset_perf") or []
    if perf:
        for r in perf:
            m = r.get("ad_metrics") or {}
            when = r.get("last_metrics_at")
            when_s = when.astimezone(timezone.utc).strftime("%m-%d") if when else "?"
            parts.append(
                f"- [{when_s}] sku=`{r.get('sku_id')}` asset=`{r.get('asset_id')[:8]}` "
                f"metrics={m}"
            )
        parts.append("")
        parts.append("> ROI/完播率高的那套 → 用 `pipeline_get_asset_lineage` 反查它的卖点+人群+脚本，"
                     "把成功要素固化；低的 → 复盘是卖点选错还是人群圈错。")
    else:
        parts.append("- _无投后回传数据（用 `record_ad_metrics` 把测试投放结果写回来才有）_")

    if data.get("errors"):
        parts.extend(["", "## ⚠ 采集告警"])
        for e in data["errors"]:
            parts.append(f"- {e}")

    parts.extend(["", "---", "_由 KE cron feedback_digest 后台任务自动写入；只聚类不自动改 prompt。_"])
    return "\n".join(parts) + "\n"


async def _run_feedback_digest_cycle(now: datetime | None = None) -> dict:
    """feedback_digest 单次执行：聚类 SQL + 渲染 markdown + 更新 last_run。"""
    if now is None:
        now = datetime.now(timezone.utc)
    last_run = _read_last_run(FEEDBACK_DIGEST_LAST_FILE)
    if not _should_run_now(last_run, now, FEEDBACK_DIGEST_INTERVAL_DAYS):
        delta = now - last_run if last_run else None
        return {
            "ran": False,
            "reason": (f"距上次仅 {delta.days}d，未到周期" if delta else "unknown"),
        }

    try:
        data = await _collect_feedback_digest(now)
    except Exception:
        logger.exception("feedback_digest 采集失败")
        return {"ran": False, "reason": "collect_failed"}

    md = _render_feedback_digest_markdown(data, now)
    FEEDBACK_DIGEST_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_DIGEST_REPORT_FILE.write_text(md, encoding="utf-8")
    _write_last_run(now, FEEDBACK_DIGEST_LAST_FILE)
    logger.info("feedback_digest 写入 %s", FEEDBACK_DIGEST_REPORT_FILE)

    # §6.2 诊断官：周期同时把负反馈+投后聚类成结构化《改进提议》入库（带 R-20 生命周期：
    # dedupe 不堆叠 / 过期归档 / 三态），老板在 web /insights「改进建议」inbox 看 + 拍板。
    # 独立 try：诊断失败不影响 digest 主流程。懒导入避免 import 环（diagnose_service 反向引用本模块）。
    diag_summary = None
    try:
        from app.services.diagnose_service import run_diagnose
        diag_summary = await run_diagnose(
            mode="content", lookback_days=FEEDBACK_DIGEST_INTERVAL_DAYS, persist=True,
        )
        logger.info(
            "feedback_digest: diagnose 持久化提议 created=%s refreshed=%s open=%s",
            diag_summary.get("created"), diag_summary.get("refreshed"),
            diag_summary.get("total_open"),
        )
    except Exception:
        logger.exception("feedback_digest: diagnose 持久化失败（不影响 digest）")

    # §8.5 分析面趋势归因：同周期也跑一次 analysis（lookback=21 对齐 TTL，避免旧提议无声过期）——
    # 让老板周一打开 /insights 同时看到内容改进 + 趋势异动提议，不必手动调。独立 try，失败不影响主流程。
    diag_analysis_summary = None
    try:
        from app.services.diagnose_service import run_diagnose as _run_diag_analysis
        diag_analysis_summary = await _run_diag_analysis(mode="analysis", lookback_days=21, persist=True)
        logger.info(
            "feedback_digest: analysis 提议 created=%s refreshed=%s open=%s",
            diag_analysis_summary.get("created"), diag_analysis_summary.get("refreshed"),
            diag_analysis_summary.get("total_open"),
        )
    except Exception:
        logger.exception("feedback_digest: analysis 诊断失败（不影响 digest）")

    return {"ran": True, "reason": "ok", "report_path": str(FEEDBACK_DIGEST_REPORT_FILE),
            "diagnose": diag_summary, "diagnose_analysis": diag_analysis_summary}


async def feedback_digest_loop(
    *,
    check_interval_seconds: int = CHECK_INTERVAL_SECONDS,
) -> None:
    logger.info(
        "feedback_digest cron 启动：每 %ds 检查一次，周期 %dd",
        check_interval_seconds,
        FEEDBACK_DIGEST_INTERVAL_DAYS,
    )
    while True:
        try:
            res = await _run_feedback_digest_cycle()
            if res.get("ran"):
                logger.info("feedback_digest 已写入：%s", res.get("report_path"))
            else:
                logger.debug("feedback_digest 跳过：%s", res.get("reason"))
        except asyncio.CancelledError:
            logger.info("feedback_digest cron 被取消")
            raise
        except Exception:
            logger.exception("feedback_digest cron 单次循环异常（继续）")
        await asyncio.sleep(check_interval_seconds)
