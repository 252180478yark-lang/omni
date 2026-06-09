"""实时取数执行器：cookies → Playwright context → page.evaluate(runner.js) → verdict。"""
from __future__ import annotations

import asyncio
import time
from datetime import date as date_cls
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.services.catalog_loader import CatalogLoader, build_render_context, render_params
from app.services.fetch_verdict import compute_verdict

_RUNNER_JS = (Path(__file__).parent / "runner.js").read_text(encoding="utf-8")

# 平台 → cookies session 目录名（sessions/<name>/storage_state.json）
# 2026-06-03 修阻断 bug：原映射到不存在的 'jinritemai'，对齐 sessions.py relogin 实际写的目录名
# （douyin_compass / douyin_shop_admin），否则 compass/doudian 的 has_cookies 恒 False → 永远 FAIL_AUTH。
_PLATFORM_SESSION = {"yuntu": "yuntu", "compass": "douyin_compass", "doudian": "douyin_shop_admin"}


class LiveFetchExecutor:
    def __init__(self, catalog: CatalogLoader, sessions_root: Path, today: date_cls | None = None):
        self.catalog = catalog
        self.sessions_root = Path(sessions_root)
        self._today = today or date_cls.today()

    # ---- cookies ----
    def storage_state_path(self, platform: str) -> Path:
        name = _PLATFORM_SESSION.get(platform, platform)
        return self.sessions_root / name / "storage_state.json"

    def has_cookies(self, platform: str) -> bool:
        return self.storage_state_path(platform).exists()

    # ---- 浏览器层（真实路径；测试覆写此方法）----
    async def _run_in_page(self, host: str, method: str, url: str, body: Any) -> dict:
        from playwright.async_api import async_playwright

        platform = self._host_platform(host)
        storage = str(self.storage_state_path(platform))
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(storage_state=storage)
            page = await ctx.new_page()
            # 导航到平台域，保证 origin 正确 + 平台 JS 注入签名能力
            await page.goto(f"https://{host}/", wait_until="domcontentloaded", timeout=30000)
            result = await page.evaluate(
                _RUNNER_JS, {"method": method, "url": url, "body": body, "retry": 3}
            )
            await ctx.close()
            await browser.close()
            return result

    @staticmethod
    def _host_platform(host: str) -> str:
        if "oceanengine" in host:
            return "yuntu"
        if "compass" in host:
            return "compass"
        return "doudian"

    # ---- 核心 ----
    async def fetch(
        self,
        platform: str,
        endpoint: str,
        params: dict | None = None,
        body: dict | None = None,
        _force_no_cookies: bool = False,
    ) -> dict:
        entry = self.catalog.get(endpoint)
        if entry is None:
            return {"verdict": "FAIL_OTHER", "error": "endpoint_not_in_catalog",
                    "hint": f"目录无 key={endpoint}，用 list_endpoints 检索",
                    "endpoint_key": endpoint, "status": None, "code": None,
                    "has_data": False, "fields": {}}

        if _force_no_cookies or not self.has_cookies(platform):
            return {"verdict": "FAIL_AUTH", "error": "no_cookies",
                    "hint": f"{platform} 无有效 cookies，去 /scout 扫码登录",
                    "endpoint_key": endpoint, "status": None, "code": None,
                    "has_data": False, "fields": {}}

        host = entry["host"]
        method = (entry.get("method") or "GET").upper()
        ctx = build_render_context(self.catalog.context.get(platform, {}), self._today)
        merged_params = render_params(entry.get("params"), ctx, overrides=params)
        merged_body = body if body is not None else entry.get("body")

        url = f"https://{host}{entry['path']}"
        if merged_params:
            qs = urlencode({k: v for k, v in merged_params.items() if v is not None})
            if qs:
                url += ("&" if "?" in url else "?") + qs

        start = time.monotonic()
        raw = await self._run_in_page(host, method, url, merged_body)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if raw.get("error") and raw.get("status", 0) == 0:
            return {"verdict": "EXCEPTION", "error": raw["error"], "endpoint_key": endpoint,
                    "status": 0, "code": None, "has_data": False, "fields": {},
                    "url": url, "elapsed_ms": elapsed_ms}

        v = compute_verdict(
            raw.get("status", 0), raw.get("ct", ""), raw.get("parsed"),
            raw.get("firstChars", ""), entry.get("expected_fields"),
        )
        return {
            "endpoint_key": endpoint, "platform": platform, "url": url,
            "status": raw.get("status"), "elapsed_ms": elapsed_ms,
            "attempts": raw.get("attempts", 1), **v,
        }

    async def batch(self, requests: list[dict]) -> list[dict]:
        out = []
        for r in requests:
            out.append(await self.fetch(
                platform=r["platform"], endpoint=r["endpoint"],
                params=r.get("params"), body=r.get("body"),
            ))
        return out

    # ---- 落库桥专用：取端点【完整 parsed JSON】（不止 verdict/抽字段）----
    async def fetch_raw(
        self,
        platform: str,
        endpoint: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        """跟 fetch() 同样的 URL 渲染 + 浏览器执行，但返回**整个 parsed JSON**。

        落库桥（metric_ingest）的抽取器需要看全结构（不止 expected_fields 几个字段），
        所以这里把 _run_in_page 拿到的 raw['parsed'] 整段返回。

        Returns:
            {ok, status, parsed, url, elapsed_ms} 或 {ok:false, error, hint, ...}
        """
        entry = self.catalog.get(endpoint)
        if entry is None:
            return {"ok": False, "error": "endpoint_not_in_catalog",
                    "hint": f"目录无 key={endpoint}", "endpoint_key": endpoint,
                    "status": None, "parsed": None}
        if not self.has_cookies(platform):
            return {"ok": False, "error": "no_cookies",
                    "hint": f"{platform} 无有效 cookies，去 /scout 扫码登录",
                    "endpoint_key": endpoint, "status": None, "parsed": None}

        host = entry["host"]
        method = (entry.get("method") or "GET").upper()
        ctx = build_render_context(self.catalog.context.get(platform, {}), self._today)
        merged_params = render_params(entry.get("params"), ctx, overrides=params)
        merged_body = body if body is not None else entry.get("body")

        url = f"https://{host}{entry['path']}"
        if merged_params:
            qs = urlencode({k: v for k, v in merged_params.items() if v is not None})
            if qs:
                url += ("&" if "?" in url else "?") + qs

        start = time.monotonic()
        raw = await self._run_in_page(host, method, url, merged_body)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        parsed = raw.get("parsed")
        if parsed is None:
            return {"ok": False, "error": raw.get("error") or "no_parsed_json",
                    "hint": (raw.get("firstChars") or "")[:200],
                    "endpoint_key": endpoint, "status": raw.get("status"),
                    "parsed": None, "url": url, "elapsed_ms": elapsed_ms}
        return {"ok": True, "endpoint_key": endpoint, "platform": platform,
                "status": raw.get("status"), "parsed": parsed,
                "url": url, "elapsed_ms": elapsed_ms}

    async def batch_raw(self, requests: list[dict]) -> dict[str, dict]:
        """一个浏览器会话连打多个端点取 parsed JSON。返回 {endpoint_key: result}。

        按 host 分组复用同一 browser/context（开 context 是淘宝/抖音的主要耗时），
        镜像 scripts/_fetch_kpi_raw.py 的分组逻辑，但收成内存 dict 供 metric_ingest 直接消费。
        """
        from playwright.async_api import async_playwright

        # 按 host 分组（同 host 共用一个浏览器会话）
        by_host: dict[str, list[dict]] = {}
        for r in requests:
            entry = self.catalog.get(r["endpoint"])
            if entry is None:
                continue
            by_host.setdefault(entry["host"], []).append({"req": r, "entry": entry})

        out: dict[str, dict] = {}
        async with async_playwright() as p:
            for host, items in by_host.items():
                platform = self._host_platform(host)
                if not self.has_cookies(platform):
                    for it in items:
                        out[it["req"]["endpoint"]] = {
                            "ok": False, "error": "no_cookies",
                            "hint": f"{platform} 无有效 cookies",
                            "endpoint_key": it["req"]["endpoint"], "parsed": None}
                    continue
                browser = await p.chromium.launch(headless=True)
                bctx = await browser.new_context(
                    storage_state=str(self.storage_state_path(platform)))
                page = await bctx.new_page()
                try:
                    await page.goto(f"https://{host}/", wait_until="domcontentloaded", timeout=30000)
                    for it in items:
                        req, entry = it["req"], it["entry"]
                        ep = req["endpoint"]
                        method = (entry.get("method") or "GET").upper()
                        ctx = build_render_context(self.catalog.context.get(platform, {}), self._today)
                        merged_params = render_params(entry.get("params"), ctx, overrides=req.get("params"))
                        merged_body = req.get("body") if req.get("body") is not None else entry.get("body")
                        url = f"https://{host}{entry['path']}"
                        if merged_params:
                            qs = urlencode({k: v for k, v in merged_params.items() if v is not None})
                            if qs:
                                url += ("&" if "?" in url else "?") + qs
                        try:
                            # 单端点超时截断：一个卡住的端点不许拖垮整批日落库（fail-open 跳过该端点）。
                            raw = await asyncio.wait_for(
                                page.evaluate(
                                    _RUNNER_JS, {"method": method, "url": url,
                                                 "body": merged_body, "retry": 2}),
                                timeout=45,
                            )
                            parsed = raw.get("parsed")
                            out[ep] = {"ok": parsed is not None, "endpoint_key": ep,
                                       "platform": platform, "status": raw.get("status"),
                                       "parsed": parsed, "url": url,
                                       "error": None if parsed is not None else (raw.get("error") or "no_parsed_json")}
                        except asyncio.TimeoutError:
                            out[ep] = {"ok": False, "endpoint_key": ep, "platform": platform,
                                       "parsed": None, "error": "timeout(45s)"}
                        except Exception as exc:
                            out[ep] = {"ok": False, "endpoint_key": ep, "platform": platform,
                                       "parsed": None, "error": f"{type(exc).__name__}: {exc}"}
                finally:
                    await bctx.close()
                    await browser.close()
        return out
