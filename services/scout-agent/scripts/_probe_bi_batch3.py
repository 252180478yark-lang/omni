"""全量 BI 2.0 第3轮探测（剩余高价值主题）。dump 到 catalog/_bi_probe/，只读。
跑：docker exec omni-scout-agent bash -c "cd /app && PYTHONPATH=/app python scripts/_probe_bi_batch3.py"
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

TARGETS = [
    # —— 流量/搜索/内容（操盘手）——
    ("compass.flow_source_detail_v2", None),     # 自家5大流量源排行
    ("compass.realtime_word_overview_v2", None), # 搜索热词机会分
    ("compass.recommend_optimized_product_v2", None),  # 待优化商品
    ("compass.shop_video_list", None),           # 视频看后搜
    ("compass.weekly_report_summary", None),     # 搜索周报
    # —— 达人/直播 ——
    ("compass.top_list", None),                  # Top直播间榜
    ("yuntu.bestsellingauthor", None),           # 抖音号带货榜
    ("yuntu.getbrandaccountliveoverview", None), # 品牌自播对标
    # —— 商品5A漏斗 ——
    ("yuntu.getproductoverview5aanalysis", None),# 商品5A漏斗
    # —— 竞品与行业 ——
    ("compass.good_compete_product_list", None), # 同类竞品清单
    ("yuntu.marketoverview", None),              # 行业大盘
    ("yuntu.trendinsights", None),               # 行业趋势
    ("yuntu.branddistribution", None),           # 品牌份额分布
    ("yuntu.flowentrystructure", None),          # 流量入口占比
    # —— 品牌心智/口碑（老板 P2）——
    ("yuntu.getoverview", None),                 # 品牌心智总览
    ("yuntu.listbrandtopkeyword", None),         # 心智Top词
    ("yuntu.get_summary", None),                 # AI口碑总结
    ("yuntu.getbrandnsrdetailstats", None),      # NSR净推荐口碑
    # —— 物流/售后（操盘手 P2）——
    ("doudian.get_ticket_list", None),           # 平台罚单
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
    print("BI BATCH3 PROBE DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
