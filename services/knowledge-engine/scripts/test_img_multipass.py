"""Multi-pass approach: reload page with different scroll positions to capture all images."""
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

    all_captured = {}
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
                if token not in all_captured or len(data) > len(all_captured[token]):
                    all_captured[token] = data
        except:
            pass

    cdp.on("Network.requestWillBeSent", on_request)
    cdp.on("Network.loadingFinished", lambda p: asyncio.ensure_future(on_finished(p)))

    base_url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"

    # First pass: get doc structure and initial images
    print("Pass 0: Initial load...")
    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)
    print(f"  Captured: {len(all_captured)}")

    # Get document info
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    tokens_needed = set()
    if target_frame:
        raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
        doc = parse_feishu_document(raw)
        if doc:
            matches = IMG_RE.findall(doc["markdown"])
            for _, u in matches:
                m = re.search(r"/cover/([^/?]+)", u)
                if m:
                    tokens_needed.add(m.group(1))

    print(f"  Tokens needed: {len(tokens_needed)}")
    print(f"  Already captured: {len(all_captured)}")
    print(f"  Missing: {len(tokens_needed - set(all_captured.keys()))}")

    # Get the total scroll height of the content container
    total_h = await page.evaluate(
        "document.querySelector('#knowledge-detail')?.scrollHeight || 0"
    )
    print(f"  Content scroll height: {total_h}")

    # Multi-pass: reload with different scroll positions
    # The content is ~10500px, viewport shows ~660px. Divide into sections.
    scroll_positions = list(range(0, total_h, 600))
    print(f"\n  Will try {len(scroll_positions)} scroll positions")

    for pass_num, scroll_pos in enumerate(scroll_positions[1:], 1):
        if len(tokens_needed - set(all_captured.keys())) == 0:
            print(f"\nAll {len(tokens_needed)} images captured!")
            break

        before = len(all_captured)

        # Navigate and immediately scroll before iframe loads
        # Use JS to set scroll position as fast as possible
        await page.evaluate(f"""() => {{
            // Pre-set scroll position
            const observer = new MutationObserver(() => {{
                const el = document.querySelector('#knowledge-detail');
                if (el) {{
                    el.scrollTo(0, {scroll_pos});
                    observer.disconnect();
                }}
            }});
            observer.observe(document.body, {{ childList: true, subtree: true }});
        }}""")

        await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)

        # Immediately try to scroll
        await page.evaluate(f"""() => {{
            const el = document.querySelector('#knowledge-detail');
            if (el) el.scrollTo(0, {scroll_pos});
        }}""")

        await page.wait_for_timeout(12000)

        new_imgs = len(all_captured) - before
        missing = len(tokens_needed - set(all_captured.keys()))
        if new_imgs > 0:
            print(f"  Pass {pass_num} (scroll={scroll_pos}): +{new_imgs} new → total {len(all_captured)}, missing {missing}")
        else:
            # Don't print every pass if no new images
            if pass_num % 5 == 0:
                print(f"  Pass {pass_num} (scroll={scroll_pos}): no new images, missing {missing}")

    # Results
    captured = tokens_needed & set(all_captured.keys())
    missing = tokens_needed - set(all_captured.keys())
    print(f"\n=== FINAL RESULTS ===")
    print(f"  Needed: {len(tokens_needed)}")
    print(f"  Captured: {len(captured)}")
    print(f"  Missing: {len(missing)}")
    total_bytes = sum(len(all_captured[t]) for t in captured)
    print(f"  Total size: {total_bytes // 1024} KB")

    if missing:
        print(f"  Missing tokens: {list(missing)[:5]}...")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
