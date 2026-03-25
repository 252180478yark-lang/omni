"""Capture Set-Cookie from Feishu init, replay them, then download all images."""
import asyncio, logging, re, base64, json
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    page = await ctx.new_page()
    cdp = await ctx.new_cdp_session(page)
    await cdp.send("Network.enable")

    # Track ALL Set-Cookie headers from any larkoffice domain
    set_cookie_headers = []
    all_response_cookies = {}

    def on_response_extra(params):
        headers = params.get("headers", {})
        # Check for set-cookie headers
        for key, value in headers.items():
            if key.lower() == "set-cookie":
                set_cookie_headers.append(value)

        # Check blocked cookies
        blocked = params.get("blockedCookies", [])
        if blocked:
            for b in blocked[:5]:
                cookie = b.get("cookie", {})
                reasons = b.get("blockedReasons", [])
                if "lark" in cookie.get("domain", ""):
                    all_response_cookies[cookie.get("name", "?")] = {
                        "value": cookie.get("value", ""),
                        "domain": cookie.get("domain", ""),
                        "blocked": reasons,
                    }

    # Track cookies in successful XHR requests
    xhr_cookie_strings = []

    def on_request_extra(params):
        headers = params.get("headers", {})
        cookie = headers.get("Cookie") or headers.get("cookie") or ""
        if "QXV0aHpDb250ZXh0" in cookie or "passport_web_did" in cookie:
            xhr_cookie_strings.append(cookie)

    cdp.on("Network.responseReceivedExtraInfo", on_response_extra)
    cdp.on("Network.requestWillBeSentExtraInfo", on_request_extra)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Loading page...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    print(f"\nSet-Cookie headers captured: {len(set_cookie_headers)}")
    for sc in set_cookie_headers[:20]:
        # Parse cookie name
        parts = sc.split(";")
        name_val = parts[0].strip()
        name = name_val.split("=")[0]
        # Check for larkoffice domain
        domain = ""
        for p in parts:
            if "domain" in p.lower():
                domain = p.strip()
        print(f"  {name}... ({domain})")

    print(f"\nBlocked response cookies: {len(all_response_cookies)}")
    for name, info in list(all_response_cookies.items())[:10]:
        print(f"  {name}: domain={info['domain']} blocked={info['blocked']}")

    print(f"\nXHR cookie strings captured: {len(xhr_cookie_strings)}")
    if xhr_cookie_strings:
        # Parse the cookie string to get individual cookies
        cookie_str = xhr_cookie_strings[0]
        print(f"  Cookie string: {cookie_str}")

        # Use these EXACT cookies with CDP to set them on the CDN domain
        print("\n=== Setting XHR cookies on CDN domain via CDP ===")
        cookie_pairs = cookie_str.split("; ")
        for pair in cookie_pairs:
            eq = pair.find("=")
            if eq < 0:
                continue
            name = pair[:eq].strip()
            value = pair[eq+1:].strip()
            if not value:
                continue

            # Set on the CDN domain specifically
            for domain in [".larkoffice.com", "internal-api-drive-stream.larkoffice.com"]:
                try:
                    result = await cdp.send("Network.setCookie", {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": "/",
                        "secure": True,
                        "httpOnly": True,
                        "sameSite": "None",
                    })
                    if result.get("success"):
                        print(f"  Set: {name} on {domain}")
                except Exception as e:
                    print(f"  Error: {name} on {domain}: {e}")

        # Now try downloading images with these cookies set in the browser
        target_frame = None
        for frame in page.frames:
            if "larkoffice" in frame.url:
                target_frame = frame
                break

        if target_frame:
            raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
            doc = parse_feishu_document(raw)
            if doc:
                matches = IMG_RE.findall(doc["markdown"])
                print(f"\n=== Testing download with cookies set ({len(matches)} images) ===")

                # Try XHR from iframe context - cookies should now be available
                for i, (alt, img_url) in enumerate(matches[:5]):
                    token_m = re.search(r"/cover/([^/?]+)", img_url)
                    token = token_m.group(1) if token_m else "?"
                    result = await target_frame.evaluate("""(url) => {
                        return new Promise((resolve) => {
                            const xhr = new XMLHttpRequest();
                            xhr.open('GET', url, true);
                            xhr.responseType = 'arraybuffer';
                            xhr.withCredentials = true;
                            xhr.onload = () => resolve({ ok: xhr.status === 200, status: xhr.status, size: xhr.response?.byteLength || 0 });
                            xhr.onerror = () => resolve({ ok: false, error: 'network' });
                            xhr.send();
                        });
                    }""", img_url)
                    print(f"  [{i+1}] {token}: {result}")

        # Also try: create a new page on bytedance.larkoffice.com domain
        # with the cookies set, and use it to fetch images
        print("\n=== Alternative: New page on larkoffice.com ===")
        page2 = await ctx.new_page()
        # Navigate to larkoffice.com to establish the domain context
        try:
            await page2.goto("https://bytedance.larkoffice.com/", wait_until="domcontentloaded", timeout=15000)
        except:
            print("  Failed to navigate to larkoffice.com")

        if target_frame and doc:
            test_url = matches[0][1]
            result2 = await page2.evaluate(f"""async () => {{
                try {{
                    const r = await fetch("{test_url}", {{ credentials: 'include' }});
                    return {{ ok: r.ok, status: r.status, size: parseInt(r.headers.get('content-length') || '0') }};
                }} catch(e) {{
                    return {{ error: e.message }};
                }}
            }}""")
            print(f"  Page2 fetch: {result2}")

        await page2.close()

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
