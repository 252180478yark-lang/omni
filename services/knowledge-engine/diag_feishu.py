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

    url = "https://bytedance.larkoffice.com/docx/BqWsdwuzGo611ix5Uq4cfT53nQb"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    result = await page.evaluate("""() => {
        const cv = window.DATA && window.DATA.clientVars;
        if (!cv || !cv.data) return JSON.stringify({error: 'no data'});
        const bmap = cv.data.block_map || {};

        const cellsWithText = [];
        const cellsNoText = [];
        for (const [bid, block] of Object.entries(bmap)) {
            const bd = block.data || {};
            if (bd.type !== 'table_cell') continue;
            const t = bd.text;
            const hasText = t && t.initialAttributedTexts && (
                (t.initialAttributedTexts.text && Object.keys(t.initialAttributedTexts.text).length > 0) ||
                (t.initialAttributedTexts.aPool && t.initialAttributedTexts.aPool.length > 0)
            );
            if (hasText && cellsWithText.length < 2) {
                cellsWithText.push({bid, data: JSON.stringify(bd).substring(0, 500)});
            }
            if (!hasText && cellsNoText.length < 3) {
                cellsNoText.push({bid, data: JSON.stringify(bd).substring(0, 500)});
            }
        }

        const textNoText = [];
        for (const [bid, block] of Object.entries(bmap)) {
            const bd = block.data || {};
            if (bd.type !== 'text') continue;
            const t = bd.text;
            const hasText = t && t.initialAttributedTexts && (
                (t.initialAttributedTexts.text && Object.keys(t.initialAttributedTexts.text).length > 0) ||
                (t.initialAttributedTexts.aPool && t.initialAttributedTexts.aPool.length > 0)
            );
            if (!hasText && textNoText.length < 3) {
                textNoText.push({bid, data: JSON.stringify(bd).substring(0, 500)});
            }
        }

        const otherNoText = [];
        for (const [bid, block] of Object.entries(bmap)) {
            const bd = block.data || {};
            if (!['callout','bullet','heading2','heading6','heading1'].includes(bd.type)) continue;
            const t = bd.text;
            const hasText = t && t.initialAttributedTexts && (
                (t.initialAttributedTexts.text && Object.keys(t.initialAttributedTexts.text).length > 0) ||
                (t.initialAttributedTexts.aPool && t.initialAttributedTexts.aPool.length > 0)
            );
            if (!hasText && otherNoText.length < 3) {
                otherNoText.push({bid, type: bd.type, data: JSON.stringify(bd).substring(0, 800)});
            }
        }

        return JSON.stringify({cellsWithText, cellsNoText, textNoText, otherNoText});
    }""")

    r = json.loads(result)
    print("=== TABLE CELLS WITH TEXT (sample) ===")
    for c in r["cellsWithText"]:
        print(f"  {c['bid']}: {c['data'][:300]}")
    print()
    print("=== TABLE CELLS NO TEXT (sample) ===")
    for c in r["cellsNoText"]:
        print(f"  {c['bid']}: {c['data'][:300]}")
    print()
    print("=== TEXT BLOCKS NO TEXT (sample) ===")
    for c in r["textNoText"]:
        print(f"  {c['bid']}: {c['data'][:300]}")
    print()
    print("=== OTHER BLOCKS NO TEXT (sample) ===")
    for c in r["otherNoText"]:
        print(f"  {c['bid']} [{c['type']}]: {c['data'][:500]}")

    await browser.close()
    await pw.stop()

asyncio.run(diag())
