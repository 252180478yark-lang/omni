"""Pre-set auth cookies via CDP then create <img> elements for all images."""
import asyncio, logging, re, base64
from pathlib import Path
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

    # Phase 1: Load page, let Feishu init, capture auth cookies
    auth_cookies = {}

    def on_extra_info(params):
        sent = params.get("associatedCookies", [])
        for c in sent:
            if c.get("blockedReasons"):
                continue
            cookie = c.get("cookie", {})
            name = cookie.get("name", "")
            if name in ("_csrf_token", "passport_web_did", "passport_trace_id", "QXV0aHpDb250ZXh0", "swp_csrf_token", "t_beda37"):
                auth_cookies[name] = cookie

    cdp.on("Network.requestWillBeSentExtraInfo", on_extra_info)

    # Also capture image responses
    img_responses = {}
    request_urls = {}

    def on_request_sent(params):
        url = params.get("request", {}).get("url", "")
        if "internal-api-drive-stream" in url:
            request_urls[params.get("requestId", "")] = url

    async def on_loading_finished(params):
        rid = params.get("requestId", "")
        if rid not in request_urls:
            return
        url = request_urls[rid]
        token_m = re.search(r"/(cover|preview)/([^/?]+)", url)
        if not token_m:
            return
        try:
            body_result = await cdp.send("Network.getResponseBody", {"requestId": rid})
            if body_result.get("base64Encoded"):
                data = base64.b64decode(body_result["body"])
            else:
                data = body_result["body"].encode()
            if len(data) > 500:
                token = token_m.group(2)
                if token not in img_responses or len(data) > len(img_responses[token]):
                    img_responses[token] = data
                    print(f"  Captured via CDP: {token} ({len(data)} bytes)")
        except Exception as e:
            pass

    cdp.on("Network.requestWillBeSent", on_request_sent)
    cdp.on("Network.loadingFinished", lambda p: asyncio.ensure_future(on_loading_finished(p)))

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Phase 1: Initial load to capture auth cookies...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    print(f"\n  Auth cookies captured: {list(auth_cookies.keys())}")
    print(f"  Images captured from initial load: {len(img_responses)}")

    # Phase 2: Set cookies on CDN domain via CDP
    print("\nPhase 2: Setting cookies on CDN domain...")
    for name, cookie_data in auth_cookies.items():
        domain = ".larkoffice.com"
        try:
            await cdp.send("Network.setCookie", {
                "name": name,
                "value": cookie_data.get("value", ""),
                "domain": domain,
                "path": "/",
                "secure": True,
                "httpOnly": cookie_data.get("httpOnly", False),
                "sameSite": "None",
            })
            # Also set on the CDN subdomain specifically
            await cdp.send("Network.setCookie", {
                "name": name,
                "value": cookie_data.get("value", ""),
                "domain": "internal-api-drive-stream.larkoffice.com",
                "path": "/",
                "secure": True,
                "httpOnly": cookie_data.get("httpOnly", False),
                "sameSite": "None",
            })
            print(f"  Set: {name} on {domain}")
        except Exception as e:
            print(f"  Error setting {name}: {e}")

    # Phase 3: Get document & find missing images
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!")
        await cdp.detach(); await browser.close(); await pw.stop(); return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No doc!")
        await cdp.detach(); await browser.close(); await pw.stop(); return

    matches = IMG_RE.findall(doc["markdown"])
    print(f"\nFound {len(matches)} images in doc")

    missing_urls = []
    for alt, img_url in matches:
        token_m = re.search(r"/cover/([^/?]+)", img_url)
        if token_m and token_m.group(1) not in img_responses:
            missing_urls.append((alt, img_url, token_m.group(1)))

    print(f"Missing: {len(missing_urls)}")

    # Phase 3b: Reload the page - now cookies are set, <img> tags should work
    print("\nPhase 3: Reloading page with pre-set cookies...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    print(f"  Images captured after reload: {len(img_responses)}")

    missing_after = []
    for alt, img_url in matches:
        token_m = re.search(r"/cover/([^/?]+)", img_url)
        if token_m and token_m.group(1) not in img_responses:
            missing_after.append(token_m.group(1))
    print(f"  Still missing: {len(missing_after)}")

    # Phase 4: Try creating <img> tags for remaining missing images
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if target_frame and missing_after:
        print(f"\nPhase 4: Creating <img> elements for {len(missing_after)} missing images...")
        remaining = [(alt, img_url) for alt, img_url in matches 
                     if any(t in img_url for t in missing_after)]

        for i, (alt, img_url) in enumerate(remaining[:5]):
            token_m = re.search(r"/cover/([^/?]+)", img_url)
            token = token_m.group(1) if token_m else "?"

            result = await target_frame.evaluate("""(url) => {
                return new Promise((resolve) => {
                    const img = new Image();
                    img.onload = () => resolve({ ok: true, w: img.naturalWidth, h: img.naturalHeight });
                    img.onerror = () => resolve({ ok: false, error: 'failed' });
                    img.src = url;
                    setTimeout(() => resolve({ ok: false, error: 'timeout' }), 8000);
                });
            }""", img_url)
            print(f"  [{i+1}] {token}: {result}")
            await page.wait_for_timeout(2000)

    # Results
    print(f"\n=== TOTAL: {len(img_responses)} / {len(matches)} images captured ===")
    total = sum(len(v) for v in img_responses.values())
    print(f"  Total size: {total // 1024} KB")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
