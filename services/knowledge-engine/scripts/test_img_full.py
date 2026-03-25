"""Full scrolling image capture — scroll slowly through entire document."""
import asyncio, logging, re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(
        storage_state="/app/data/harvester_auth.json",
        viewport={"width": 1920, "height": 1080},
    )
    page = await ctx.new_page()

    captured_images = {}

    async def on_response(response):
        url = response.url
        if "internal-api-drive-stream" in url and response.ok:
            token_m = re.search(r"/(cover|preview)/([^/?]+)", url)
            if token_m:
                token = token_m.group(2)
                try:
                    body = await response.body()
                    if len(body) > 500:
                        ct = response.headers.get("content-type", "image/png")
                        captured_images[token] = {"data": body, "ct": ct}
                        print(f"    Captured: {token} ({len(body)} bytes)")
                except:
                    pass

    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!")
        await browser.close(); await pw.stop()
        return

    # Get total scroll height
    scroll_height = await target_frame.evaluate("document.documentElement.scrollHeight")
    print(f"Scroll height: {scroll_height}")
    print("Scrolling through document...")

    # Scroll slowly through the document in 800px increments
    pos = 0
    step = 800
    while pos < scroll_height:
        await target_frame.evaluate(f"window.scrollTo(0, {pos})")
        await page.wait_for_timeout(1500)
        pos += step
        # Recheck scroll height (might grow as content renders)
        new_height = await target_frame.evaluate("document.documentElement.scrollHeight")
        if new_height > scroll_height:
            scroll_height = new_height
            print(f"  Scroll height grew to {scroll_height}")

    # Scroll to bottom and wait
    await target_frame.evaluate(f"window.scrollTo(0, {scroll_height})")
    await page.wait_for_timeout(3000)

    # Scroll back up slowly (in case some images only render on re-visit)
    pos = scroll_height
    while pos > 0:
        pos -= 1200
        await target_frame.evaluate(f"window.scrollTo(0, {max(0, pos)})")
        await page.wait_for_timeout(800)

    await page.wait_for_timeout(3000)

    # Extract document
    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    matches = IMG_RE.findall(doc["markdown"])
    tokens_in_doc = set()
    for _, cdn_url in matches:
        m = re.search(r"/cover/([^/?]+)/", cdn_url)
        if m:
            tokens_in_doc.add(m.group(1))

    print(f"\nTokens in document: {len(tokens_in_doc)}")
    print(f"Tokens captured: {len(captured_images)}")
    matched = tokens_in_doc & set(captured_images.keys())
    unmatched = tokens_in_doc - set(captured_images.keys())
    print(f"Matched: {len(matched)} / {len(tokens_in_doc)}")
    if unmatched:
        print(f"Missing tokens: {list(unmatched)[:5]}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
