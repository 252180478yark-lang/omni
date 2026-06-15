"""切片2 调试：抓 jdsz SPA 真实 szgateway 请求的 headers（找 -402「不安全的请求」缺的那个安全头）。

监听 page request 事件，逮住前几个 szgateway/api/lowcode POST，打印其 headers + body 头部。
对比我们裸 fetch 缺的头 → 复制进回放即可（若是计算签名则另谋）。
    docker exec -w /app -e DISPLAY=:99 omni-scout-agent python scripts/_jd_capture_headers.py
"""
import asyncio
import json
from playwright.async_api import async_playwright

SESS = "/app/sessions/jd/storage_state.json"
captured: list[dict] = []


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(storage_state=SESS, locale="zh-CN",
                                        viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()

        def on_req(req):
            if "szgateway.jd.com/api/lowcode" in req.url and req.method == "POST" and len(captured) < 4:
                captured.append({"url": req.url, "headers": dict(req.headers), "post": (req.post_data or "")[:160]})

        pg.on("request", on_req)
        try:
            await pg.goto("https://jdsz.jd.com/", wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            print("GOTO_ERR", str(exc)[:140], flush=True)
        await pg.wait_for_timeout(8000)
        for kw in ("经营概况", "实时", "交易", "流量", "商品", "数据"):
            if len(captured) >= 4:
                break
            try:
                loc = pg.get_by_text(kw, exact=False).first
                if await loc.count():
                    await loc.click(timeout=3000)
                    await pg.wait_for_timeout(4000)
            except Exception:
                continue
        await pg.wait_for_timeout(2000)
        print(f"CAPTURED {len(captured)} szgateway POSTs", flush=True)
        for c in captured[:2]:
            print("\nURL", c["url"], flush=True)
            print("HEADERS", json.dumps(c["headers"], ensure_ascii=False), flush=True)
            print("POST", c["post"], flush=True)
        await browser.close()


asyncio.run(main())
