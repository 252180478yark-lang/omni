"""Resize the Feishu iframe to be very tall, forcing the virtual renderer to load all content."""
import asyncio, logging, re, base64
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    # Use a VERY tall viewport
    ctx = await browser.new_context(
        storage_state="/app/data/harvester_auth.json",
        viewport={"width": 1920, "height": 900},
    )
    page = await ctx.new_page()
    cdp = await ctx.new_cdp_session(page)
    await cdp.send("Network.enable")

    # Track image captures
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

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Step 1: Navigate...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)
    print(f"  Images after initial load: {len(img_responses)}")

    # Step 2: Find and resize the iframe
    iframe_info = await page.evaluate("""() => {
        const iframes = document.querySelectorAll('iframe');
        const results = [];
        for (const iframe of iframes) {
            const rect = iframe.getBoundingClientRect();
            results.push({
                src: iframe.src?.substring(0, 80),
                width: rect.width,
                height: rect.height,
                style: iframe.style.cssText?.substring(0, 100),
                parentTag: iframe.parentElement?.tagName,
                parentCls: iframe.parentElement?.className?.substring(0, 60),
            });
        }
        return results;
    }""")
    print(f"\nIframes found: {len(iframe_info)}")
    for i, info in enumerate(iframe_info):
        print(f"  [{i}] {info['src']} ({info['width']}x{info['height']}) parent={info['parentTag']}.{info['parentCls']}")

    # Resize the larkoffice iframe and its container to be very tall
    print("\nStep 2: Resizing iframe to very tall...")
    await page.evaluate("""() => {
        const iframes = document.querySelectorAll('iframe');
        for (const iframe of iframes) {
            if (iframe.src?.includes('larkoffice')) {
                // Remove height restrictions on the iframe and all ancestors
                iframe.style.height = '50000px';
                iframe.style.maxHeight = '50000px';
                iframe.style.minHeight = '50000px';

                let el = iframe.parentElement;
                for (let i = 0; i < 10 && el; i++) {
                    el.style.height = 'auto';
                    el.style.maxHeight = 'none';
                    el.style.overflow = 'visible';
                    el = el.parentElement;
                }
            }
        }
    }""")

    # Wait for more images to load
    print("  Waiting 15s for more images...")
    await page.wait_for_timeout(15000)
    print(f"  Images after resize: {len(img_responses)}")

    # Step 3: Also try scrolling the main page
    print("\nStep 3: Scrolling main page...")
    main_scroll_h = await page.evaluate("document.documentElement.scrollHeight")
    print(f"  Main page scroll height: {main_scroll_h}")

    pos = 0
    while pos < main_scroll_h:
        await page.evaluate(f"window.scrollTo(0, {pos})")
        await page.wait_for_timeout(2000)
        pos += 800
        new_h = await page.evaluate("document.documentElement.scrollHeight")
        if new_h > main_scroll_h:
            main_scroll_h = new_h
            print(f"  Scroll height grew to {main_scroll_h}")

    await page.wait_for_timeout(5000)
    print(f"  Images after main scroll: {len(img_responses)}")

    # Step 4: Also scroll within the iframe
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if target_frame:
        print("\nStep 4: Checking iframe internals...")
        iframe_scroll_h = await target_frame.evaluate("document.documentElement.scrollHeight")
        print(f"  Iframe scroll height: {iframe_scroll_h}")

        if iframe_scroll_h > 2000:
            print(f"  Scrolling iframe (height={iframe_scroll_h})...")
            pos = 0
            while pos < iframe_scroll_h:
                await target_frame.evaluate(f"window.scrollTo(0, {pos})")
                await page.wait_for_timeout(2000)
                pos += 800
                new_h = await target_frame.evaluate("document.documentElement.scrollHeight")
                if new_h > iframe_scroll_h:
                    iframe_scroll_h = new_h
                    print(f"    Iframe scroll height grew to {iframe_scroll_h}")
            await page.wait_for_timeout(5000)
            print(f"  Images after iframe scroll: {len(img_responses)}")

        # Get document to check total images needed
        raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
        doc = parse_feishu_document(raw)
        if doc:
            matches = IMG_RE.findall(doc["markdown"])
            tokens_needed = set()
            for _, u in matches:
                m = re.search(r"/cover/([^/?]+)", u)
                if m:
                    tokens_needed.add(m.group(1))
            matched = tokens_needed & set(img_responses.keys())
            print(f"\n  Tokens in doc: {len(tokens_needed)}")
            print(f"  Tokens captured: {len(img_responses)}")
            print(f"  Matched: {len(matched)} / {len(tokens_needed)}")

    print(f"\n=== RESULT: {len(img_responses)} unique images captured ===")
    total = sum(len(v) for v in img_responses.values())
    print(f"  Total: {total // 1024} KB")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
