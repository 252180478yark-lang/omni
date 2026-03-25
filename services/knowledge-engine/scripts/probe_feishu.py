"""Probe Feishu content extraction approaches."""
import asyncio
import json
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}


async def main():
    # First, get article metadata for the feishuDocxToken
    url = (
        "https://yuntu.oceanengine.com/support/content/143250"
        "?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
        "&__ssrDirect=true&graphId=610&mappingType=2"
        "&pageId=445&spaceId=221"
    )

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
        resp = await client.get(url)
        data = json.loads(resp.text)
        cd = data["contentData"]
        token = cd["feishuDocxToken"]
        component = cd.get("feishuDocxComponent", {})
        print(f"Token: {token}")
        print(f"Component: {json.dumps(component, ensure_ascii=False)}")

        # Try 1: Direct Feishu docx page (get HTML, see if content is SSR'd)
        print("\n=== Try 1: Feishu docx page HTML ===")
        feishu_url = f"https://bytedance.larkoffice.com/docx/{token}"
        try:
            r = await client.get(feishu_url)
            print(f"Status: {r.status_code}, URL: {r.url}")
            print(f"Body[:500]: {r.text[:500]}")
        except Exception as e:
            print(f"Error: {e}")

        # Try 2: support.oceanengine individual article page HTML
        print("\n=== Try 2: support.oceanengine article HTML ===")
        article_url = f"https://support.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
        try:
            r = await client.get(article_url, follow_redirects=False)
            print(f"Status: {r.status_code}")
            if r.status_code in (301, 302, 307, 308):
                print(f"Redirects to: {r.headers.get('location', '?')}")
            else:
                html = r.text
                print(f"HTML length: {len(html)}")
                # Look for feishu iframe or content in HTML
                if "feishu" in html.lower() or "larkoffice" in html.lower():
                    idx = html.lower().find("feishu")
                    if idx == -1:
                        idx = html.lower().find("larkoffice")
                    print(f"Found feishu/larkoffice at pos {idx}")
                    print(f"Context: ...{html[max(0,idx-100):idx+200]}...")
                # Look for __NEXT_DATA__ or window.__DATA
                for marker in ["__NEXT_DATA__", "window.__DATA", "window.DATA", "__SSR_DATA__"]:
                    mi = html.find(marker)
                    if mi >= 0:
                        print(f"Found {marker} at pos {mi}")
                        print(f"Context: {html[mi:mi+300]}")
        except Exception as e:
            print(f"Error: {e}")

        # Try 3: Use JSSDK params to construct iframe URL
        print("\n=== Try 3: Construct Feishu embed URL ===")
        sig = component.get("signature", "")
        app_id = component.get("appId", "")
        ts = component.get("timestamp", "")
        nonce = component.get("nonceStr", "")
        embed_url = (
            f"https://bytedance.larkoffice.com/docx/{token}"
            f"?from=from_external_doc"
        )
        try:
            r = await client.get(embed_url)
            print(f"Status: {r.status_code}, final URL: {r.url}")
            html = r.text
            print(f"HTML length: {len(html)}")
            # Check for window.DATA
            for marker in ["window.DATA", "clientVars", "block_map"]:
                mi = html.find(marker)
                if mi >= 0:
                    print(f"Found '{marker}' at pos {mi}")
                    print(f"Context: {html[mi:mi+200]}")
        except Exception as e:
            print(f"Error: {e}")

        # Try 4: Use Playwright to load the support page (not yundu)
        print("\n=== Try 4: Playwright on support.oceanengine.com ===")
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        # Block navigation to yuntu login
        await page.route("**/yuntu_ng/login**", lambda route: route.abort())

        art_url = "https://support.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
        print(f"Navigating to: {art_url}")
        try:
            await page.goto(art_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            print(f"Navigation error (may be ok): {e}")

        await page.wait_for_timeout(3000)
        print(f"Final URL: {page.url}")

        frames = page.frames
        print(f"Frames: {len(frames)}")
        for f in frames:
            print(f"  - {f.url[:200]}")
            has_feishu = any(k in f.url for k in ["larkoffice", "feishu", "larksuite"])
            if has_feishu:
                print("  -> IS FEISHU FRAME!")
                try:
                    raw = await f.evaluate("""() => {
                        try {
                            if (window.DATA && window.DATA.clientVars) {
                                var cv = window.DATA.clientVars;
                                return JSON.stringify({code: cv.code, hasData: !!cv.data, hasBlockMap: !!(cv.data && cv.data.block_map)});
                            }
                        } catch(e) { return 'ERROR: ' + e.message; }
                        return 'NO_DATA';
                    }""")
                    print(f"  clientVars check: {raw}")
                except Exception as e:
                    print(f"  clientVars error: {e}")

        # Check if there's content directly on the page
        content_el = await page.query_selector(".doc-content, .rich-text, article, .content-body")
        if content_el:
            text = await content_el.inner_text()
            print(f"Direct content found! Length: {len(text)}")
            print(f"Preview: {text[:300]}")

        await browser.close()
        await pw.stop()


asyncio.run(main())
