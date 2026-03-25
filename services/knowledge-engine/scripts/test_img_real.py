"""Check actual image URLs loaded by the browser in the Feishu iframe."""
import asyncio, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    page = await ctx.new_page()

    captured = []

    async def on_response(response):
        ct = response.headers.get("content-type", "")
        if "image" in ct and response.ok:
            captured.append({
                "url": response.url[:200],
                "status": response.status,
                "ct": ct,
                "size": response.headers.get("content-length", "?"),
            })

    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    # Try scrolling iframe to trigger lazy-loaded images
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url or "feishu" in frame.url:
            target_frame = frame
            break

    if target_frame:
        # Scroll inside iframe to load images
        for i in range(5):
            await target_frame.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(1000)

    # Also get img src attributes from iframe
    print("=== Actual <img> src in iframe ===")
    if target_frame:
        img_srcs = await target_frame.evaluate("""() => {
            const imgs = document.querySelectorAll('img');
            return Array.from(imgs).map(i => ({
                src: i.src?.substring(0, 200),
                naturalW: i.naturalWidth,
                naturalH: i.naturalHeight,
                loading: i.loading,
            }));
        }""")
        for i, img in enumerate(img_srcs[:10]):
            print(f"  [{i}] {img['src']}  ({img['naturalW']}x{img['naturalH']})")
        print(f"  ... total: {len(img_srcs)} imgs")

    print(f"\n=== Captured {len(captured)} image responses ===")
    for c in captured[:10]:
        print(f"  [{c['status']}] {c['ct']} ({c['size']} bytes) {c['url']}")

    if captured:
        # Test downloading first captured image
        first_url = captured[0]["url"]
        print(f"\nDownloading first captured image via new page...")
        dl_page = await ctx.new_page()
        resp = await dl_page.goto(first_url, wait_until="commit", timeout=10000)
        if resp and resp.ok:
            body = await resp.body()
            print(f"  Success: {len(body)} bytes")
        else:
            print(f"  Failed: {resp.status if resp else 'no response'}")
        await dl_page.close()

    await browser.close()
    await pw.stop()

asyncio.run(test())
