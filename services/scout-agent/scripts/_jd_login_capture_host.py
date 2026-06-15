"""切片0 主流程 v2（HOST 可见浏览器版）：在老板自己屏幕上开真浏览器 → 老板用京麦正常登录商智 → 自动抓接口。

为什么换 host：scout 容器里浏览器跑在 xvfb 虚拟屏（老板看不见、没法做京麦商家登录），
且 sz-online/shop 商家域对容器自动化浏览器 ERR_CONNECTION_CLOSED（反爬）。host 上是真窗口、真 IP，
老板能看见能点，京麦扫码/账密/短信都行；登完我自动逛商智录 HAR。

老板只做：在弹出的窗口里登录商智（京麦）。其余自动：存 session（顺带办切片2 前置）+ 录 jd_capture.har。
跑（host，cwd=E:\\agent\\omni）：python services/scout-agent/scripts/_jd_login_capture_host.py
stdout 标记：BROWSER_OPEN / LOGGED_IN / SESSION_SAVED / DASH_URL / HAR_SAVED / TIMEOUT
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SESS = Path("services/scout-agent/sessions/jd")
HAR = "services/scout-agent/catalog/jd_capture.har"
AUTH = {"pt_key", "pt_pin"}  # 真·登录态 cookie（仅登录后才有；不含游客早植的 thor，防误判）
POLL_SECONDS = 360  # 老板可见窗口里从容登录


async def _logged_in(ctx, page) -> bool:
    # 真·登录 cookie（passport 登录后必有）+ 落到商家工作台/商智工具页 url（poll 跳过前 9s 防初始 goto 误判）
    try:
        names = {c["name"] for c in await ctx.cookies() if "jd" in c.get("domain", "")}
        if AUTH & names:
            return True
    except Exception:
        pass
    u = page.url or ""
    return ("/jdm/" in u) or ("sz-online" in u)


def _flush(m: str) -> None:
    print(m, flush=True)


async def main() -> None:
    SESS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            locale="zh-CN", viewport={"width": 1440, "height": 900},
            record_har_path=HAR, record_har_content="embed",
        )
        page = await ctx.new_page()
        try:
            await page.goto("https://shop.jd.com/jdm/home", wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            _flush(f"GOTO_ERR {str(exc)[:160]}")
        _flush("BROWSER_OPEN 请在【这个弹出的窗口】里登录京麦商家后台（不要用你自己的浏览器）")

        ok = False
        waited = 0
        while waited < POLL_SECONDS:
            await page.wait_for_timeout(3000)
            waited += 3
            if waited >= 9 and await _logged_in(ctx, page):  # 跳过前 9s 让初始 goto 的重定向落定
                ok = True
                break
        if not ok:
            _flush("TIMEOUT 未检测到登录")
            await browser.close()
            sys.exit(3)
        _flush("LOGGED_IN")
        await page.wait_for_timeout(3000)
        await ctx.storage_state(path=str(SESS / "storage_state.json"))
        _flush(f"SESSION_SAVED {SESS / 'storage_state.json'}")

        # 已登录——当前窗口应已是商智仪表盘（登录后自动跳 ReturnUrl=sz-online）。
        # 不再主动 goto sz-online（冷访问会 ERR_CONNECTION_CLOSED）；就在当前页等概况 XHR + 录 HAR。
        for _ in range(3):
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)
        _flush(f"DASH_URL {page.url}")
        clicked = 0
        for kw in ("数据", "经营", "概况", "交易", "成交", "流量", "商品", "订单", "转化"):
            if clicked >= 6:
                break
            try:
                loc = page.get_by_text(kw, exact=False).first
                if await loc.count():
                    await loc.click(timeout=3500)
                    clicked += 1
                    await page.wait_for_timeout(2500)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
            except Exception:
                continue
        _flush(f"NAV_CLICKS {clicked}")
        await page.wait_for_timeout(2000)
        await ctx.close()  # flush HAR
        await browser.close()
        _flush(f"HAR_SAVED {HAR}")


asyncio.run(main())
