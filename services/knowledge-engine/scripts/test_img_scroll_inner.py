"""Make iframe container scrollable, then scroll through to trigger image lazy loading."""
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
    request_statuses = {}

    def on_request(params):
        url = params.get("request", {}).get("url", "")
        if "internal-api-drive-stream" in url:
            request_urls[params.get("requestId", "")] = url

    def on_response_received(params):
        url = params.get("response", {}).get("url", "")
        status = params.get("response", {}).get("status", 0)
        if "internal-api-drive-stream" in url:
            token_m = re.search(r"/(cover|preview)/([^/?]+)", url)
            t = token_m.group(2) if token_m else "?"
            if t not in request_statuses:
                request_statuses[t] = []
            request_statuses[t].append(status)

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
    cdp.on("Network.responseReceived", on_response_received)
    cdp.on("Network.loadingFinished", lambda p: asyncio.ensure_future(on_finished(p)))

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(10000)
    print(f"Initial load: {len(img_responses)} images")

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!"); await cdp.detach(); await browser.close(); await pw.stop(); return

    # Strategy 1: Make bear-web-x-container scrollable and scroll it
    print("\n=== Strategy 1: Make container scrollable ===")
    container_info = await target_frame.evaluate("""() => {
        const el = document.querySelector('.bear-web-x-container');
        if (!el) return { found: false };
        el.style.overflow = 'auto';
        el.style.overflowY = 'auto';
        el.classList.remove('opendoc-unscrollable');
        return {
            found: true,
            scrollH: el.scrollHeight,
            clientH: el.clientHeight,
            overflow: getComputedStyle(el).overflowY,
        };
    }""")
    print(f"  Container: {container_info}")

    if container_info.get("found"):
        before = len(img_responses)
        total_h = container_info.get("scrollH", 0)
        pos = 0
        while pos < total_h:
            await target_frame.evaluate(f"""() => {{
                const el = document.querySelector('.bear-web-x-container');
                el.scrollTo(0, {pos});
                // Also dispatch scroll event
                el.dispatchEvent(new Event('scroll', {{ bubbles: true }}));
            }}""")
            await page.wait_for_timeout(3000)
            pos += 500
            new_h = await target_frame.evaluate(
                "document.querySelector('.bear-web-x-container')?.scrollHeight || 0"
            )
            if new_h > total_h:
                total_h = new_h
                print(f"  scrollH grew to {total_h} at pos={pos}")
            if len(img_responses) > before:
                print(f"  New images! Total: {len(img_responses)}")
                before = len(img_responses)

        await page.wait_for_timeout(5000)
        print(f"  After Strategy 1: {len(img_responses)} images")

    # Strategy 2: Simultaneously scroll the parent #knowledge-detail
    print("\n=== Strategy 2: Sync scroll parent + emit resize events ===")
    before = len(img_responses)

    total_h = await page.evaluate(
        "document.querySelector('#knowledge-detail')?.scrollHeight || document.documentElement.scrollHeight"
    )
    pos = 0
    while pos < total_h:
        await page.evaluate(f"""() => {{
            const el = document.querySelector('#knowledge-detail');
            if (el) el.scrollTo(0, {pos});
            else window.scrollTo(0, {pos});
            // Dispatch resize to trick lazy loaders
            window.dispatchEvent(new Event('resize'));
        }}""")
        # Also post scroll message to iframe
        if target_frame:
            try:
                await target_frame.evaluate(f"""() => {{
                    window.dispatchEvent(new Event('scroll'));
                    window.dispatchEvent(new Event('resize'));
                    document.dispatchEvent(new Event('scroll', {{ bubbles: true }}));
                }}""")
            except:
                pass
        await page.wait_for_timeout(3000)
        pos += 500
        new_h = await page.evaluate(
            "document.querySelector('#knowledge-detail')?.scrollHeight || document.documentElement.scrollHeight"
        )
        if new_h > total_h:
            total_h = new_h

    await page.wait_for_timeout(5000)
    print(f"  After Strategy 2: {len(img_responses)} images")

    # Print status summary
    print(f"\n=== Request status summary ===")
    for token, statuses in sorted(request_statuses.items()):
        status_str = ", ".join(str(s) for s in statuses)
        captured = "CAPTURED" if token in img_responses else "MISSING"
        print(f"  {token}: [{status_str}] {captured}")

    # Get doc to count needed
    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if doc:
        matches = IMG_RE.findall(doc["markdown"])
        tokens_needed = set()
        for _, u in matches:
            m = re.search(r"/cover/([^/?]+)", u)
            if m:
                tokens_needed.add(m.group(1))
        print(f"\n  Tokens needed: {len(tokens_needed)}")
        print(f"  Tokens captured: {len(img_responses)}")
        print(f"  Tokens requested: {len(request_statuses)}")

    print(f"\n=== FINAL: {len(img_responses)} unique images ===")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
