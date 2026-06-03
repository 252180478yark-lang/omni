"""全量 BI 2.0 目标端点真实返回 dump（per-SKU/价格/人群细分/达人/搜索词）。
照 _fetch_kpi_raw.py 同款机制（登录态 + page.evaluate runner.js），只读不落库。
dump 到 catalog/_bi_probe/<key>.json，供 workflow agent 看全结构写抽取器。
跑：docker exec omni-scout-agent bash -c "cd /app && PYTHONPATH=/app python scripts/_probe_bi_endpoints.py"
"""
import asyncio
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from app.services.catalog_loader import CatalogLoader, build_render_context, render_params
from app.services.live_fetch import LiveFetchExecutor, _RUNNER_JS

CAT = Path("/app/catalog")
OUTDIR = CAT / "_bi_probe"
OUTDIR.mkdir(exist_ok=True)

# 全量 BI 2.0 目标端点。按维度分组（注释标维度）。值=可选 param override。
TARGETS = [
    # —— per-SKU / 单品（解决"看不到产品"）——
    ("compass.product_list", None),                 # TOP 商品榜（per-product 表格）
    ("compass.index_data", None),                   # 单品近7天卖多少
    ("compass.sku", None),                          # SKU 拆分销量
    ("compass.trend_v3", None),                     # 单品 GMV 日趋势
    ("compass.flow_data_v2", None),                 # 单品流量来源拆分
    # —— 价格（解决"看不到价格"）——
    ("compass.category_overview_price_band_distribution", None),  # 行业价格带分布（整表）
    ("compass.category_overview_price_analysis_product", None),   # 价格带商品池
    ("compass.category_price_band_distribution", None),          # 备版
    # —— 人群细分（性别/年龄/地域/兴趣）——
    ("compass.basic_attribute", None),              # 人群画像（年龄/性别/地域）
    ("compass.core_crowd", None),                   # 核心人群
    ("compass.crowd_prefer", None),                 # 人群偏好
    # —— 达人 / 搜索词 ——
    ("compass.list", None),                         # 达人榜（整表明细）
    ("compass.word_rank", None),                    # 搜索词 Top 榜
    ("compass.overview_data_trend", None),          # 搜索 GMV 日趋势
    # —— 云图人群（八大人群，可能 500，fail-open）——
    ("yuntu.getaudienceassetbig8profile", None),
    ("yuntu.getaudienceassetbig8trend", None),
    ("yuntu.bestsellingproduct", None),             # 畅销 SPU 排行
]


async def main():
    files = {p: CAT / f"{p}.json" for p in ("yuntu", "compass", "doudian") if (CAT / f"{p}.json").exists()}
    context = json.loads((CAT / "context.json").read_text("utf-8"))
    cat = CatalogLoader.from_files(files, context)
    ex = LiveFetchExecutor(cat, Path("/app/sessions"))
    today = date.today()

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
                    print(f"  {key}: status={raw.get('status')} size={sz} -> _bi_probe/{safe}.json", flush=True)
                except Exception as exc:
                    print(f"  {key}: ERR {exc}", flush=True)
                await asyncio.sleep(1.0)
            await bctx.close()
            await browser.close()
    print("BI PROBE DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
