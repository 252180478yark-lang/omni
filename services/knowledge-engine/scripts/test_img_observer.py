"""Override IntersectionObserver to trick Feishu into rendering all images."""
import asyncio, logging, re
from pathlib import Path
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

INTERCEPT_OBSERVER_JS = """
// Override IntersectionObserver to always report elements as visible
const _OrigIO = window.IntersectionObserver;
window.IntersectionObserver = class extends _OrigIO {
    constructor(callback, options) {
        const wrappedCallback = (entries, observer) => {
            const fakeEntries = entries.map(entry => {
                if (!entry.isIntersecting) {
                    return Object.defineProperties({}, {
                        target: { get: () => entry.target },
                        isIntersecting: { get: () => true },
                        intersectionRatio: { get: () => 1.0 },
                        boundingClientRect: { get: () => entry.boundingClientRect },
                        intersectionRect: { get: () => entry.boundingClientRect },
                        rootBounds: { get: () => entry.rootBounds },
                        time: { get: () => entry.time },
                    });
                }
                return entry;
            });
            callback(fakeEntries, observer);
        };
        super(wrappedCallback, options);
    }
};
"""

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")

    # Inject IntersectionObserver override into ALL frames before any page loads
    await ctx.add_init_script(INTERCEPT_OBSERVER_JS)

    page = await ctx.new_page()

    captured = {}
    async def on_response(response):
        if "internal-api-drive-stream" not in response.url:
            return
        if not response.ok:
            return
        token_m = re.search(r"/(cover|preview)/([^/?]+)", response.url)
        if not token_m:
            return
        try:
            body = await response.body()
            if len(body) > 500:
                token = token_m.group(2)
                if token not in captured or len(body) > len(captured[token]):
                    captured[token] = body
                    print(f"  Captured: {token} ({len(body)} bytes)")
        except:
            pass

    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    print("Waiting for content to load...")
    await page.wait_for_timeout(10000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if target_frame:
        # Also try scrolling slowly through the document
        scroll_h = await target_frame.evaluate("document.documentElement.scrollHeight")
        print(f"Scroll height: {scroll_h}")

        pos = 0
        while pos < scroll_h + 500:
            await target_frame.evaluate(f"window.scrollTo(0, {pos})")
            await page.wait_for_timeout(1500)
            pos += 600
            new_h = await target_frame.evaluate("document.documentElement.scrollHeight")
            if new_h > scroll_h:
                scroll_h = new_h
                print(f"  Scroll height grew to {scroll_h}")

        await page.wait_for_timeout(5000)

        # Extract document
        raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
        doc = parse_feishu_document(raw)
        if doc:
            matches = IMG_RE.findall(doc["markdown"])
            tokens_needed = set()
            for _, u in matches:
                m = re.search(r"/cover/([^/?]+)/", u)
                if m:
                    tokens_needed.add(m.group(1))

            matched = tokens_needed & set(captured.keys())
            print(f"\nTokens in document: {len(tokens_needed)}")
            print(f"Tokens captured: {len(captured)}")
            print(f"Matched: {len(matched)} / {len(tokens_needed)}")
            if tokens_needed - set(captured.keys()):
                missing = list(tokens_needed - set(captured.keys()))[:5]
                print(f"Missing (sample): {missing}")

        # Check DOM images
        img_info = await target_frame.evaluate("""() => {
            const imgs = document.querySelectorAll('img');
            return {
                total: imgs.length,
                blobs: Array.from(imgs).filter(i => i.src?.startsWith('blob:')).length,
                loaded: Array.from(imgs).filter(i => i.complete && i.naturalWidth > 0).length,
            };
        }""")
        print(f"\nDOM images: total={img_info['total']}, blobs={img_info['blobs']}, loaded={img_info['loaded']}")

    print(f"\nTotal unique images captured: {len(captured)}")
    total_bytes = sum(len(v) for v in captured.values())
    print(f"Total size: {total_bytes // 1024} KB")

    await browser.close()
    await pw.stop()

asyncio.run(test())
