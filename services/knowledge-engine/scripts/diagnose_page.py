"""Diagnose the actual page structure for harvester debugging."""
import asyncio


async def diagnose():
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    url = "https://support.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221"
    print("1. Navigating to:", url)
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    print("2. Page title:", await page.title())
    print("3. Page URL:", page.url)

    content = await page.content()
    if "login" in page.url.lower():
        print("!! REDIRECTED TO LOGIN PAGE")

    tree_spans = await page.query_selector_all(".base-tree-title span[title]")
    print(f"4. Tree title spans found: {len(tree_spans)}")
    if tree_spans:
        for s in tree_spans[:5]:
            title = await s.get_attribute("title")
            print(f"   - {title}")

    frames = page.frames
    print(f"5. Total frames: {len(frames)}")
    for f in frames:
        print(f"   - Frame URL: {f.url[:200]}")

    if tree_spans:
        first_title = await tree_spans[0].get_attribute("title")
        print(f"6. Clicking first article: {first_title}")
        await tree_spans[0].click()
        await page.wait_for_timeout(5000)

        frames = page.frames
        print(f"7. Frames after click: {len(frames)}")
        for f in frames:
            furl = f.url[:200]
            has_feishu = any(k in f.url for k in ["larkoffice", "feishu", "larksuite"])
            print(f"   - {furl}")
            print(f"     is_feishu: {has_feishu}")

            if has_feishu:
                print("   8. Trying to extract window.DATA.clientVars...")
                try:
                    raw = await f.evaluate("""() => {
                        try {
                            if (window.DATA && window.DATA.clientVars) {
                                return JSON.stringify(window.DATA.clientVars).substring(0, 500);
                            }
                        } catch(e) { return 'ERROR: ' + e.message; }
                        return null;
                    }""")
                    print(f"   clientVars result: {raw}")
                except Exception as e:
                    print(f"   clientVars error: {e}")

    print("9. Checking content selectors on page...")
    selectors = [
        "article", ".article", ".content", ".doc-content",
        ".rich-text", ".markdown-body", ".ql-editor",
        "iframe", ".doc-viewer", ".reader-container",
        ".support-content", ".detail-content",
    ]
    for sel in selectors:
        els = await page.query_selector_all(sel)
        if els:
            print(f"   Found {len(els)} for: {sel}")
            for el in els[:3]:
                tag = await el.evaluate("el => el.tagName")
                text_len = await el.evaluate("el => el.innerText ? el.innerText.length : 0")
                info = f"tag={tag} textLen={text_len}"
                if tag == "IFRAME":
                    src = await el.get_attribute("src") or "(no src)"
                    info += f" src={src[:200]}"
                print(f"     {info}")

    # Also dump first 3000 chars of page HTML to see structure
    html = await page.content()
    print("10. Page HTML snippet (3000 chars):")
    print(html[:3000])

    await browser.close()
    await pw.stop()


asyncio.run(diagnose())
