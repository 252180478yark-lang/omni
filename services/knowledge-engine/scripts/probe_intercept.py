"""Try Playwright with login redirect interception."""
import asyncio
import json
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}


async def main():
    # Step 1: Get JSSDK params from SSR API
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
        r = await client.get(
            "https://yuntu.oceanengine.com/support/content/143250"
            "?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
            "&__ssrDirect=true&graphId=610&mappingType=2"
            "&pageId=445&spaceId=221"
        )
        ssr_data = json.loads(r.text)
        cd = ssr_data["contentData"]
        token = cd["feishuDocxToken"]
        component = cd.get("feishuDocxComponent", {})
        print(f"Token: {token}")
        print(f"AppId: {component.get('appId')}")

    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)

    # Approach 1: Block login redirect via init script
    print("\n=== Approach 1: Block redirect, load support page ===")
    ctx = await browser.new_context()
    page = await ctx.new_page()

    # Block navigation to login pages
    async def handle_route(route):
        url = route.request.url
        if "yuntu_ng/login" in url or "accounts.feishu" in url:
            print(f"  BLOCKED: {url[:100]}")
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", handle_route)

    # Override location.assign/replace to prevent JS redirects
    await page.add_init_script("""
        const _orig_assign = window.location.assign;
        const _orig_replace = window.location.replace;
        Object.defineProperty(window, 'location', {
            get: function() { return window._loc || document.location; },
            set: function(v) {
                if (typeof v === 'string' && (v.includes('login') || v.includes('yuntu_ng'))) {
                    console.log('BLOCKED redirect to:', v);
                    return;
                }
                document.location = v;
            }
        });
    """)

    try:
        await page.goto(
            "https://support.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221",
            wait_until="domcontentloaded",
            timeout=15000,
        )
    except Exception as e:
        print(f"  Navigation: {e}")

    await page.wait_for_timeout(8000)
    print(f"  Final URL: {page.url}")

    frames = page.frames
    print(f"  Frames: {len(frames)}")
    for f in frames:
        furl = f.url[:150]
        print(f"    {furl}")
        if any(k in f.url for k in ["larkoffice", "feishu", "larksuite"]):
            print("    -> FEISHU FRAME FOUND!")
            try:
                raw = await f.evaluate("""() => {
                    if (window.DATA && window.DATA.clientVars) {
                        return JSON.stringify(window.DATA.clientVars).substring(0, 300);
                    }
                    return null;
                }""")
                print(f"    clientVars: {raw}")
            except Exception as ex:
                print(f"    Error: {ex}")

    # Check page content
    try:
        body_text = await page.evaluate("document.body.innerText")
        print(f"  Body text length: {len(body_text)}")
        if body_text.strip():
            print(f"  Body preview: {body_text[:300]}")
    except Exception:
        pass

    await ctx.close()

    # Approach 2: Construct Feishu embed iframe directly
    print("\n=== Approach 2: Direct Feishu embed in blank page ===")
    ctx2 = await browser.new_context()
    page2 = await ctx2.new_page()

    # Navigate to yuntu domain first (for JSSDK url verification)
    await page2.goto("https://yuntu.oceanengine.com", wait_until="commit", timeout=10000)
    await page2.wait_for_timeout(1000)

    # Inject Feishu SDK and component
    sig = component.get("signature", "")
    app_id = component.get("appId", "")
    ts = component.get("timestamp", "")
    nonce = component.get("nonceStr", "")

    result = await page2.evaluate(f"""async () => {{
        // Create a new iframe pointing to the docx
        const iframe = document.createElement('iframe');
        iframe.src = 'https://bytedance.larkoffice.com/docx/{token}?from=from_external_doc';
        iframe.style = 'width:100%;height:800px;border:none;';
        document.body.innerHTML = '';
        document.body.appendChild(iframe);
        return 'iframe_created';
    }}""")
    print(f"  Result: {result}")
    await page2.wait_for_timeout(5000)

    frames2 = page2.frames
    print(f"  Frames: {len(frames2)}")
    for f in frames2:
        print(f"    {f.url[:200]}")

    await ctx2.close()
    await browser.close()
    await pw.stop()


asyncio.run(main())
