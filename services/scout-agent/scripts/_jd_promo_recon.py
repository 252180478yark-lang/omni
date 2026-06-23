"""京麦推广费勘测（host headed · 老板驱动导航）。

目的：找到京麦「推广/营销（京准通/快车）」里**推广花费**的数据接口，为把推广费接进
京东月度净利做准备（月报缺的近几月推广费从这抓）。

机制：复用已存 session 开真窗口 → 老板在窗口里点到平时看推广花费/报表的页面 →
我 passive 抓所有 json 响应，dump 出端点 + 字段名 + 命中"费/花费/消耗/cost"的提示键。
不 forge 不对抗，只读。跑（host，cwd=E:\\agent\\omni）：
  python services/scout-agent/scripts/_jd_promo_recon.py
stdout：BROWSER_OPEN / HINT <端点> / DONE
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SESS = Path("services/scout-agent/sessions/jd/storage_state.json")
OUT = Path("services/scout-agent/catalog/jd_promo_recon.jsonl")
POLL_SECONDS = 360
HINT = ("费", "花费", "消耗", "成本", "cost", "charge", "amt", "amount",
        "spend", "推广", "cpc", "cpm", "roi", "click", "consume", "budget", "balance")


def keys_of(j, depth=0):
    out = []
    if isinstance(j, dict):
        for k, v in j.items():
            out.append(str(k))
            if depth < 2 and isinstance(v, (dict, list)):
                out += keys_of(v, depth + 1)
    elif isinstance(j, list) and j:
        out += keys_of(j[0], depth + 1)
    return out


async def main() -> None:
    if not SESS.exists():
        print("NO_SESSION 先跑 _jd_login_capture_host.py", flush=True)
        sys.exit(2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    f = OUT.open("w", encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(locale="zh-CN", viewport={"width": 1500, "height": 950},
                                        storage_state=str(SESS))
        pg = await ctx.new_page()

        async def on_resp(resp):
            url = resp.url
            try:
                ct = (resp.headers or {}).get("content-type", "")
                if "json" not in ct and not url.endswith(".ajax"):
                    return
                j = json.loads(await resp.text())
            except Exception:
                return
            ks = keys_of(j)
            if not ks:
                return
            base = url.split("?")[0]
            sig = (base, tuple(sorted(set(ks))[:10]))
            if sig in seen:
                return
            seen.add(sig)
            hint = sorted({k for k in ks if any(h in str(k).lower() or h in str(k) for h in HINT)})
            rec = {"url": url[:280], "hint_keys": hint[:24], "all_keys": sorted(set(ks))[:48]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if hint:
                print(f"HINT {base[:90]} :: {hint[:10]}", flush=True)

        pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
        try:
            await pg.goto("https://shop.jd.com/jdm/home", wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            print(f"GOTO_ERR {str(exc)[:120]}", flush=True)
        print("BROWSER_OPEN 请在【这个窗口】里点到你平时看推广花费/消耗的页面"
              "（京准通/快车/营销 → 报表/数据/花费），尽量切到「月」或自定义时间段。我在抓接口。", flush=True)
        waited = 0
        while waited < POLL_SECONDS:
            await pg.wait_for_timeout(3000)
            waited += 3
        await ctx.close()
        await browser.close()
        f.close()
        print(f"DONE {OUT} · captured {len(seen)} endpoints", flush=True)


asyncio.run(main())
