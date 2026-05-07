"""W4-B 切片 4：weekly_self_review 后台 cron。

design doc §7.4 反馈循环：每周自动跑一次 agent_self_review，把结果渲染成
markdown 写到 data/agent_state/weekly_review.md（覆盖式），老板进 omni
工作目录直接 cat 看。

设计取舍（个人自用，禁止过度工程）：
- 不引入 APScheduler / celery；KE 容器 lifespan startup 起一个后台 asyncio
  task，每小时唤醒一次检查 last_run，距今 ≥ 7 天就跑
- last_run 持久化到 data/agent_state/last_weekly_review.txt（ISO 时间戳），
  容器重启不丢节奏
- 老板关电脑/容器停 → 不跑就不跑（不是 SLA 服务）
- 失败不抛、log warning 后 sleep 继续（不能因为 review 错误把容器拉挂）
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

AGENT_STATE_DIR = Path("/app/agent_state")
LAST_RUN_FILE = AGENT_STATE_DIR / "last_weekly_review.txt"
WEEKLY_REPORT_FILE = AGENT_STATE_DIR / "weekly_review.md"

WEEKLY_REVIEW_INTERVAL_DAYS = 7
CHECK_INTERVAL_SECONDS = 3600  # 每小时检查一次
REVIEW_PERIOD_DAYS = 7


def _read_last_run() -> datetime | None:
    """读 last_run 文件返 aware datetime；解析失败或文件不存在返 None。"""
    if not LAST_RUN_FILE.exists():
        return None
    try:
        text = LAST_RUN_FILE.read_text(encoding="utf-8").strip()
        # 支持 "2026-05-07T12:34:56+00:00" 与 "2026-05-07T12:34:56Z" 两种
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        logger.warning("last_weekly_review.txt 解析失败，视为从未跑过", exc_info=True)
        return None


def _write_last_run(ts: datetime) -> None:
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(ts.astimezone(timezone.utc).isoformat(), encoding="utf-8")


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
