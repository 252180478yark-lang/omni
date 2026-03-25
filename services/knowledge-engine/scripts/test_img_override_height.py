"""Override window.innerHeight in iframe to trick Feishu into loading all images."""
import asyncio, logging, re
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

# Override window.innerHeight BEFORE any Feishu code reads it
OVERRIDE_HEIGHT_JS = """
(() => {
    Object.defineProperty(window, 'innerHeight', {
        get: () => 50000,
        configurable: true,
    });
    // Also override visualViewport
    if (window.visualViewport) {
        Object.defineProperty(window.visualViewport, 'height', {
            get: () => 50000,
            configurable: true,
        });
    }
    // Override document.documentElement.clientHeight
    Object.defineProperty(document.documentElement, 'clientHeight', {
        get: () => 50000,
        configurable: true,
    });
    // Override getBoundingClientRect to make everything "visible"
    const origGetBCR = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function() {
        const rect = origGetBCR.call(this);
        // If the element is below the original viewport, pretend it's visible
        // by clamping the top to within viewport
        return rect;
    };
})();
"""

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")

    # Inject the height override BEFORE page loads
    await ctx.add_init_script(OVERRIDE_HEIGHT_JS)

    page = await ctx.new_page()

    captured = {}
    unique_tokens_requested = set()

    async def on_response(response):
        if "internal-api-drive-stream" not in response.url or not response.ok:
            return
        token_m = re.search(r"/(cover|preview)/([^/?]+)", response.url)
        if token_m:
            try:
                body = await response.body()
                if len(body) > 500:
                    token = token_m.group(2)
                    if token not in captured or len(body) > len(captured[token]):
                        captured[token] = body
                        print(f"  ++ {token} ({len(body)} bytes) [total: {len(captured)}]")
            except:
                pass

    async def on_request(request):
        if "internal-api-drive-stream" in request.url:
            token_m = re.search(r"/(cover|preview)/([^/?]+)", request.url)
            if token_m:
                unique_tokens_requested.add(token_m.group(2))

    page.on("response", on_response)
    page.on("request", on_request)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Loading with overridden innerHeight...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if target_frame:
        h = await target_frame.evaluate("window.innerHeight")
        print(f"  Iframe innerHeight: {h}")

    print(f"  Images captured: {len(captured)}")
    print(f"  Unique tokens requested: {len(unique_tokens_requested)}")

    # Also try: override after page load and trigger resize
    if target_frame:
        print("\n=== Post-load override + resize event ===")
        before = len(captured)
        await target_frame.evaluate("""() => {
            Object.defineProperty(window, 'innerHeight', { get: () => 50000, configurable: true });
            Object.defineProperty(document.documentElement, 'clientHeight', { get: () => 50000, configurable: true });
            window.dispatchEvent(new Event('resize'));
            // Also try triggering the opendoc scroll handler
            window.dispatchEvent(new CustomEvent('scroll', { detail: { scrollTop: 0, viewportHeight: 50000 } }));
        }""")
        await page.wait_for_timeout(10000)
        print(f"  After resize event: {len(captured)} (was {before})")
        print(f"  Tokens requested: {len(unique_tokens_requested)}")

    # Get doc info
    if target_frame:
        raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
        doc = parse_feishu_document(raw)
        if doc:
            matches = IMG_RE.findall(doc["markdown"])
            tokens = set()
            for _, u in matches:
                m = re.search(r"/cover/([^/?]+)", u)
                if m: tokens.add(m.group(1))
            print(f"\n  Total in doc: {len(tokens)}")
            print(f"  Captured: {len(captured)}")
            print(f"  Requested: {len(unique_tokens_requested)}")

    print(f"\n=== RESULT: {len(captured)} images captured ===")

    await browser.close()
    await pw.stop()

asyncio.run(test())
