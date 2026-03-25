"""Wait for full render, check scrollable container, get complete text."""
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

    # Track how innerText grows over time
    for wait in [2, 5, 8, 12, 15]:
        await page.wait_for_timeout(1000)
        result = await page.evaluate("""() => {
            const body = document.body;
            const text = body ? (body.innerText || '') : '';
            
            // Also check block_map size
            let blockCount = 0;
            try {
                blockCount = Object.keys(window.DATA.clientVars.data.block_map).length;
            } catch(e) {}
            
            return JSON.stringify({
                textLen: text.length,
                blockCount,
                elapsed: """ + str(wait) + """,
            });
        }""")
        r = json.loads(result)
        print(f"  t={r['elapsed']}s: innerText={r['textLen']} chars, blocks={r['blockCount']}")

    # Now find scrollable containers in the main page
    scroll_info = await page.evaluate("""() => {
        const els = document.querySelectorAll('*');
        const scrollable = [];
        for (const el of els) {
            const style = window.getComputedStyle(el);
            const canScroll = (style.overflow === 'auto' || style.overflow === 'scroll' ||
                              style.overflowY === 'auto' || style.overflowY === 'scroll');
            if (canScroll && el.scrollHeight > el.clientHeight + 100) {
                scrollable.push({
                    tag: el.tagName,
                    className: (el.className || '').substring(0, 80),
                    id: el.id || '',
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    diff: el.scrollHeight - el.clientHeight,
                });
            }
        }
        return JSON.stringify(scrollable);
    }""")
    scrollables = json.loads(scroll_info)
    print(f"\n=== SCROLLABLE CONTAINERS ({len(scrollables)}) ===")
    for s in scrollables:
        print(f"  <{s['tag']} id='{s['id']}' class='{s['className'][:50]}'> scrollH={s['scrollHeight']}, clientH={s['clientHeight']}, diff={s['diff']}")

    # Scroll the largest scrollable container
    if scrollables:
        biggest = max(scrollables, key=lambda x: x["diff"])
        sel = f"#{biggest['id']}" if biggest["id"] else f".{biggest['className'].split()[0]}" if biggest["className"] else biggest["tag"]
        print(f"\n=== SCROLLING: {sel} (diff={biggest['diff']}) ===")

        scroll_result = await page.evaluate("""(selector) => {
            return new Promise(resolve => {
                const el = document.querySelector(selector);
                if (!el) { resolve({error: 'not found'}); return; }
                const step = Math.max(500, Math.floor(el.scrollHeight / 20));
                let pos = 0;
                const timer = setInterval(() => {
                    pos += step;
                    el.scrollTo(0, pos);
                    if (pos >= el.scrollHeight) {
                        clearInterval(timer);
                        el.scrollTo(0, 0);
                        resolve({scrolled: true, scrollHeight: el.scrollHeight});
                    }
                }, 150);
                setTimeout(() => { clearInterval(timer); resolve({scrolled: true, timeout: true}); }, 30000);
            });
        }""", sel)
        print(f"  Scroll result: {scroll_result}")
        await page.wait_for_timeout(5000)

    # Check text and blocks after scrolling
    final = await page.evaluate("""() => {
        const body = document.body;
        const text = body ? (body.innerText || '') : '';
        let blockCount = 0;
        try {
            blockCount = Object.keys(window.DATA.clientVars.data.block_map).length;
        } catch(e) {}
        return JSON.stringify({textLen: text.length, blockCount});
    }""")
    fr = json.loads(final)
    print(f"\n=== AFTER SCROLL: innerText={fr['textLen']} chars, blocks={fr['blockCount']} ===")

    # Get full text
    full_text = await page.evaluate("() => document.body.innerText || ''")
    print(f"\n=== FULL TEXT ({len(full_text)} chars) ===")
    # Print last 1500 chars to see if the end of document is captured
    print("--- FIRST 800 chars after TOC ---")
    # Skip the TOC/nav part
    lines = full_text.split('\n')
    doc_start = 0
    for i, line in enumerate(lines):
        if '更新公告' in line and i > 5:
            doc_start = i
            break
    content_lines = lines[doc_start:]
    content = '\n'.join(content_lines)
    print(content[:1500])
    print(f"\n--- LAST 500 chars ---")
    print(content[-500:])

    await browser.close()
    await pw.stop()

asyncio.run(diag())
