"""一次性 survey：跑全部端点目录，抓每个端点的真实返回预览，dump 成 JSON。

目的：登录态就绪后，把三平台「实际能取到啥真实数据」全量摸一遍 → 出一张表给老板挑进 Power BI。
复用底座：catalog_loader / runner.js / fetch_verdict / LiveFetchExecutor 的 host→platform→storage 映射。
按 host 复用一个浏览器会话（不是每端点起一个浏览器），快很多。只读、不落库。

跑（容器内，三平台已登录 cookie 在 sessions/）：
    docker exec -w /app omni-scout-agent python scripts/_survey_catalog.py            # 全部 491
    docker exec -w /app omni-scout-agent python scripts/_survey_catalog.py verified    # 只跑 verified 204
输出：/app/catalog/_survey_result.json（bind-mount 到 host services/scout-agent/catalog/）。
"""
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from app.services.catalog_loader import CatalogLoader, build_render_context, render_params
from app.services.fetch_verdict import compute_verdict
from app.services.live_fetch import LiveFetchExecutor, _RUNNER_JS

CAT = Path("/app/catalog")
OUT = CAT / "_survey_result.json"
PREVIEW_CHARS = 1400
REQ_DELAY_S = 0.4  # 端点间间隔，温和一点（L0-6 抓取合规意识）


async def main(verified_only: bool) -> None:
    files = {p: CAT / f"{p}.json" for p in ("yuntu", "compass", "doudian") if (CAT / f"{p}.json").exists()}
    context = json.loads((CAT / "context.json").read_text("utf-8")) if (CAT / "context.json").exists() else {}
    cat = CatalogLoader.from_files(files, context)
    ex = LiveFetchExecutor(cat, Path("/app/sessions"))
    today = date.today()

    entries = cat.search(verified_only=verified_only)
    by_host: dict[str, list] = {}
    for e in entries:
        by_host.setdefault(e["host"], []).append(e)

    results: list[dict] = []
    print(f"survey 开始：{len(entries)} 端点，{len(by_host)} 个 host，verified_only={verified_only}", flush=True)

    async with async_playwright() as p:
        for host, eps in by_host.items():
            platform = ex._host_platform(host)
            storage = str(ex.storage_state_path(platform))
            print(f"--- host={host} platform={platform} 端点={len(eps)} ---", flush=True)
            try:
                browser = await p.chromium.launch(headless=True)
                ctx = await browser.new_context(storage_state=storage)
                page = await ctx.new_page()
                await page.goto(f"https://{host}/", wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                for e in eps:
                    results.append({"platform": e.get("platform"), "key": e["key"],
                                    "alias": (e.get("aliases") or [""])[0], "verdict": "CTX_FAIL",
                                    "error": str(exc)[:200]})
                continue

            for i, e in enumerate(eps):
                rec: dict = {"platform": e.get("platform"), "key": e["key"],
                             "category": e.get("category", ""),
                             "alias": (e.get("aliases") or [""])[0],
                             "verified_flag": bool(e.get("verified")),
                             "method": (e.get("method") or "GET").upper(), "path": e.get("path")}
                try:
                    rctx = build_render_context(cat.context.get(e.get("platform", platform), {}), today)
                    params = render_params(e.get("params"), rctx, overrides=None)
                    url = f"https://{host}{e['path']}"
                    if params:
                        qs = urlencode({k: v for k, v in params.items() if v is not None})
                        if qs:
                            url += ("&" if "?" in url else "?") + qs
                    raw = await page.evaluate(
                        _RUNNER_JS,
                        {"method": rec["method"], "url": url, "body": e.get("body"), "retry": 1},
                    )
                    v = compute_verdict(raw.get("status", 0), raw.get("ct", ""), raw.get("parsed"),
                                        raw.get("firstChars", ""), e.get("expected_fields"))
                    rec.update({"verdict": v["verdict"], "code": v.get("code"),
                                "has_data": v.get("has_data"), "status": raw.get("status"),
                                "fields": v.get("fields") or {}})
                    if raw.get("parsed") is not None:
                        rec["raw_preview"] = json.dumps(raw["parsed"], ensure_ascii=False)[:PREVIEW_CHARS]
                    else:
                        rec["raw_preview"] = (raw.get("firstChars") or "")[:PREVIEW_CHARS]
                except Exception as exc:
                    rec.update({"verdict": "EXC", "error": str(exc)[:200]})
                results.append(rec)
                if i % 20 == 0:
                    print(f"  {host} {i}/{len(eps)}", flush=True)
                await asyncio.sleep(REQ_DELAY_S)

            try:
                await ctx.close()
                await browser.close()
            except Exception:
                pass

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    npass = sum(1 for r in results if str(r.get("verdict", "")).startswith("PASS"))
    ndata = sum(1 for r in results if r.get("has_data"))
    print(f"SURVEY DONE: {len(results)} 端点, {npass} PASS, {ndata} 有数据 -> {OUT}", flush=True)


if __name__ == "__main__":
    vonly = len(sys.argv) > 1 and sys.argv[1].lower().startswith("verif")
    asyncio.run(main(verified_only=vonly))
