"""切片0 探针 v2：商智是商家工具，登录走京麦/商家，不是消费者 passport。
直接进商智工具页 sz-online.jd.com，看它跳到哪个登录页（应是京麦商家登录），截图+dump。
    docker exec -w /app -e DISPLAY=:99 omni-scout-agent python scripts/_jd_login_probe.py
"""
import asyncio
from playwright.async_api import async_playwright

CANDIDATES = [
    "https://sz-online.jd.com/",   # 商智工具页（未登录会跳商家登录）
    "https://shop.jd.com/",        # 京东商家
]


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(locale="zh-CN", viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()
        for url in CANDIDATES:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(6000)
                print(f"\n--- goto {url}")
                print("FINAL_URL:", page.url)
                try:
                    print("TITLE:", await page.title())
                except Exception:
                    pass
                try:
                    texts = await page.eval_on_selector_all(
                        "a,button,div[role=tab],li,span,h1,h2,h3",
                        "els => els.map(e=>e.innerText && e.innerText.trim()).filter(t=>t && t.length<14)"
                    )
                    uniq = []
                    for t in texts:
                        if t and t not in uniq:
                            uniq.append(t)
                    print("TEXTS:", " | ".join(uniq[:40]))
                except Exception as exc:
                    print("texts err:", str(exc)[:120])
            except Exception as exc:
                print(f"--- goto {url} ERR {str(exc)[:160]}")
        await page.screenshot(path="/app/catalog/_jd_login_probe.png", full_page=False)
        print("\nscreenshot -> /app/catalog/_jd_login_probe.png (last page)")
        await browser.close()


asyncio.run(main())
