"""对候选层失败端点应用平台启发式修复(path/params)，改完**立即实测**，
只把真 PASS/PASS_NODATA 的回写 catalog（verified=true）。非破坏：失败的不动。

用法：python scripts/refix.py <yuntu|compass|doudian>
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
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
SESSION_NAME = {"yuntu": "yuntu", "compass": "jinritemai", "doudian": "jinritemai"}
HOSTS = {"yuntu": "yuntu.oceanengine.com", "compass": "compass.jinritemai.com",
         "doudian": "fxg.jinritemai.com"}


def fix_compass(path: str, params: dict) -> tuple[str, dict]:
    if not path.startswith("/compass_api"):
        if path.startswith("/trade/"):
            path = "/compass_api/shop/common" + path
        elif path.startswith("/app/"):
            path = "/compass_api/shop" + path[4:]  # /app/homepage/.. → /compass_api/shop/homepage/..
        else:
            path = "/compass_api/shop" + path
    p = dict(params or {})
    p.setdefault("date_type", 21)
    p.setdefault("begin_date", "{win_begin_slashdt}")
    p.setdefault("end_date", "{win_end_slashdt}")
    return path, p


def fix_yuntu(path: str, params: dict) -> tuple[str, dict]:
    # 候选多缺 api 版本段：在域后插入正确版本前缀（从 verified 真前缀学到）
    segs = path.lstrip("/").split("/")
    dom = segs[0] if segs else ""
    rest = "/".join(segs[1:])
    api_inserts = {
        "product_node": "v2/api",      # /product_node/v2/api/...
        "yuntu_ng": "api/v1",
        "yuntu_common": "api/v1",
        "yuntu_ecom": "api/v1",
        "yuntu_biz": "api/common",
        "yuntu_rome": "api",
    }
    if dom in api_inserts and len(segs) > 1 and segs[1] not in ("api", "v2", "v1"):
        path = f"/{dom}/{api_inserts[dom]}/{rest}"
    return path, dict(params or {})


def fix_doudian(path: str, params: dict) -> tuple[str, dict]:
    p = dict(params or {})
    # 抖店多数 GET 需固定 query（phase5 经验）
    if path.startswith("/account/center"):
        p.setdefault("req_source", "dou_dian_pc")
        p.setdefault("ac_redesign", "doudian")
    if "/experiencescore/" in path:
        p.setdefault("exp_version", "release")
    return path, p


FIXERS = {"compass": fix_compass, "yuntu": fix_yuntu, "doudian": fix_doudian}


async def main():
    platform = sys.argv[1]
    fixer = FIXERS[platform]
    entries = json.loads((CAT / f"{platform}.json").read_text("utf-8"))
    ctx_ids = json.loads((CAT / "context.json").read_text("utf-8")).get(platform, {})
    rctx = build_render_context(ctx_ids, TODAY)
    host = HOSTS[platform]

    # 只修 verified=false 的（候选 + 之前失败的）
    targets = [e for e in entries if not e.get("verified")]
    print(f"{platform}: {len(targets)} 个待修候选/失败端点", flush=True)

    from playwright.async_api import async_playwright
    fixed = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(SESS / SESSION_NAME[platform] / "storage_state.json"))
        page = await context.new_page()
        await page.goto(f"https://{host}/", wait_until="domcontentloaded", timeout=40000)
        for i, e in enumerate(targets):
            new_path, new_params = fixer(e["path"], e.get("params") or {})
            params = render_params(new_params, rctx, None)
            for idk, idv in ctx_ids.items():
                params.setdefault(idk, idv)
            url = f"https://{host}{new_path}"
            qs = urlencode({k: v for k, v in params.items() if v is not None})
            if qs:
                url += ("&" if "?" in url else "?") + qs
            try:
                raw = await page.evaluate(RUNNER, {"method": (e.get("method") or "GET").upper(),
                                                   "url": url, "body": e.get("body"), "retry": 2})
                v = compute_verdict(raw.get("status", 0), raw.get("ct", ""), raw.get("parsed"),
                                    raw.get("firstChars", ""), e.get("expected_fields"))
            except Exception as exc:  # noqa: BLE001
                v = {"verdict": "EXCEPTION"}
            if v["verdict"] in ("PASS", "PASS_NODATA"):
                e["path"] = new_path
                e["params"] = new_params
                e["verified"] = True
                e["verified_at"] = TODAY.isoformat()
                e["notes"] = f"refix({platform}) prefix+params 修复 → {v['verdict']}"
                fixed += 1
            await page.wait_for_timeout(500)
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(targets)} ... 已修 {fixed}", flush=True)
        await context.close()
        await browser.close()

    (CAT / f"{platform}.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")
    now_ok = sum(1 for e in entries if e.get("verified"))
    print(f"=== {platform} refix 完成：新修好 {fixed} 个；catalog 现 verified {now_ok}/{len(entries)} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
