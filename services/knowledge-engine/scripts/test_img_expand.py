"""Expand the inner container to full height so ALL image blocks become visible simultaneously."""
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
    unique_tokens_requested = set()

    def on_request(params):
        url = params.get("request", {}).get("url", "")
        if "internal-api-drive-stream" in url:
            request_urls[params.get("requestId", "")] = url
            token_m = re.search(r"/(cover|preview)/([^/?]+)", url)
            if token_m:
                unique_tokens_requested.add(token_m.group(2))

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
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(10000)
    print(f"Initial: {len(img_responses)} images, {len(unique_tokens_requested)} tokens requested")

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!")
        await cdp.detach(); await browser.close(); await pw.stop(); return

    # Strategy: Expand the container from within iframe
    print("\n=== Strategy: Expand bear-web-x-container to full height ===")
    expand_result = await target_frame.evaluate("""() => {
        // Find and expand the container and ALL ancestors
        const container = document.querySelector('.bear-web-x-container');
        if (!container) return { error: 'no container' };

        const contentH = container.scrollHeight;

        // Remove all height restrictions
        let el = container;
        while (el && el !== document.documentElement) {
            el.style.height = contentH + 'px';
            el.style.maxHeight = 'none';
            el.style.minHeight = contentH + 'px';
            el.style.overflow = 'visible';
            el.classList.remove('opendoc-unscrollable');
            el = el.parentElement;
        }

        // Also set on html and body
        document.documentElement.style.height = contentH + 'px';
        document.documentElement.style.overflow = 'visible';
        document.body.style.height = contentH + 'px';
        document.body.style.overflow = 'visible';

        return {
            contentH,
            newScrollH: document.documentElement.scrollHeight,
            newClientH: container.clientHeight,
        };
    }""")
    print(f"  Expand result: {expand_result}")

    # Wait for renderer to detect visibility changes
    print("  Waiting 15s for image loads...")
    await page.wait_for_timeout(15000)
    print(f"  After expand: {len(img_responses)} images, {len(unique_tokens_requested)} tokens requested")

    # Try dispatching resize/scroll events to trigger re-detection
    print("  Dispatching events...")
    await target_frame.evaluate("""() => {
        window.dispatchEvent(new Event('resize'));
        window.dispatchEvent(new Event('scroll'));
        document.dispatchEvent(new Event('resize', {bubbles: true}));

        // Trigger IntersectionObserver re-evaluation by toggling visibility
        document.querySelectorAll('[data-block-type]').forEach(el => {
            el.style.visibility = 'hidden';
            requestAnimationFrame(() => { el.style.visibility = ''; });
        });
    }""")
    await page.wait_for_timeout(10000)
    print(f"  After events: {len(img_responses)} images, {len(unique_tokens_requested)} tokens requested")

    # Strategy 2: Use scrollIntoView on each image element in the DOM
    print("\n=== Strategy 2: scrollIntoView on image elements ===")
    img_elements = await target_frame.evaluate("""() => {
        // Find all image blocks in the document
        const imgBlocks = document.querySelectorAll('[data-block-type="image"], .image-block, img, [data-type="image"]');
        const placeholders = document.querySelectorAll('.img-loading, .img-placeholder, [data-image-token]');
        return {
            imgBlocks: imgBlocks.length,
            placeholders: placeholders.length,
            allImages: document.querySelectorAll('img').length,
            blobImages: Array.from(document.querySelectorAll('img')).filter(i => i.src?.startsWith('blob:')).length,
        };
    }""")
    print(f"  DOM image info: {img_elements}")

    # Find ALL elements with image-related attributes
    image_blocks = await target_frame.evaluate("""() => {
        const blocks = [];
        document.querySelectorAll('*').forEach(el => {
            const attrs = {};
            for (const attr of el.attributes || []) {
                if (attr.name.includes('image') || attr.name.includes('token') || attr.name.includes('src')) {
                    attrs[attr.name] = attr.value?.substring(0, 80);
                }
            }
            if (Object.keys(attrs).length > 0) {
                blocks.push({
                    tag: el.tagName,
                    cls: el.className?.substring(0, 60),
                    attrs,
                    top: el.getBoundingClientRect().top,
                });
            }
        });
        return blocks.slice(0, 30);
    }""")
    print(f"  Image-related elements: {len(image_blocks)}")
    for b in image_blocks[:10]:
        print(f"    {b['tag']}.{b['cls'][:30]} top={b['top']:.0f} attrs={b['attrs']}")

    # Count actual tokens
    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if doc:
        matches = IMG_RE.findall(doc["markdown"])
        tokens_needed = set()
        for _, u in matches:
            m = re.search(r"/cover/([^/?]+)", u)
            if m: tokens_needed.add(m.group(1))
        print(f"\n  Tokens in doc: {len(tokens_needed)}")
        print(f"  Tokens captured: {len(img_responses)}")
        print(f"  Tokens requested (total): {len(unique_tokens_requested)}")
        missing = tokens_needed - set(img_responses.keys())
        print(f"  Missing: {len(missing)} → {list(missing)[:5]}")

    print(f"\n=== RESULT: {len(img_responses)} images captured ===")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
