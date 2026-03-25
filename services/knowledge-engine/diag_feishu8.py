"""Intercept network requests during scroll to find block-loading API."""
import asyncio, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

async def diag():
    from playwright.async_api import async_playwright
    from pathlib import Path

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)

    auth_path = r"\app\data\feishu_auth.json"
    ctx_kw = {}
    if Path(auth_path).exists():
        ctx_kw["storage_state"] = auth_path
    ctx = await browser.new_context(**ctx_kw)
    page = await ctx.new_page()

    api_calls = []

    async def on_response(response):
        url = response.url
        if any(kw in url for kw in ["block", "doc", "content", "chunk", "render"]):
            try:
                body = await response.text()
                api_calls.append({
                    "url": url[:200],
                    "status": response.status,
                    "bodyLen": len(body),
                    "bodySnippet": body[:300] if body else "",
                })
            except:
                api_calls.append({
                    "url": url[:200],
                    "status": response.status,
                    "bodyLen": -1,
                })

    page.on("response", on_response)

    url = "https://bytedance.larkoffice.com/docx/BqWsdwuzGo611ix5Uq4cfT53nQb"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    initial_count = len(api_calls)
    print(f"API calls during load: {initial_count}")
    for c in api_calls:
        print(f"  [{c['status']}] {c['url'][:120]} ({c['bodyLen']} bytes)")
    print()

    # Now scroll the document container
    print("=== SCROLLING .bear-web-x-container ===")
    api_calls.clear()

    await page.evaluate("""() => {
        return new Promise(resolve => {
            const el = document.querySelector('.bear-web-x-container');
            if (!el) { resolve('no container'); return; }
            const step = Math.max(500, Math.floor(el.scrollHeight / 15));
            let pos = 0;
            const timer = setInterval(() => {
                pos += step;
                el.scrollTo(0, pos);
                if (pos >= el.scrollHeight) {
                    clearInterval(timer);
                    el.scrollTo(0, 0);
                    resolve('done');
                }
            }, 300);
            setTimeout(() => { clearInterval(timer); resolve('timeout'); }, 30000);
        });
    }""")
    await page.wait_for_timeout(5000)

    print(f"\nAPI calls during scroll: {len(api_calls)}")
    for c in api_calls:
        print(f"  [{c['status']}] {c['url'][:120]} ({c['bodyLen']} bytes)")
        if c["bodyLen"] > 1000:
            print(f"    snippet: {c.get('bodySnippet', '')[:200]}")

    # Check block_map after scroll
    after = await page.evaluate("""() => {
        try {
            const bm = window.DATA.clientVars.data.block_map;
            let withText = 0;
            for (const [bid, block] of Object.entries(bm)) {
                const bd = block.data || {};
                const t = bd.text;
                const hasText = t && t.initialAttributedTexts && (
                    (t.initialAttributedTexts.text && Object.keys(t.initialAttributedTexts.text).length > 0) ||
                    (t.initialAttributedTexts.aPool && t.initialAttributedTexts.aPool.length > 0)
                );
                if (hasText) withText++;
            }
            return JSON.stringify({total: Object.keys(bm).length, withText});
        } catch(e) { return JSON.stringify({error: e.message}); }
    }""")
    print(f"\nBlock map after scroll: {after}")

    page.remove_listener("response", on_response)
    await browser.close()
    await pw.stop()

asyncio.run(diag())
