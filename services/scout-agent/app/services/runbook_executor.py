"""
RunbookExecutor: loads a YAML runbook, drives Playwright, writes results to DB.

Key behaviours:
  - Uses persistent Chromium context (storage_state) so cookies survive across runs.
  - headless=False to avoid bot detection on Douyin/Compass.
  - Each step retries up to 3x with exponential back-off.
  - Sends failure notification via NotificationDispatcher on any step crash.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import uuid
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from app.config import settings
from app.database import get_pool
from app.schemas.runbook import RunbookDefinition, RunbookStep
from app.services.notification import dispatcher

log = logging.getLogger(__name__)

_TODAY = lambda: datetime.now().strftime("%Y-%m-%d")  # noqa: E731


class RunbookExecutor:
    def __init__(
        self,
        runbook: RunbookDefinition,
        rb_id: str,
        parent_ctx: BrowserContext | None = None,
        parent_platform: str | None = None,
    ) -> None:
        """
        parent_ctx + parent_platform: reuse parent's Chromium ctx ONLY when the
        sub-runbook is on the same platform (same user_data_dir). Cross-platform
        sub-runbooks (e.g. yuntu inside a compass suite) launch their own ctx —
        independent user_data_dir means no lock contention anyway.
        """
        self.runbook = runbook
        self.rb_id = rb_id
        self.run_id = str(uuid.uuid4())
        self._step_results: dict[str, str] = {}  # step_id -> file path or value
        same_platform = parent_platform is not None and parent_platform == runbook.platform
        self._parent_ctx = parent_ctx if same_platform else None

    # ── public ────────────────────────────────────────────────────────────────

    async def run(self) -> str:
        """Execute the runbook; returns run_id."""
        await self._record_start()
        log.info("runbook '%s' started run_id=%s", self.rb_id, self.run_id)

        try:
            if self._parent_ctx is not None:
                # Sub-runbook path: reuse parent's Chromium context.
                await self._run_with_ctx(self._parent_ctx)
            else:
                # Top-level path: own the playwright lifecycle.
                async with async_playwright() as p:
                    ctx = await self._launch_context(p)
                    try:
                        await self._run_with_ctx(ctx)
                    finally:
                        try:
                            await ctx.close()
                        except Exception:
                            pass

            await self._record_end("success")
            log.info("runbook '%s' completed run_id=%s", self.rb_id, self.run_id)

        except Exception as exc:
            log.exception("runbook '%s' failed run_id=%s", self.rb_id, self.run_id)
            await dispatcher.broadcast(
                "urgent",
                "Omni 巡店异常",
                f"Runbook [{self.runbook.name}] 执行失败：{str(exc)[:300]}",
                {"runbook": self.rb_id, "run_id": self.run_id},
            )
            await self._record_end("failed", str(exc)[:500])

        return self.run_id

    async def _run_with_ctx(self, ctx: BrowserContext) -> None:
        """Run all steps of this runbook against an already-open Chromium ctx."""
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        if not await self._check_session(page):
            await dispatcher.broadcast(
                "warning",
                "Omni 巡店 — 登录态失效",
                f"Runbook [{self.runbook.name}] 需要重新扫码登录。\n"
                "请在前端 /scout 页面点击「重新登录」。",
                {"runbook": self.rb_id, "platform": self.runbook.platform},
            )
            raise RuntimeError("session_expired")

        for step in self.runbook.steps:
            await asyncio.sleep(random.uniform(1.0, 2.5))  # anti-bot jitter
            # Pass current ctx down so sub_runbook actions can reuse it
            await self._exec_step(page, step, ctx=ctx)

    # ── context / session ─────────────────────────────────────────────────────

    async def _launch_context(self, p) -> BrowserContext:
        session_dir = Path(settings.sessions_dir) / self.runbook.platform
        session_dir.mkdir(parents=True, exist_ok=True)

        # Persistent context loads cookies & localStorage automatically from
        # user_data_dir; storage_state= is NOT supported here (the API rejects
        # it). The login cookies written by sessions._run_relogin land in
        # user_data_dir/Default/Cookies, so they're already available.
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(session_dir / "user_data"),
            headless=settings.playwright_headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        return ctx

    async def _check_session(self, page: Page) -> bool:
        """Cheap pre-flight: only fails on hard signals (login/passport URL).
        Network errors / timeouts -> treat as transient and let actual steps run.
        Many platforms (yuntu in particular) reject Playwright's first request
        with ERR_CONNECTION_CLOSED but accept subsequent SPA-internal navigation."""
        if not self.runbook.session:
            return True
        try:
            await page.goto(
                self.runbook.session.recheck_url,
                wait_until="domcontentloaded", timeout=20000,
            )
            await asyncio.sleep(3)  # let SPA finish initial render before reading url
        except Exception as exc:
            # Network-level failure (CONNECTION_CLOSED, timeout) — don't punish
            # the runbook; let real steps try with their own retry/timeout.
            log.warning("session pre-flight skipped (transient): %s", str(exc)[:120])
            return True

        current = page.url or ""
        # Hard signals: stuck on auth pages
        if any(kw in current.lower() for kw in (
            "/login", "/passport", "/sso", "/account/login", "/select-shop",
        )):
            log.warning("session expired for platform %s (url=%s)",
                        self.runbook.platform, current[:100])
            await self._update_session_health("expired")
            return False
        await self._update_session_health("ok")
        return True

    async def _update_session_health(self, health: str) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE mvp_session SET health=$1, updated_at=NOW() WHERE platform=$2",
                health, self.runbook.platform,
            )

    # ── step execution ────────────────────────────────────────────────────────

    # Best-effort actions: failure does NOT abort runbook (visual capture, UI
    # filtering, LLM vision — runbook still produces useful data via
    # click_and_download / parse_csv / write_metric).
    _NON_FATAL_ACTIONS = {
        "screenshot",
        "click_then_select",
        "multi_select",
        "llm_vision",
        "extract_5a_card",
        "parse_html_table",
    }
    _NON_FATAL_ID_PREFIXES = (
        "select", "screenshot", "filter", "snapshot", "capture",
    )

    def _is_non_fatal(self, step: RunbookStep) -> bool:
        if step.action in self._NON_FATAL_ACTIONS:
            return True
        sid = (step.id or "").lower()
        return any(sid.startswith(p) for p in self._NON_FATAL_ID_PREFIXES)

    async def _exec_step(self, page: Page, step: RunbookStep, ctx: BrowserContext | None = None) -> None:
        attempts = 1 if self._is_non_fatal(step) else 3  # don't waste 3x retry on best-effort
        for attempt in range(attempts):
            try:
                await self._dispatch_step(page, step, ctx=ctx)
                return
            except Exception as exc:
                last_attempt = attempt == attempts - 1
                if last_attempt:
                    if self._is_non_fatal(step):
                        log.warning("step '%s' (best-effort) skipped: %s", step.id, str(exc)[:200])
                        return
                    raise RuntimeError(f"step '{step.id}' failed after {attempts} attempts: {exc}") from exc
                log.warning("step '%s' attempt %d failed: %s", step.id, attempt + 1, exc)
                await asyncio.sleep(2 ** attempt)

    async def _dispatch_step(self, page: Page, step: RunbookStep, ctx: BrowserContext | None = None) -> None:
        action = step.action

        if action == "goto":
            import re as _re
            url = step.url or ""
            # Substitute {VAR_NAME} with os.environ values (supports _CURRENT_* injected by foreach_focus_skus)
            url = _re.sub(r'\{(\w+)\}', lambda m: os.environ.get(m.group(1), m.group(0)), url)
            await page.goto(url, wait_until=step.wait_until, timeout=step.timeout)

        elif action == "sleep":
            # Give SPAs time to finish rendering after a goto. Compass/yuntu both
            # poll endlessly so networkidle never fires; an explicit sleep is the
            # only reliable way to let lazy charts/cards mount before screenshot.
            await asyncio.sleep(max(0.0, step.timeout / 1000.0))

        elif action == "click_then_select":
            await page.click(step.selector)
            await asyncio.sleep(0.5)
            await page.click(f'[data-value="{step.value}"]')

        elif action == "multi_select":
            values = os.environ.get(step.values_env or "", "").split(",")
            values = [v.strip() for v in values if v.strip()]
            for v in values:
                await page.fill(step.selector, v)
                await asyncio.sleep(0.3)
                await page.keyboard.press("Enter")

        elif action == "click_and_download":
            save_path = (step.save_to or "").replace("{date}", _TODAY())
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            async with page.expect_download(timeout=step.timeout) as dl_info:
                await page.click(step.selector)
            download = await dl_info.value
            await download.save_as(save_path)
            self._step_results[step.id] = save_path
            log.info("downloaded: %s", save_path)

        elif action == "parse_csv":
            from app.services.csv_parser import parse_and_write
            csv_path = self._step_results.get(step.file_from or "", step.file or "")
            await parse_and_write(csv_path, step.schema_name or "", step.write_to or "", self.run_id)

        elif action == "screenshot":
            save_path = (step.save_to or "").replace("{date}", _TODAY())
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            sel = (step.selector or "").strip()
            # Wait briefly for SPA content; fallback to full page if locator fails
            saved = False
            if sel and sel.lower() not in ("body", "*", "html"):
                try:
                    el = page.locator(sel).first
                    await el.wait_for(state="visible", timeout=8000)
                    await el.screenshot(path=save_path, timeout=10000)
                    saved = True
                except Exception as exc:
                    log.warning("screenshot selector %r missed (%s); falling back to full page",
                                sel[:60], str(exc)[:80])
            if not saved:
                await asyncio.sleep(2)  # let SPA finish render
                await page.screenshot(path=save_path, full_page=True)
            self._step_results[step.id] = save_path
            log.info("screenshot saved: %s", save_path)

        elif action == "llm_vision":
            from app.services.llm_vision import vision_extract
            img_path = self._step_results.get(step.image_from or "", step.image or "")
            extracted = await vision_extract(img_path, step.prompt or "")
            self._step_results[step.id] = json.dumps(extracted, ensure_ascii=False)

        elif action == "invoke_anomaly_engine":
            from app.services.anomaly_engine import detect_all_focus_skus
            await detect_all_focus_skus(self.run_id)

        elif action == "sub_runbook":
            from app.services.runbook_loader import load_one
            sub_rb = load_one(step.runbook)
            # Reuse current ctx so sub-runbook doesn't relaunch Chromium on the
            # same user_data_dir (which would trigger "Target page closed" because
            # the OS lock is still held by the just-closed instance). Cross-platform
            # sub-runbooks (different user_data_dir) launch fresh — no lock issue.
            sub_exec = RunbookExecutor(
                sub_rb, step.runbook,
                parent_ctx=ctx, parent_platform=self.runbook.platform,
            )
            await sub_exec.run()
            self._step_results.update(sub_exec._step_results)

        elif action == "parse_html_table":
            from app.services.html_parser import extract_table_from_page
            data = await extract_table_from_page(page, step.table_selector or "table")
            self._step_results[step.id] = json.dumps(data, ensure_ascii=False)

        elif action == "extract_5a_card":
            from app.services.html_parser import extract_5a_cards_from_page
            data = await extract_5a_cards_from_page(page, step.card_selector or ".crowd-card")
            self._step_results[step.id] = json.dumps(data, ensure_ascii=False)

        elif action == "sync_skus":
            from app.services.sku_bootstrapper import bootstrap_skus
            count = await bootstrap_skus()
            self._step_results[step.id] = str(count)
            log.info("sync_skus: upserted %d rows", count)

        elif action == "rebuild_focus_pool":
            from app.services.focus_pool_builder import rebuild_focus_pool
            await rebuild_focus_pool()

        elif action == "update_sku_growth":
            # Reads LLM-extracted growth classification JSON and updates mvp_sku.growth_class
            import json as _json
            from app.database import get_pool as _get_pool
            data_raw = self._step_results.get(step.extra.get("data_from", ""), "{}")
            try:
                data = _json.loads(data_raw)
            except Exception:
                return
            pool = await _get_pool()
            async with pool.acquire() as conn:
                for sku_id, growth_class in (data.get("classifications") or {}).items():
                    await conn.execute(
                        "UPDATE mvp_sku SET growth_class=$2, updated_at=NOW() WHERE id=$1",
                        sku_id, growth_class,
                    )

        elif action == "run_dual_track_merge":
            from app.services.dual_track_merger import merge_pending
            await merge_pending()

        elif action == "foreach_focus_skus":
            # Run sub_runbook once per focus-pool SKU, injecting SKU context via env
            from app.services.runbook_loader import load_one
            from app.database import get_pool as _get_pool
            pool = await _get_pool()
            async with pool.acquire() as conn:
                skus = await conn.fetch(
                    "SELECT id, douyin_product_id, name FROM mvp_sku "
                    "WHERE in_focus_pool=TRUE AND status='active'"
                )
            for sku_row in skus:
                os.environ["_CURRENT_SKU_ID"] = sku_row["id"]
                os.environ["_CURRENT_DOUYIN_PRODUCT_ID"] = sku_row["douyin_product_id"] or ""
                os.environ["_CURRENT_SKU_NAME"] = sku_row["name"] or ""
                try:
                    sub_rb = load_one(step.runbook)
                    # Reuse parent ctx only when same platform (see sub_runbook above)
                    sub_exec = RunbookExecutor(
                        sub_rb, step.runbook,
                        parent_ctx=ctx, parent_platform=self.runbook.platform,
                    )
                    await sub_exec.run()
                    self._step_results.update(sub_exec._step_results)
                except Exception as exc:
                    log.warning("foreach_focus_skus: sku=%s runbook=%s failed: %s",
                                sku_row["id"], step.runbook, exc)
            # Clean up env
            for k in ("_CURRENT_SKU_ID", "_CURRENT_DOUYIN_PRODUCT_ID", "_CURRENT_SKU_NAME"):
                os.environ.pop(k, None)

        elif action == "write_metric":
            # Directly write a single metric value extracted from a previous step
            from app.database import get_pool as _get_pool
            _raw_sku = step.extra.get("sku_id") or os.environ.get("_CURRENT_SKU_ID", "")
            sku_id = _raw_sku if _raw_sku else "_SHOP_"  # _SHOP_ = shop-level metric
            metric = step.extra.get("metric_name", "")
            value_raw = self._step_results.get(step.extra.get("value_from", ""), "")
            # If json_field is set, parse value_raw as JSON and extract the field
            json_field = step.extra.get("json_field", "")
            if json_field:
                try:
                    parsed = json.loads(value_raw) if isinstance(value_raw, str) else value_raw
                    value_raw = parsed.get(json_field, "")
                except Exception:
                    return
            if value_raw is None or value_raw == "":
                return
            try:
                value = float(str(value_raw).replace(",", "").replace("%", "").strip())
                if "%" in str(value_raw):
                    value /= 100.0
            except (ValueError, TypeError):
                return
            if not sku_id or not metric:
                return
            pool = await _get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO mvp_daily_metric
                        (sku_id, date, metric_name, value, source_runbook, source_run_id)
                    VALUES ($1, CURRENT_DATE - 1, $2, $3, $4, $5)
                    ON CONFLICT (sku_id, date, metric_name)
                    DO UPDATE SET value=$3, source_runbook=$4, source_run_id=$5
                    """,
                    sku_id, metric, value, self.rb_id, self.run_id,
                )

        elif action == "write_5a_asset":
            from app.database import get_pool as _get_pool
            data_raw = self._step_results.get(step.extra.get("data_from", ""), "{}")
            try:
                data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            except Exception:
                return
            if not data:
                return
            pool = await _get_pool()
            brand_id = os.environ.get("YUNTU_BRAND_ID", settings.yuntu_brand_id)
            sku_id_5a = os.environ.get("_CURRENT_SKU_ID", "")  # '' = brand-level; non-empty = SKU-level
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO mvp_5a_asset_daily
                        (date, brand_id, sku_id,
                         o_count, a1_aware, a2_appeal, a3_ask, a4_act, a5_advocate, total_5a,
                         o_industry_avg, a1_industry_avg, a2_industry_avg,
                         a3_industry_avg, a4_industry_avg, a5_industry_avg,
                         a1_outperform_pct, a2_outperform_pct, a3_outperform_pct,
                         a4_outperform_pct, a5_outperform_pct,
                         raw, created_at)
                    VALUES (CURRENT_DATE-1, $1, $21, $2,$3,$4,$5,$6,$7,$8,
                            $9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,NOW())
                    ON CONFLICT (date, brand_id, sku_id)
                    DO UPDATE SET
                        o_count=$2, a1_aware=$3, a2_appeal=$4, a3_ask=$5,
                        a4_act=$6, a5_advocate=$7, total_5a=$8,
                        a1_outperform_pct=$15, a2_outperform_pct=$16,
                        a3_outperform_pct=$17, a4_outperform_pct=$18, a5_outperform_pct=$19,
                        raw=$20
                    """,
                    brand_id,
                    data.get("o_count"), data.get("a1_aware"), data.get("a2_appeal"),
                    data.get("a3_ask"), data.get("a4_act"), data.get("a5_advocate"),
                    data.get("total_5a"),
                    data.get("o_industry_avg"), data.get("a1_industry_avg"),
                    data.get("a2_industry_avg"), data.get("a3_industry_avg"),
                    data.get("a4_industry_avg"), data.get("a5_industry_avg"),
                    data.get("a1_outperform_pct"), data.get("a2_outperform_pct"),
                    data.get("a3_outperform_pct"), data.get("a4_outperform_pct"),
                    data.get("a5_outperform_pct"),
                    json.dumps(data, ensure_ascii=False),
                    sku_id_5a,
                )

        elif action == "write_5a_flow":
            from app.database import get_pool as _get_pool
            data_raw = self._step_results.get(step.extra.get("data_from", ""), "{}")
            try:
                data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            except Exception:
                return
            scenes = (data or {}).get("scenes", {})
            if not scenes:
                return
            pool = await _get_pool()
            brand_id = os.environ.get("YUNTU_BRAND_ID", settings.yuntu_brand_id)
            async with pool.acquire() as conn:
                for scene_name, vals in scenes.items():
                    if not vals:
                        continue
                    await conn.execute(
                        """
                        INSERT INTO mvp_5a_flow_daily
                            (date, brand_id, sku_id, scene,
                             flow_count, industry_avg, outperform_pct, flow_detail)
                        VALUES (CURRENT_DATE-1, $1, '', $2, $3, $4, $5, $6)
                        ON CONFLICT (date, brand_id, sku_id, scene)
                        DO UPDATE SET
                            flow_count=$3, industry_avg=$4,
                            outperform_pct=$5, flow_detail=$6
                        """,
                        brand_id, scene_name,
                        vals.get("flow_count"), vals.get("industry_avg"),
                        vals.get("outperform_pct"),
                        json.dumps(vals, ensure_ascii=False),
                    )

        elif action == "write_per_sku_metrics":
            # Bulk-write per-SKU metrics from a vision-extracted table.
            # Expects LLM to have produced {"skus":[{"douyin_product_id":..., "<metric>":val,...}]}
            # Resolves douyin_product_id -> mvp_sku.id and writes each non-null
            # metric to mvp_daily_metric (date = CURRENT_DATE - 1).
            from app.database import get_pool as _get_pool
            data_raw = self._step_results.get(step.extra.get("data_from", ""), "{}")
            try:
                data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            except Exception:
                return
            skus_rows = (data or {}).get("skus") or []
            if not skus_rows:
                return
            pool = await _get_pool()
            written = 0
            async with pool.acquire() as conn:
                # Build douyin_product_id -> mvp_sku.id map once
                id_rows = await conn.fetch(
                    "SELECT id, douyin_product_id FROM mvp_sku WHERE douyin_product_id IS NOT NULL"
                )
                pid_to_sku = {r["douyin_product_id"]: r["id"] for r in id_rows}

                for row in skus_rows:
                    pid = str(row.get("douyin_product_id") or "").strip()
                    sku_id = pid_to_sku.get(pid)
                    if not sku_id:
                        continue
                    for metric_name, value_raw in row.items():
                        if metric_name == "douyin_product_id":
                            continue
                        if value_raw is None or value_raw == "":
                            continue
                        try:
                            value = float(str(value_raw).replace(",", "").replace("%", "").strip())
                            if "%" in str(value_raw):
                                value /= 100.0
                        except (ValueError, TypeError):
                            continue
                        await conn.execute(
                            """
                            INSERT INTO mvp_daily_metric
                                (sku_id, date, metric_name, value, source_runbook, source_run_id)
                            VALUES ($1, CURRENT_DATE - 1, $2, $3, $4, $5)
                            ON CONFLICT (sku_id, date, metric_name)
                            DO UPDATE SET value=$3, source_runbook=$4, source_run_id=$5
                            """,
                            sku_id, metric_name, value, self.rb_id, self.run_id,
                        )
                        written += 1
            log.info("write_per_sku_metrics: wrote %d rows from %d SKUs",
                     written, len(skus_rows))

        elif action == "write_brand_mind":
            from app.database import get_pool as _get_pool
            monitor_raw = self._step_results.get(step.extra.get("monitor_from", ""), "{}")
            prefer_raw = self._step_results.get(step.extra.get("prefer_from", ""), "{}")
            try:
                monitor = json.loads(monitor_raw) if isinstance(monitor_raw, str) else monitor_raw
                prefer = json.loads(prefer_raw) if isinstance(prefer_raw, str) else prefer_raw
            except Exception:
                return
            if not monitor:
                return
            pool = await _get_pool()
            brand_id = os.environ.get("YUNTU_BRAND_ID", settings.yuntu_brand_id)
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO mvp_brand_mind_daily
                        (date, brand_id, sku_id,
                         brand_assoc_count, industry_share, industry_rank,
                         reputation, preference, dwell, connection, increase)
                    VALUES (CURRENT_DATE-1, $1, '', $2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (date, brand_id, sku_id)
                    DO UPDATE SET
                        brand_assoc_count=$2, industry_share=$3, industry_rank=$4,
                        reputation=$5, preference=$6,
                        dwell=$7, connection=$8, increase=$9
                    """,
                    brand_id,
                    monitor.get("brand_assoc_count"), monitor.get("industry_share"),
                    monitor.get("industry_rank"),
                    (prefer or {}).get("reputation"), (prefer or {}).get("preference"),
                    monitor.get("dwell"), monitor.get("connection"), monitor.get("increase"),
                )

        else:
            raise ValueError(f"unknown action: {action}")

    # ── DB bookkeeping ────────────────────────────────────────────────────────

    async def _record_start(self) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mvp_runbook_run(id, runbook_name, started_at, status)
                VALUES($1, $2, NOW(), 'running')
                """,
                self.run_id, self.rb_id,
            )

    async def _record_end(self, status: str, error: str | None = None) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE mvp_runbook_run
                SET ended_at=NOW(), status=$2, error=$3
                WHERE id=$1
                """,
                self.run_id, status, error,
            )
