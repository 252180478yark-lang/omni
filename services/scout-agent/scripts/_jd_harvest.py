"""京麦全面数据 harvest（自驱动 computer use · Claude 自己判断该抓什么）。

老板是小白、不指路 → 自动遍历京麦三大数据源的主要页面，passive 抓**所有数据接口**
(dsm.* / szgateway / jzt-api / atoms-api 的 JSON data) 的真实数值 + 每页截图。
产出 jd_harvest.jsonl（端点目录+数值）供分析、judge 哪些能建 BI。
覆盖：商智(jdsz 经营/交易/流量/商品/服务) + 财务账单 + 京准通推广数据。
跑：python services/scout-agent/scripts/_jd_harvest.py
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SESS = Path("services/scout-agent/sessions/jd/storage_state.json")
OUT = Path("services/scout-agent/catalog/jd_harvest.jsonl")
SHOTDIR = Path("E:/agent/omni/.pbi-work/jmrecon")
DATA_HOSTS = ("sff.jd.com/api", "szgateway.jd.com", "jzt-api.jd.com", "atoms-api.jd.com", "jdsz.jd.com")


def api_name(url: str) -> str:
    if "api=" in url:
        return url.split("api=")[-1].split("&")[0]
    return url.split("?")[0].split("jd.com")[-1]


async def main() -> None:
    if not SESS.exists():
        print("NO_SESSION", flush=True); sys.exit(2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    SHOTDIR.mkdir(parents=True, exist_ok=True)
    f = OUT.open("w", encoding="utf-8")
    seen = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(locale="zh-CN", viewport={"width": 1500, "height": 950},
                                        storage_state=str(SESS))

        async def on_resp(resp):
            url = resp.url
            if not any(d in url for d in DATA_HOSTS):
                return
            try:
                body = await resp.text()
            except Exception:
                return
            if not body.strip().startswith(("{", "[")):
                return
            api = api_name(url)
            sig = api + str(len(body) // 400)
            if sig in seen:
                return
            seen.add(sig)
            f.write(json.dumps({"api": api[:120], "url": url[:200], "body": body[:4500]}, ensure_ascii=False) + "\n")
            f.flush()

        def attach(pg):
            pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
        ctx.on("page", lambda pg: attach(pg))
        page = await ctx.new_page(); attach(page)

        async def shot(n):
            try:
                cur = ctx.pages[-1] if ctx.pages else page
                await cur.screenshot(path=str(SHOTDIR / n)); print(f"SHOT {n} <{cur.url[:50]}> ({len(seen)} eps)", flush=True)
            except Exception as e:
                print("SHOT_ERR", str(e)[:50], flush=True)

        async def sweep(pg, kws, maxc=8):
            c = 0
            for kw in kws:
                if c >= maxc:
                    break
                try:
                    loc = pg.get_by_text(kw, exact=False).first
                    if await loc.count():
                        await loc.click(timeout=2500); c += 1
                        await pg.wait_for_timeout(3200)
                        try:
                            await pg.wait_for_load_state("networkidle", timeout=6000)
                        except Exception:
                            pass
                except Exception:
                    continue
            print(f"  swept {c} of {len(kws)} kw", flush=True)

        async def visit(url, name, kws):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=55000)
            except Exception as exc:
                print(f"VISIT_ERR {name} {str(exc)[:80]}", flush=True)
            await page.wait_for_timeout(8000)
            await shot(name)
            if kws:
                await sweep(page, kws)
                await page.wait_for_timeout(2500)
                await shot(name.replace(".png", "_b.png"))

        # 1) 商智（jdsz）：经营/交易/流量/商品/服务 —— BI 核心运营数据
        await visit("https://jdsz.jd.com/", "h1_szhome.png",
                    ["经营概况", "交易", "成交", "流量", "流量来源", "商品", "商品分析", "服务", "评价", "转化", "实时"])
        # 2) 财务账单：货款收支/结算/账单
        await visit("https://shop.jd.com/jdm/fin/billManage/DailyBill", "h2_finance.png",
                    ["账单", "收支", "对账", "结算", "账户", "资金", "汇总"])
        # 3) 京准通：推广花费/效果/账户消耗
        await visit("https://jzt.jd.com/", "h3_jzt.png",
                    ["数据", "报表", "总览", "效果", "财务", "账户", "消耗", "全部推广"])
        # 4) 京麦工作台：订单/商品/价格/售后/营销/成长（首页带很多模块）
        await visit("https://shop.jd.com/jdm/home", "h4_jdm.png",
                    ["订单", "商品", "价格", "售后", "营销", "成长", "数据", "经营"])
        for _ in range(4):
            await page.wait_for_timeout(3000)
        await ctx.close(); await browser.close(); f.close()
        print(f"DONE harvested {len(seen)} endpoints -> {OUT}", flush=True)


asyncio.run(main())
