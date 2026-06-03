"""把落库桥要用的 14 个 KPI 端点的【完整真实返回】抓下来 dump 成文件，供写抽取器看全结构。
（survey 预览截断了，写精确抽取路径要看完整 JSON。）只读、不落库。"""
import asyncio
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from app.services.catalog_loader import CatalogLoader, build_render_context, render_params
from app.services.live_fetch import LiveFetchExecutor, _RUNNER_JS

CAT = Path("/app/catalog")
OUTDIR = CAT / "_kpi_raw"
OUTDIR.mkdir(exist_ok=True)

# 落库桥 14 端点（老板 2026-06-03 拍板）。值=可选 override（要特定指标/维度时）。
TARGETS = [
    ("compass.core_trend_v3", None),
    ("doudian.getoverviewbyversion", None),
    ("doudian.doudian_shop_overview", None),
    ("compass.doudian_shop_overview", None),  # 备：可能在 compass 目录里
    ("compass.flow_source_funnel", None),
    ("compass.product_list", None),
    ("compass.trend_v3", None),
    ("yuntu.getaudienceassetstructure", None),
    ("yuntu.get_audience_asset_trend", None),
    ("yuntu.audienceflowanalysisv2", None),
    ("yuntu.industryrank", None),
    ("yuntu.corebrand", None),
    ("yuntu.productstructure", None),
    ("compass.list", None),
    ("compass.category_overview_price_band_distribution", None),
]


async def main():
    files = {p: CAT / f"{p}.json" for p in ("yuntu", "compass", "doudian") if (CAT / f"{p}.json").exists()}
    context = json.loads((CAT / "context.json").read_text("utf-8"))
    cat = CatalogLoader.from_files(files, context)
    ex = LiveFetchExecutor(cat, Path("/app/sessions"))
    today = date.today()

    # 按 host 分组
    by_host = {}
    for key, override in TARGETS:
        e = cat.get(key)
        if e is None:
            print(f"SKIP {key}: 目录里没有", flush=True)
            continue
        by_host.setdefault(e["host"], []).append((key, e, override))

    async with async_playwright() as p:
        for host, items in by_host.items():
            platform = ex._host_platform(host)
            print(f"--- {host} ({platform}) {len(items)} 端点 ---", flush=True)
            browser = await p.chromium.launch(headless=True)
            bctx = await browser.new_context(storage_state=str(ex.storage_state_path(platform)))
            page = await bctx.new_page()
            await page.goto(f"https://{host}/", wait_until="domcontentloaded", timeout=30000)
            for key, e, override in items:
                ectx = build_render_context(cat.context.get(e.get("platform", platform), {}), today)
                params = render_params(e.get("params"), ectx, overrides=override)
                url = f"https://{host}{e['path']}"
                if params:
                    qs = urlencode({k: v for k, v in params.items() if v is not None})
                    if qs:
                        url += ("&" if "?" in url else "?") + qs
                try:
                    raw = await page.evaluate(_RUNNER_JS, {"method": (e.get("method") or "GET").upper(),
                                                           "url": url, "body": e.get("body"), "retry": 1})
                    parsed = raw.get("parsed")
                    safe = key.replace(".", "__")
                    (OUTDIR / f"{safe}.json").write_text(
                        json.dumps(parsed, ensure_ascii=False, indent=1) if parsed is not None
                        else (raw.get("firstChars") or ""), encoding="utf-8")
                    sz = len(json.dumps(parsed, ensure_ascii=False)) if parsed is not None else 0
                    print(f"  {key}: status={raw.get('status')} size={sz} -> _kpi_raw/{safe}.json", flush=True)
                except Exception as exc:
                    print(f"  {key}: ERR {exc}", flush=True)
                await asyncio.sleep(1.0)
            await bctx.close()
            await browser.close()
    print("KPI RAW DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
