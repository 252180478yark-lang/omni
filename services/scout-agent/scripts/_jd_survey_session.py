"""切片0 自动勘测：用已存的京麦登录态（无需老板）逛商智/京麦数据页，录 HAR。

登录已是最难的一步且已完成（sessions/jd/storage_state.json）。这脚本 headless 复用该 session，
访问商智/京麦数据入口 + best-effort 点进数据菜单，把业务接口录进 jd_survey.har，再喂 _jd_har_to_catalog.py。
无界面、无需老板。跑（host）：python services/scout-agent/scripts/_jd_survey_session.py
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SESS = Path("services/scout-agent/sessions/jd/storage_state.json")
HAR = "services/scout-agent/catalog/jd_survey.har"
URLS = [
    "https://sz-online.jd.com/",   # 商智工具页（概况自动触发业务 XHR）
    "https://sz.jd.com/",          # 商智网关
    "https://shop.jd.com/jdm/home",  # 京麦商家后台首页
]
NAV_KW = ("数据", "经营概况", "实时", "交易", "成交概况", "流量", "流量来源", "商品", "商品分析", "概况")


async def main() -> None:
    if not SESS.exists():
        print("NO_SESSION 先跑 _jd_login_capture_host.py 登录", flush=True)
        sys.exit(2)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(
            locale="zh-CN", viewport={"width": 1440, "height": 900},
            storage_state=str(SESS), record_har_path=HAR, record_har_content="embed",
        )
        pg = await ctx.new_page()
        for u in URLS:
            try:
                await pg.goto(u, wait_until="domcontentloaded", timeout=45000)
                print(f"VISIT {u} -> {pg.url}", flush=True)
            except Exception as exc:
                print(f"VISIT_ERR {u} {str(exc)[:120]}", flush=True)
                continue
            for _ in range(2):
                try:
                    await pg.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                await pg.wait_for_timeout(2500)
            clicked = 0
            for kw in NAV_KW:
                if clicked >= 8:
                    break
                try:
                    loc = pg.get_by_text(kw, exact=False).first
                    if await loc.count():
                        await loc.click(timeout=3000)
                        clicked += 1
                        await pg.wait_for_timeout(2500)
                        try:
                            await pg.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                except Exception:
                    continue
            print(f"  nav_clicks {clicked}", flush=True)
        await pg.wait_for_timeout(2000)
        await ctx.close()
        await browser.close()
        print(f"HAR_SAVED {HAR}", flush=True)


asyncio.run(main())
