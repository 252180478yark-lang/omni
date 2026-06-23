"""京麦推广费/利润 自驱动勘测（Claude 自己开浏览器导航，老板不用点）。

复用 session 开真窗口 → 自动导航京麦财务/营销/京准通 + 点报表/花费 → passive 抓
财务/推广相关接口的**完整响应体**（含数值）+ 每步截图。目的：确认京麦哪个接口能给
推广费 + 利润 + 时间范围，为接进京东月度净利做准备。不 forge 不对抗，只读自动点。
跑（host）：python services/scout-agent/scripts/_jd_promo_autonav.py
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SESS = Path("services/scout-agent/sessions/jd/storage_state.json")
BODIES = Path("services/scout-agent/catalog/jd_promo_bodies.jsonl")
SHOTDIR = Path("E:/agent/omni/.pbi-work/jmrecon")
DUMP = ("expenseAmount", "profitAmount", "incomeAmount", "推广", "花费", "消耗", "cost",
        "charge", "promot", "jzt", "operationData", "findShopData", "consume", "spend",
        "结算", "资金", "expenseDetail", "incomeDetail", "广告")


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
            try:
                body = await resp.text()
            except Exception:
                return
            if not any(h in url or h in body for h in DUMP):
                return
            base = url.split("?")[0]
            sig = base + str(len(body) // 400)
            if sig in seen:
                return
            seen.add(sig)
            f.write(json.dumps({"url": url[:240], "body": body[:7000]}, ensure_ascii=False) + "\n")
            f.flush()
            tag = [h for h in ("expenseAmount", "profitAmount", "推广", "花费", "消耗", "operationData", "jzt", "广告") if h in url or h in body]
            print(f"BODY {base[:78]} :: {tag}", flush=True)

        def attach(pg):
            pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
        ctx.on("page", lambda pg: attach(pg))
        page = await ctx.new_page(); attach(page)

        async def shot(name):
            try:
                cur = ctx.pages[-1] if ctx.pages else page
                await cur.screenshot(path=str(SHOTDIR / name))
                print(f"SHOT {name} <{cur.url[:55]}>", flush=True)
            except Exception as exc:
                print("SHOT_ERR", str(exc)[:70], flush=True)

        async def click_kw(pg, kws, maxc=4):
            c = 0
            for kw in kws:
                if c >= maxc:
                    break
                try:
                    loc = pg.get_by_text(kw, exact=False).first
                    if await loc.count():
                        await loc.click(timeout=3000); c += 1
                        await pg.wait_for_timeout(3500)
                        try:
                            await pg.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                except Exception:
                    continue
            print(f"  clicked {c} of {kws[:3]}...", flush=True)
            return c

        try:
            await page.goto("https://shop.jd.com/jdm/home", wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            print("GOTO_ERR home", str(exc)[:100], flush=True)
        await page.wait_for_timeout(9000)
        await shot("01_home.png")
        await click_kw(page, ["资金", "财务", "账户", "钱包", "收支", "结算", "对账", "我的资产"])
        await page.wait_for_timeout(3000); await shot("02_finance.png")
        await click_kw(page, ["营销", "推广", "京准通", "快车", "数据中心", "经营概况", "报表"])
        await page.wait_for_timeout(3000); await shot("03_promo.png")
        try:
            await page.goto("https://jzt.jd.com/", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(7000); await shot("04_jzt.png")
            await click_kw(page, ["报表", "数据", "花费", "消耗", "账户", "财务", "推广", "总览"])
            await page.wait_for_timeout(3000); await shot("05_jzt2.png")
        except Exception as exc:
            print("JZT_ERR", str(exc)[:100], flush=True)
        for i in range(8):
            await page.wait_for_timeout(3000)
            if i == 4:
                await shot("06_dwell.png")
        await ctx.close(); await browser.close(); f.close()
        print(f"DONE captured {len(seen)} bodies", flush=True)


asyncio.run(main())
