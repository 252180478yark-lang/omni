"""Check Feishu page structure: iframes, shadow DOM, canvas, etc."""
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

    result = await page.evaluate("""() => {
        const info = {};

        // Check iframes
        const iframes = document.querySelectorAll('iframe');
        info.iframes = [];
        for (const f of iframes) {
            info.iframes.push({
                src: (f.src || '').substring(0, 150),
                id: f.id,
                className: (f.className || '').substring(0, 80),
                width: f.width || f.offsetWidth,
                height: f.height || f.offsetHeight,
            });
        }

        // Check canvas
        const canvases = document.querySelectorAll('canvas');
        info.canvasCount = canvases.length;

        // Check shadow hosts
        const allEls = document.querySelectorAll('*');
        let shadowCount = 0;
        for (const el of allEls) {
            if (el.shadowRoot) shadowCount++;
        }
        info.shadowHostCount = shadowCount;

        // Check innerHTML length
        info.bodyInnerHTMLLength = document.body ? document.body.innerHTML.length : 0;
        info.bodyInnerTextLength = document.body ? (document.body.innerText || '').length : 0;

        // Check if document.body has visibility issues
        const bodyStyle = document.body ? window.getComputedStyle(document.body) : null;
        info.bodyDisplay = bodyStyle ? bodyStyle.display : 'N/A';
        info.bodyVisibility = bodyStyle ? bodyStyle.visibility : 'N/A';

        // Sample body innerHTML (first 1000 chars)
        info.bodyHTMLSnippet = document.body ? document.body.innerHTML.substring(0, 1500) : '';

        // Check for React/Vue root
        const appDiv = document.querySelector('#app') || document.querySelector('#root') || document.querySelector('#__next');
        if (appDiv) {
            info.appDiv = {
                id: appDiv.id,
                childCount: appDiv.children.length,
                innerTextLength: (appDiv.innerText || '').length,
                innerHTMLLength: appDiv.innerHTML.length,
            };
        }

        return JSON.stringify(info);
    }""")
    r = json.loads(result)

    print(f"Body innerHTML length: {r['bodyInnerHTMLLength']}")
    print(f"Body innerText length: {r['bodyInnerTextLength']}")
    print(f"Body display: {r['bodyDisplay']}")
    print(f"Body visibility: {r['bodyVisibility']}")
    print(f"Canvas count: {r['canvasCount']}")
    print(f"Shadow host count: {r['shadowHostCount']}")

    print(f"\n=== IFRAMES ({len(r['iframes'])}) ===")
    for f in r["iframes"]:
        print(f"  id='{f['id']}' class='{f['className']}' src='{f['src'][:120]}' size={f['width']}x{f['height']}")

    if r.get("appDiv"):
        print(f"\n=== APP DIV ===")
        print(f"  id: {r['appDiv']['id']}, children: {r['appDiv']['childCount']}")
        print(f"  innerText: {r['appDiv']['innerTextLength']}, innerHTML: {r['appDiv']['innerHTMLLength']}")

    print(f"\n=== BODY HTML SNIPPET ===")
    print(r["bodyHTMLSnippet"][:1500])

    # Also try to read from iframes
    for i, frame_info in enumerate(r["iframes"]):
        try:
            frame = page.frames[i + 1]  # +1 to skip main frame
            frame_text = await frame.evaluate("() => document.body ? (document.body.innerText || '').length : 0")
            frame_html = await frame.evaluate("() => document.body ? document.body.innerHTML.length : 0")
            print(f"\n=== IFRAME {i} text={frame_text}, html={frame_html} ===")
            if frame_text > 100:
                snippet = await frame.evaluate("() => (document.body.innerText || '').substring(0, 500)")
                print(f"  Snippet: {snippet[:500]}")
        except Exception as e:
            print(f"\n=== IFRAME {i} ERROR: {e} ===")

    await browser.close()
    await pw.stop()

asyncio.run(diag())
