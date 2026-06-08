"""
APScheduler setup for scout-agent.

Scheduled jobs:
  - Daily 08:30 — run all runbook-suite/*.yaml runbooks
  - Daily 02:00 — run pending 7-day verifications
  - Daily 08:00 — sku_bootstrapper incremental sync
  - Weekly Sun 23:00 — focus_pool_builder rebuild
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

log = logging.getLogger(__name__)
_scheduler = AsyncIOScheduler()


async def _run_all_runbook_suites() -> None:
    from app.services.runbook_loader import load_all
    from app.services.runbook_executor import RunbookExecutor
    suites = [(rb_id, rb) for rb_id, rb in load_all() if rb_id.startswith("runbook-suite/")]
    log.info("scheduler: running %d runbook-suite entries", len(suites))
    for rb_id, rb in suites:
        try:
            executor = RunbookExecutor(rb, rb_id)
            await executor.run()
        except Exception as exc:
            log.error("scheduler: runbook %s failed: %s", rb_id, exc)


async def _run_verifications() -> None:
    from app.services.verification import run_pending_verifications
    await run_pending_verifications()


async def _run_sku_bootstrap() -> None:
    from app.services.sku_bootstrapper import bootstrap_skus
    await bootstrap_skus()


async def _run_focus_pool() -> None:
    from app.services.focus_pool_builder import rebuild_focus_pool
    await rebuild_focus_pool()


async def _run_dual_track_merge() -> None:
    from app.services.dual_track_merger import merge_pending
    await merge_pending()


async def _run_auth_health() -> None:
    """每日 cookie 健康检查：探针真取数判活 → 失效则告警 + 写 mvp_session.health。失败容忍。
    排在 metric_ingest(09:00) 之前(08:50)，cookie 隔夜死了能先告警，老板重登后当天数据照常落。"""
    from app.routers.fetch import _EXECUTOR
    from app.services.auth_health import check_auth_health
    if _EXECUTOR is None:
        log.warning("scheduler: auth_health skipped (live_fetch executor 未初始化)")
        return
    try:
        res = await check_auth_health(_EXECUTOR)
        if res.get("stale_auth"):
            log.warning("scheduler: auth_health 检出失效平台 %s（已告警）", res["stale_auth"])
        else:
            log.info("scheduler: auth_health 三平台登录态正常")
    except Exception as exc:
        log.error("scheduler: auth_health failed: %s", exc)


async def _run_metric_ingest() -> None:
    """落库桥日级 ingest：实时取 10 端点 → 29 抽取器 + 同行标杆 → upsert 两表。失败容忍。"""
    from app.routers.fetch import _EXECUTOR
    from app.services.metric_ingest import ingest_metrics
    if _EXECUTOR is None:
        log.warning("scheduler: metric_ingest skipped (live_fetch executor 未初始化)")
        return
    try:
        res = await ingest_metrics(_EXECUTOR)
        log.info("scheduler: metric_ingest wrote %s metric + %s benchmark rows",
                 res.get("metric_rows_written"), res.get("benchmark_rows_written"))
    except Exception as exc:
        log.error("scheduler: metric_ingest failed: %s", exc)


def start_scheduler() -> None:
    if not settings.enable_scheduler:
        log.info("scheduler disabled (ENABLE_SCHEDULER=false)")
        return

    tz = "Asia/Shanghai"
    _scheduler.add_job(
        _run_all_runbook_suites,
        CronTrigger.from_crontab("30 8 * * *", timezone=tz),
        id="daily-runbooks",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_verifications,
        CronTrigger.from_crontab("0 2 * * *", timezone=tz),
        id="daily-verification",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_sku_bootstrap,
        CronTrigger.from_crontab("0 8 * * *", timezone=tz),
        id="daily-sku-bootstrap",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_focus_pool,
        CronTrigger.from_crontab("0 23 * * 0", timezone=tz),
        id="weekly-focus-pool",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_dual_track_merge,
        CronTrigger.from_crontab("0 3 * * *", timezone=tz),
        id="daily-dual-track-merge",
        replace_existing=True,
    )
    # cookie 健康检查：每天 08:50（ingest 前 10 分钟）探针判活，失效告警 + 写 mvp_session.health
    _scheduler.add_job(
        _run_auth_health,
        CronTrigger.from_crontab("50 8 * * *", timezone=tz),
        id="daily-auth-health",
        replace_existing=True,
    )
    # 落库桥：每天 09:00 全量 ingest（罗盘/云图/抖店登录态有效时落库；失败容忍）
    _scheduler.add_job(
        _run_metric_ingest,
        CronTrigger.from_crontab("0 9 * * *", timezone=tz),
        id="daily-metric-ingest",
        replace_existing=True,
    )

    _scheduler.start()
    log.info("scheduler started with %d jobs", len(_scheduler.get_jobs()))


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
