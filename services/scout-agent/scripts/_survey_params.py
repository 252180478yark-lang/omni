"""参数化全面迭代 survey：每个端点把它声明的可切维度逐个跑遍取值（单维度变、其余默认）
+ 时间窗(30天/本月) + per-SKU(product_id) → 把"网站所有能取的切面数据"都抓回来。

温和限速（DELAY 秒/次，~1-1.5 小时）。结果增量写 JSONL（每条 flush，可中途监控/断点续查）。
复用底座 catalog_loader / runner.js / fetch_verdict / executor 的 host→platform→storage。

跑：docker exec -e PYTHONPATH=/app -w /app omni-scout-agent python scripts/_survey_params.py
输出：/app/catalog/_survey_params.jsonl（host: services/scout-agent/catalog/）
"""
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from app.services.catalog_loader import CatalogLoader, build_render_context, render_params
from app.services.fetch_verdict import compute_verdict
from app.services.live_fetch import LiveFetchExecutor, _RUNNER_JS

CAT = Path("/app/catalog")
OUT = CAT / "_survey_params.jsonl"
LOG = CAT / "_survey_params.log"
DELAY = 1.2  # 温和限速：每请求间隔，降封号风险
PREVIEW = 900

PRODUCT_IDS = [
    "3780440627322421585", "3679941929442869421", "3680485053911138644",
    "3760063698182471779", "3679932703777620444",
]

# 每平台可切维度 → 取值集（来自 _analyze_params 的真实词表 + 合理扩展）
DIM_VOCAB = {
    "compass": {
        "index_selected": ["pay_amt", "income_amt", "trans_amt", "pay_cnt", "pay_ucnt",
                           "refund_sucess_amt", "dh_product_show_uv", "dh_product_click_uv",
                           "gpm", "per_user_price", "gmv_per_user", "product_show_ucnt",
                           "product_click_ucnt", "search_pv"],
        "sort_field": ["pay_amt", "trans_amt", "repeat_buy_user_cnt", "search_pv",
                       "product_show_ucnt", "cate_pay_amt"],
        "content_type": [0, 1],
        "traffic_channel": [1, 2, 3],
        "product_id": PRODUCT_IDS,
    },
    "yuntu": {
        "card": [0, 1, 2],
        "benchmark": [1, 2, 3],
        "spu_id": [],  # 缺 SPU 列表，暂不切
    },
    "doudian": {
        "tab": ["all", "onSale"],
    },
}


def win_context(base_ctx: dict, begin: date, end: date) -> dict:
    c = dict(base_ctx)
    c.update({
        "win_begin_yyyymmdd": begin.strftime("%Y%m%d"), "win_end_yyyymmdd": end.strftime("%Y%m%d"),
        "win_begin_iso": begin.isoformat(), "win_end_iso": end.isoformat(),
        "win_begin_slashdt": begin.strftime("%Y/%m/%d 00:00:00"),
        "win_end_slashdt": end.strftime("%Y/%m/%d 00:00:00"),
    })
    return c


async def one_fetch(page, host, e, ctx, override=None):
    params = render_params(e.get("params"), ctx, overrides=override)
    url = f"https://{host}{e['path']}"
    if params:
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        if qs:
            url += ("&" if "?" in url else "?") + qs
    raw = await page.evaluate(
        _RUNNER_JS,
        {"method": (e.get("method") or "GET").upper(), "url": url, "body": e.get("body"), "retry": 1},
    )
    v = compute_verdict(raw.get("status", 0), raw.get("ct", ""), raw.get("parsed"),
                        raw.get("firstChars", ""), e.get("expected_fields"))
    if raw.get("parsed") is not None:
        prev = json.dumps(raw["parsed"], ensure_ascii=False)[:PREVIEW]
    else:
        prev = (raw.get("firstChars") or "")[:PREVIEW]
    return v, prev, raw.get("status")


async def main(plat=None):
    out_path = CAT / (f"_survey_params_{plat}.jsonl" if plat else "_survey_params.jsonl")
    files = {p: CAT / f"{p}.json" for p in ("yuntu", "compass", "doudian") if (CAT / f"{p}.json").exists()}
    context = json.loads((CAT / "context.json").read_text("utf-8")) if (CAT / "context.json").exists() else {}
    cat = CatalogLoader.from_files(files, context)
    ex = LiveFetchExecutor(cat, Path("/app/sessions"))
    today = date.today()
    yest = today - timedelta(days=1)
    windows = {"30d": (today - timedelta(days=31), yest), "month": (today.replace(day=1), yest)}

    entries = cat.search(platform=plat, verified_only=False) if plat else cat.search(verified_only=False)
    by_host: dict[str, list] = {}
    for e in entries:
        by_host.setdefault(e["host"], []).append(e)

    out_f = out_path.open("w", encoding="utf-8")
    n = 0

    def log(msg):
        LOG.write_text(msg + "\n", encoding="utf-8") if not LOG.exists() else LOG.open("a", encoding="utf-8").write(msg + "\n")

    def emit(msg):
        print(msg, flush=True)

    def write(rec):
        nonlocal n
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out_f.flush()
        n += 1

    emit(f"参数化 survey 开始：{len(entries)} 端点，{len(by_host)} host，DELAY={DELAY}s")

    async with async_playwright() as p:
        for host, eps in by_host.items():
            platform = ex._host_platform(host)
            vocab = DIM_VOCAB.get(platform, {})
            emit(f"--- host={host} platform={platform} 端点={len(eps)} ---")
            try:
                browser = await p.chromium.launch(headless=True)
                bctx = await browser.new_context(storage_state=str(ex.storage_state_path(platform)))
                page = await bctx.new_page()
                await page.goto(f"https://{host}/", wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                write({"platform": platform, "host": host, "dim": "CTX", "error": str(exc)[:200]})
                continue

            for idx, e in enumerate(eps):
                ectx = build_render_context(cat.context.get(e.get("platform", platform), {}), today)
                params = e.get("params") or {}
                base = {"platform": e.get("platform"), "key": e["key"],
                        "alias": (e.get("aliases") or [""])[0], "category": e.get("category", "")}

                async def run(dim, value, override=None, ctx=ectx):
                    rec = dict(base, dim=dim, value=value)
                    try:
                        v, prev, st = await one_fetch(page, host, e, ctx, override)
                        rec.update({"verdict": v["verdict"], "code": v.get("code"),
                                    "has_data": v.get("has_data"), "status": st, "preview": prev})
                    except Exception as exc:
                        rec.update({"verdict": "EXC", "error": str(exc)[:160]})
                    write(rec)
                    await asyncio.sleep(DELAY)

                # 1. 默认
                await run("default", None)
                # 2. 各声明的可切维度
                for P, vals in vocab.items():
                    if P not in params or not vals:
                        continue
                    dflt = params[P]
                    for V in vals:
                        if str(V) == str(dflt):
                            continue
                        await run(P, V, override={P: V})
                # 3. 时间窗（begin/end_date 端点）
                if "begin_date" in params and "end_date" in params:
                    for wname, (b, e2) in windows.items():
                        await run("time", wname, ctx=win_context(ectx, b, e2))

                if idx % 10 == 0:
                    emit(f"  {host} {idx}/{len(eps)}  (累计写 {n})")

            try:
                await bctx.close()
                await browser.close()
            except Exception:
                pass

    out_f.close()
    emit(f"PARAMS SURVEY DONE: 写了 {n} 条 -> {out_path}")


if __name__ == "__main__":
    import sys
    _plat = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(_plat))
