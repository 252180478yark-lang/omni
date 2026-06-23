"""京准通推广花费勘测（自驱动·抓真实花费数值）。

进京准通数据报表/财务账户，抓 reweb/index/indicator(cost) + 账户消耗 + trendchart 的
**真实数值**（带默认时间段），+ 截图看推广花费到底是 0 还是有数。判断老板现在投不投京准通。
跑：python services/scout-agent/scripts/_jd_jzt_cost_recon.py
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SESS = Path("services/scout-agent/sessions/jd/storage_state.json")
BODIES = Path("services/scout-agent/catalog/jd_jzt_cost.jsonl")
SHOTDIR = Path("E:/agent/omni/.pbi-work/jmrecon")
WANT = ("cost", "消耗", "花费", "charge", "financecore", "trendchart", "indicator",
        "totalOrderSum", "totalOrderROI", "balance", "expense", "settle", "bill")


async def main() -> None:
    if not SESS.exists():
        print("NO_SESSION", flush=True); sys.exit(2)
    BODIES.parent.mkdir(parents=True, exist_ok=True)
    SHOTDIR.mkdir(parents=True, exist_ok=True)
    f = BODIES.open("w", encoding="utf-8")
    seen = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(locale="zh-CN", viewport={"width": 1500, "height": 950},
                                        storage_state=str(SESS))

        async def on_resp(resp):
            url = resp.url
            if not any(d in url for d in ("jzt-api.jd.com", "atoms-api.jd.com", "sff.jd.com/api")):
                return
            try:
                body = await resp.text()
            except Exception:
                return
            if not body.strip().startswith(("{", "[")):
                return
            if not any(w in url or w in body for w in WANT):
                return
            base = url.split("?")[0]
            sig = base + str(len(body) // 300)
            if sig in seen:
                return
            seen.add(sig)
            f.write(json.dumps({"url": url[:200], "body": body[:5000]}, ensure_ascii=False) + "\n")
            f.flush()
            if any(k in body for k in ("cost", "消耗", "花费", "totalOrderSum")):
                print(f"COST? {base[:80]}", flush=True)

        def attach(pg):
            pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
        ctx.on("page", lambda pg: attach(pg))
        page = await ctx.new_page(); attach(page)

        async def shot(n):
            try:
                cur = ctx.pages[-1] if ctx.pages else page
                await cur.screenshot(path=str(SHOTDIR / n)); print(f"SHOT {n} <{cur.url[:55]}>", flush=True)
            except Exception as e:
                print("SHOT_ERR", str(e)[:60], flush=True)

        async def click_kw(pg, kws, maxc=5):
            c = 0
            for kw in kws:
                if c >= maxc:
                    break
                try:
                    loc = pg.get_by_text(kw, exact=False).first
                    if await loc.count():
                        await loc.click(timeout=3000); c += 1
                        await pg.wait_for_timeout(3500)
                except Exception:
                    continue
            print(f"  clicked {c}", flush=True)
            return c

        try:
            await page.goto("https://jzt.jd.com/", wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            print("GOTO_ERR", str(exc)[:100], flush=True)
        await page.wait_for_timeout(9000); await shot("c1_jzt_home.png")
        # 数据中心 / 报表 / 财务 / 账户 — 逐个点
        for grp, name in [(["数据", "数据中心", "报表", "总览", "效果"], "c2_data.png"),
                          (["财务", "账户", "资金", "充值", "消耗", "流水"], "c3_finance.png"),
                          (["全部推广", "推广报表", "账户报表", "日报", "汇总"], "c4_report.png")]:
            await click_kw(page, grp)
            await page.wait_for_timeout(3500); await shot(name)
        for i in range(6):
            await page.wait_for_timeout(3000)
        await ctx.close(); await browser.close(); f.close()
        print(f"DONE {len(seen)} bodies", flush=True)


asyncio.run(main())
