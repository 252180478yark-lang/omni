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

    _scheduler.start()
    log.info("scheduler started with %d jobs", len(_scheduler.get_jobs()))


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
