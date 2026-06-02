"""高效全量实时重验（一平台一浏览器，复用 page 循环打 XHR）。

非破坏性：只写报告 catalog/_sweep_<platform>_<date>.json，不覆盖 catalog。
日期参数按平台策略自动换当前值（yuntu T+1 用 today-2，其余 today）。
缺标准 ID 参数（aadvid/shop_id/...）时从 context.json 兜底补。

用法：python scripts/sweep.py [yuntu|compass|doudian|all]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.fetch_verdict import compute_verdict  # noqa: E402
from app.services.catalog_loader import build_render_context, render_params  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "catalog"
SESS = ROOT / "sessions"
RUNNER = (ROOT / "app" / "services" / "runner.js").read_text("utf-8")
TODAY = date.today()
TODAY_STR = TODAY.isoformat()
INTER_DELAY_MS = 600

SESSION_NAME = {"yuntu": "yuntu", "compass": "jinritemai", "doudian": "jinritemai"}
HOSTS = {"yuntu": "yuntu.oceanengine.com", "compass": "compass.jinritemai.com",
         "doudian": "fxg.jinritemai.com"}


def resolve_params(params: dict, platform: str, ctx_ids: dict) -> dict:
    """用真实 executor 解析路径（build_render_context + render_params）+ 兜底补标准 ID。"""
    rctx = build_render_context(ctx_ids, TODAY)
    out = render_params(params, rctx, overrides=None)
    for idk, idv in ctx_ids.items():
        out.setdefault(idk, idv)
    return out


async def sweep_platform(p, platform: str) -> dict:
    entries = json.loads((CAT / f"{platform}.json").read_text("utf-8"))
    ctx = json.loads((CAT / "context.json").read_text("utf-8")).get(platform, {})
    storage = SESS / SESSION_NAME[platform] / "storage_state.json"
    host = HOSTS[platform]

    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context(storage_state=str(storage))
    page = await context.new_page()
    await page.goto(f"https://{host}/", wait_until="domcontentloaded", timeout=40000)

    results = []
    counts: dict[str, int] = {}
    for i, e in enumerate(entries):
        params = resolve_params(e.get("params"), platform, ctx)
        url = f"https://{host}{e['path']}"
        if params:
            qs = urlencode({k: v for k, v in params.items() if v is not None})
            if qs:
                url += ("&" if "?" in url else "?") + qs
        req = {"method": (e.get("method") or "GET").upper(), "url": url,
               "body": e.get("body"), "retry": 2}
        try:
            raw = await page.evaluate(RUNNER, req)
            v = compute_verdict(raw.get("status", 0), raw.get("ct", ""), raw.get("parsed"),
                                raw.get("firstChars", ""), e.get("expected_fields"))
            verdict, code, fields = v["verdict"], v["code"], v["fields"]
        except Exception as exc:  # noqa: BLE001
            verdict, code, fields = "EXCEPTION", None, {}
            raw = {"error": str(exc)[:100]}
        counts[verdict] = counts.get(verdict, 0) + 1
        results.append({"key": e["key"], "path": e["path"], "method": e.get("method"),
                        "was_verified": e.get("verified"), "verdict": verdict,
                        "code": code, "n_fields": len(fields), "url": url,
                        "sample": str(raw.get("firstChars", ""))[:120] if isinstance(raw, dict) else ""})
        # 进度打点
        if (i + 1) % 25 == 0:
            print(f"  [{platform}] {i+1}/{len(entries)} ...", flush=True)
        await page.wait_for_timeout(INTER_DELAY_MS)

    await context.close()
    await browser.close()

    report = {"platform": platform, "date": TODAY_STR, "total": len(entries),
              "counts": counts,
              "pass": sum(1 for r in results if r["verdict"] in ("PASS", "PASS_NODATA")),
              "results": results}
    (CAT / f"_sweep_{platform}_{TODAY_STR}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return {"platform": platform, "total": len(entries), "counts": counts,
            "pass": report["pass"]}


async def main():
    from playwright.async_api import async_playwright
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    platforms = ["yuntu", "compass", "doudian"] if target == "all" else [target]
    summary = {}
    async with async_playwright() as p:
        for plat in platforms:
            print(f"=== sweeping {plat} ===", flush=True)
            try:
                summary[plat] = await sweep_platform(p, plat)
            except Exception as exc:  # noqa: BLE001
                summary[plat] = {"error": str(exc)[:200]}
            print(json.dumps(summary[plat], ensure_ascii=False), flush=True)
    print("=== SWEEP DONE ===", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
