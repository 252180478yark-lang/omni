"""Navigate directly to the Feishu doc as first-party, avoiding third-party cookie restrictions."""
import asyncio, logging, re, base64
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

    img_responses = {}
    request_urls = {}

    def on_request(params):
        url = params.get("request", {}).get("url", "")
        if "internal-api-drive-stream" in url:
            request_urls[params.get("requestId", "")] = url

    async def on_finished(params):
        rid = params.get("requestId", "")
        if rid not in request_urls:
            return
        url = request_urls[rid]
        token_m = re.search(r"/(cover|preview)/([^/?]+)", url)
        if not token_m:
            return
        try:
            body = await cdp.send("Network.getResponseBody", {"requestId": rid})
            data = base64.b64decode(body["body"]) if body.get("base64Encoded") else body["body"].encode()
            if len(data) > 500:
                token = token_m.group(2)
                if token not in img_responses or len(data) > len(img_responses[token]):
                    img_responses[token] = data
                    print(f"  ++ {token} ({len(data)} bytes) [total: {len(img_responses)}]")
        except:
            pass

    cdp.on("Network.requestWillBeSent", on_request)
    cdp.on("Network.loadingFinished", lambda p: asyncio.ensure_future(on_finished(p)))

    # Step 1: Load the yuntu page first to initialize larkoffice cookies
    yuntu_url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Step 1: Loading yuntu page to init larkoffice session...")
    await page.goto(yuntu_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)
    print(f"  Initial images: {len(img_responses)}")

    # Extract larkoffice cookies via CDP
    lark_cookies = {}
    def on_extra_info(params):
        sent = params.get("associatedCookies", [])
        for c in sent:
            if c.get("blockedReasons"):
                continue
            cookie = c.get("cookie", {})
            name = cookie.get("name", "")
            domain = cookie.get("domain", "")
            if "larkoffice" in domain:
                lark_cookies[name] = cookie

    cdp.on("Network.requestWillBeSentExtraInfo", on_extra_info)
    await page.wait_for_timeout(3000)

    # Get the Feishu doc URL from the iframe
    feishu_url = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            feishu_url = frame.url
            break

    print(f"  Feishu URL: {feishu_url}")
    print(f"  Larkoffice cookies captured: {list(lark_cookies.keys())}")

    if not feishu_url:
        print("No Feishu URL found!")
        await cdp.detach(); await browser.close(); await pw.stop(); return

    # Step 2: Set cookies on larkoffice domain via CDP
    print("\nStep 2: Setting cookies on larkoffice domain...")
    for name, cookie_data in lark_cookies.items():
        for domain in [".larkoffice.com", "bytedance.larkoffice.com", "internal-api-drive-stream.larkoffice.com"]:
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
            except:
                pass
    print(f"  Set {len(lark_cookies)} cookies on 3 domains")

    # Also get all cookies via CDP and verify
    all_result = await cdp.send("Network.getAllCookies")
    lark_count = sum(1 for c in all_result.get("cookies", []) if "lark" in c.get("domain", ""))
    print(f"  Total larkoffice cookies in browser: {lark_count}")

    # Step 3: Navigate DIRECTLY to the Feishu doc
    print(f"\nStep 3: Navigating directly to Feishu doc...")
    img_responses.clear()
    request_urls.clear()

    await page.goto(feishu_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(10000)
    print(f"  Images after direct load: {len(img_responses)}")

    # Step 4: Check page structure and scroll
    scroll_info = await page.evaluate("""() => {
        const results = [];
        const walk = (el, depth) => {
            if (depth > 15) return;
            const style = getComputedStyle(el);
            if (el.scrollHeight > el.clientHeight + 20 &&
                (style.overflowY === 'auto' || style.overflowY === 'scroll')) {
                results.push({
                    tag: el.tagName,
                    cls: Array.from(el.classList || []).slice(0, 3).join(' '),
                    scrollH: el.scrollHeight,
                    clientH: el.clientHeight,
                });
            }
            for (const child of el.children) walk(child, depth + 1);
        };
        walk(document.documentElement, 0);
        return results;
    }""")
    print(f"  Scrollable elements: {len(scroll_info)}")
    for s in scroll_info:
        print(f"    {s['tag']}.{s['cls']} sH={s['scrollH']} cH={s['clientH']}")

    # Try scrolling the page directly
    print("\nStep 4: Scrolling through document...")
    before = len(img_responses)
    total_h = await page.evaluate("document.documentElement.scrollHeight")
    print(f"  Document scroll height: {total_h}")

    pos = 0
    while pos < total_h:
        await page.evaluate(f"window.scrollTo(0, {pos})")
        await page.wait_for_timeout(2000)
        pos += 600
        new_h = await page.evaluate("document.documentElement.scrollHeight")
        if new_h > total_h:
            total_h = new_h
            print(f"  scrollH grew to {total_h}")
        if len(img_responses) > before:
            print(f"  *** New images! Total: {len(img_responses)} ***")
            before = len(img_responses)

    await page.wait_for_timeout(5000)
    print(f"  Final images: {len(img_responses)}")

    # Check doc for needed images
    try:
        raw = await page.evaluate(FEISHU_GET_DATA_JS)
        doc = parse_feishu_document(raw)
        if doc:
            matches = IMG_RE.findall(doc["markdown"])
            print(f"  Images in doc: {len(matches)}")
    except:
        print("  Could not extract doc from direct page")

    print(f"\n=== RESULT: {len(img_responses)} images captured ===")
    total = sum(len(v) for v in img_responses.values())
    print(f"  Total: {total // 1024} KB")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
