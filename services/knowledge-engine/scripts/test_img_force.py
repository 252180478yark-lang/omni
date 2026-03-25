"""Force Feishu to render all images by expanding viewport + manipulating DOM."""
import asyncio, logging, re, base64
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

    captured = {}
    async def on_response(response):
        if "internal-api-drive-stream" in response.url and response.ok:
            token_m = re.search(r"/(cover|preview)/([^/?]+)", response.url)
            if token_m:
                try:
                    body = await response.body()
                    if len(body) > 500:
                        captured[token_m.group(2)] = body
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

    # Extract document first
    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    matches = IMG_RE.findall(doc["markdown"])
    tokens_needed = set()
    for _, u in matches:
        m = re.search(r"/cover/([^/?]+)/", u)
        if m:
            tokens_needed.add(m.group(1))

    print(f"Tokens needed: {len(tokens_needed)}")
    print(f"Already captured: {len(captured)}")

    # Strategy: force all blocks to render by manipulating the virtual scroll
    # 1. Remove any overflow:hidden or virtual scroll containers
    await target_frame.evaluate("""() => {
        // Remove all overflow constraints
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const style = getComputedStyle(el);
            if (style.overflow === 'hidden' || style.overflowY === 'hidden') {
                el.style.overflow = 'visible';
                el.style.overflowY = 'visible';
            }
        }
        // Expand body to full height
        document.body.style.height = 'auto';
        document.body.style.minHeight = '50000px';
        document.documentElement.style.height = 'auto';
        document.documentElement.style.overflow = 'visible';
    }""")

    await page.wait_for_timeout(3000)

    # Aggressive scrolling: scroll through in small steps, pausing to let images load
    total_h = await target_frame.evaluate("document.documentElement.scrollHeight")
    print(f"\nScroll height after DOM fix: {total_h}")

    pos = 0
    while pos < total_h + 1000:
        await target_frame.evaluate(f"window.scrollTo(0, {pos})")
        await page.wait_for_timeout(500)
        pos += 400
        if pos % 4000 == 0:
            await page.wait_for_timeout(2000)  # Extra wait every ~10 steps
            print(f"  Scrolled to {pos}, captured: {len(captured)}")

    # Final wait
    await page.wait_for_timeout(5000)

    # Scroll back through for any missed images
    while pos > 0:
        pos -= 800
        await target_frame.evaluate(f"window.scrollTo(0, {max(0, pos)})")
        await page.wait_for_timeout(300)

    await page.wait_for_timeout(3000)

    print(f"\nFinal captured: {len(captured)}")
    matched = tokens_needed & set(captured.keys())
    unmatched = tokens_needed - set(captured.keys())
    print(f"Matched: {len(matched)} / {len(tokens_needed)}")
    if unmatched:
        print(f"Still missing: {len(unmatched)} tokens")

    # Check how many <img> elements exist now
    img_info = await target_frame.evaluate("""() => {
        const imgs = document.querySelectorAll('img');
        return {
            total: imgs.length,
            blobs: Array.from(imgs).filter(i => i.src?.startsWith('blob:')).length,
            loaded: Array.from(imgs).filter(i => i.complete && i.naturalWidth > 0).length,
        };
    }""")
    print(f"DOM images: total={img_info['total']}, blobs={img_info['blobs']}, loaded={img_info['loaded']}")

    # Save captured images
    if captured:
        img_dir = Path("/tmp/test_imgs2")
        img_dir.mkdir(exist_ok=True)
        saved = 0
        for token, body in captured.items():
            if token in tokens_needed:
                (img_dir / f"{token}.png").write_bytes(body)
                saved += 1
        print(f"\nSaved {saved} images to /tmp/test_imgs2/")

    await browser.close()
    await pw.stop()

asyncio.run(test())
