"""全量 BI 2.0 第 1 批探测（P0 诊断闭环缺口 + 投放ROI，最痛 gaps）。
照 _probe_bi_endpoints.py 同机制，dump 到 catalog/_bi_probe/，只读不落库。
跑：docker exec omni-scout-agent bash -c "cd /app && PYTHONPATH=/app python scripts/_probe_bi_batch2.py"
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

# 第 1 批：P0 诊断闭环 + 投放ROI（gaps 第一优先）
TARGETS = [
    ("compass.core_index_v3", None),            # 投放ROI榜（product_id/ad_cost）— 全盘唯一投钱回报
    ("compass.flow_loss_card", None),           # 转化流失定位（各环节流失量/率）
    ("compass.flow_source_detail_v2", None),    # 自家5大流量源排行
    ("compass.flow_overview_card", None),       # 流量大盘核心指标 KPI
    ("compass.core_data", None),                # 商品卡 UV 价值
    ("compass.enter_source_v2", None),          # 流量时段/来源拆支付
    ("compass.shop_rank", None),                # 店铺行业排名
    ("compass.prof_exp_score", None),           # 体验分 + 行业对比
    ("compass.shop_negative_problem", None),    # 负面问题分类排行
    ("compass.overview_data", None),            # 搜索四档行业对标
    ("doudian.statistics", None),               # 好评率/差评数
    ("doudian.homepage", None),                 # 今日大盘
    ("yuntu.insightbrandoccupancy", None),      # 品牌市占率
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
    print("BI BATCH2 PROBE DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
