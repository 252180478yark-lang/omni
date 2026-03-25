"""Check Feishu DOM structure after full page scroll."""
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
    await page.wait_for_timeout(5000)

    # Scroll entire page to trigger lazy loading
    scroll_h = await page.evaluate("""() => {
        return new Promise(resolve => {
            const el = document.scrollingElement || document.documentElement;
            if (!el) { resolve(0); return; }
            const step = Math.max(300, Math.floor(el.scrollHeight / 30));
            let pos = 0;
            const timer = setInterval(() => {
                pos += step;
                el.scrollTo(0, pos);
                if (pos >= el.scrollHeight) {
                    clearInterval(timer);
                    el.scrollTo(0, 0);
                    resolve(el.scrollHeight);
                }
            }, 100);
            setTimeout(() => { clearInterval(timer); resolve(el.scrollHeight); }, 20000);
        });
    }""")
    print(f"Scroll height: {scroll_h}")
    await page.wait_for_timeout(3000)

    # Check common Feishu DOM selectors
    result = await page.evaluate("""() => {
        const selectors = [
            '.docx-container',
            '.doc-content',
            '[data-page-id]',
            '.lark-editor',
            '.ne-editor',
            'article',
            '.docx-editor',
            '#docx-container',
            '.render-unit-wrapper',
            '.block-wrapper',
        ];
        const found = {};
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            if (els.length > 0) {
                found[sel] = {
                    count: els.length,
                    firstTagName: els[0].tagName,
                    firstTextLength: els[0].innerText ? els[0].innerText.length : 0,
                    firstClassName: els[0].className.substring(0, 100),
                };
            }
        }
        // Also check document title
        const title = document.title;
        // Check body text length
        const bodyText = document.body.innerText ? document.body.innerText.length : 0;

        // Try to find the main content container by looking for specific patterns
        const allDivs = document.querySelectorAll('div[class]');
        const bigDivs = [];
        for (const d of allDivs) {
            const text = d.innerText || '';
            if (text.length > 2000 && bigDivs.length < 5) {
                bigDivs.push({
                    className: d.className.substring(0, 80),
                    tagName: d.tagName,
                    textLength: text.length,
                    childCount: d.children.length,
                });
            }
        }
        return JSON.stringify({found, title, bodyText, bigDivs});
    }""")
    r = json.loads(result)
    print(f"\nTitle: {r['title']}")
    print(f"Body text length: {r['bodyText']}")

    print("\n=== FOUND SELECTORS ===")
    for sel, info in r["found"].items():
        print(f"  {sel}: count={info['count']}, text={info['firstTextLength']}, tag={info['firstTagName']}, class={info['firstClassName'][:60]}")

    print("\n=== BIG DIVS (text > 2000) ===")
    for d in r["bigDivs"]:
        print(f"  <{d['tagName']} class='{d['className'][:60]}'> text={d['textLength']}, children={d['childCount']}")

    # Get a snippet of the innerText from the largest container
    if r["bigDivs"]:
        snippet = await page.evaluate("""(cls) => {
            const el = document.querySelector('div.' + cls.split(' ')[0]);
            return el ? el.innerText.substring(0, 500) : 'NOT FOUND';
        }""", r["bigDivs"][-1]["className"])
        print(f"\n=== SNIPPET from biggest div ===")
        print(snippet[:500])

    await browser.close()
    await pw.stop()

asyncio.run(diag())
