"""Access the Feishu doc iframe and extract content from it."""
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

    # List all frames
    print(f"Total frames: {len(page.frames)}")
    for i, frame in enumerate(page.frames):
        print(f"  Frame {i}: name='{frame.name}', url='{frame.url[:100]}'")

    # Try to find a frame with content
    for i, frame in enumerate(page.frames):
        try:
            text_len = await frame.evaluate("() => document.body ? (document.body.innerText || '').length : -1")
            html_len = await frame.evaluate("() => document.body ? document.body.innerHTML.length : -1")
            print(f"\n  Frame {i}: text={text_len}, html={html_len}")

            if text_len > 100:
                snippet = await frame.evaluate("() => (document.body.innerText || '').substring(0, 800)")
                print(f"  SNIPPET: {snippet[:800]}")

            if html_len > 1000 and text_len < 100:
                # Check if it has specific Feishu content elements
                check = await frame.evaluate("""() => {
                    const editors = document.querySelectorAll('[contenteditable]');
                    const textBlocks = document.querySelectorAll('[data-block-type]');
                    const divs = document.querySelectorAll('div');
                    return {
                        editors: editors.length,
                        textBlocks: textBlocks.length,
                        divs: divs.length,
                        bodyChildCount: document.body.children.length,
                        bodyFirstChildTag: document.body.children[0] ? document.body.children[0].tagName : 'none',
                        bodyFirstChildClass: document.body.children[0] ? (document.body.children[0].className || '').substring(0, 80) : 'none',
                    };
                }""")
                print(f"  Details: {check}")

        except Exception as e:
            print(f"\n  Frame {i}: ERROR - {str(e)[:100]}")

    # Try an alternative: use page.locator to find iframe and get its content
    print("\n=== TRYING LOCATOR APPROACH ===")
    try:
        iframe_locator = page.frame_locator("iframe")
        content = await iframe_locator.locator("body").inner_text()
        print(f"  iframe body text: {len(content)} chars")
        print(f"  Snippet: {content[:500]}")
    except Exception as e:
        print(f"  Locator ERROR: {str(e)[:200]}")

    # Also try: maybe the content is rendered by JS and we need to wait longer
    print("\n=== CHECKING MAIN PAGE AFTER LONGER WAIT ===")
    await page.wait_for_timeout(5000)
    # Try to find the editor container
    check2 = await page.evaluate("""() => {
        // Check for ne-editor (Feishu new editor)
        const neEditor = document.querySelector('.ne-editor-wrap');
        const catalog = document.querySelector('.catalog-wrapper');
        const docContent = document.querySelector('.doc-content-container');
        const suiteDoc = document.querySelector('.suite-docx');
        return {
            neEditor: neEditor ? {text: (neEditor.innerText||'').length, html: neEditor.innerHTML.length} : null,
            catalog: catalog ? {text: (catalog.innerText||'').length} : null,
            docContent: docContent ? {text: (docContent.innerText||'').length, html: docContent.innerHTML.length} : null,
            suiteDoc: suiteDoc ? {text: (suiteDoc.innerText||'').length, html: suiteDoc.innerHTML.length} : null,
        };
    }""")
    print(f"  Main page elements: {check2}")

    await browser.close()
    await pw.stop()

asyncio.run(diag())
