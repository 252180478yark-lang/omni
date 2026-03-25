"""Intercept all image network requests from the iframe."""
import asyncio, logging, re
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    page = await ctx.new_page()

    # Capture ALL requests/responses with image tokens
    token_images = {}

    async def on_response(response):
        url = response.url
        # Match any URL containing image tokens
        m = re.search(r"/(HAw3b|SO9eb|FJrRb|[A-Za-z0-9]{20,})", url)
        ct = response.headers.get("content-type", "")
        if "image" in ct or "octet" in ct:
            # Try to extract token from URL
            token_m = re.search(r"/cover/([^/?]+)", url) or re.search(r"/([A-Za-z0-9]{20,30})", url)
            if token_m:
                token = token_m.group(1)
                try:
                    body = await response.body()
                    if len(body) > 1000:
                        token_images[token] = {"size": len(body), "url": url[:150], "ct": ct}
                except:
                    pass

    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url or "feishu" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe found!")
        await browser.close()
        await pw.stop()
        return

    # Get the scroll height and scroll slowly through the document
    scroll_height = await target_frame.evaluate("document.documentElement.scrollHeight")
    print(f"Document scroll height: {scroll_height}")

    scrolled = 0
    while scrolled < scroll_height:
        await target_frame.evaluate(f"window.scrollTo(0, {scrolled})")
        await page.wait_for_timeout(1500)
        scrolled += 600

    await page.wait_for_timeout(3000)

    # Check how many images were loaded
    img_count = await target_frame.evaluate("""() => {
        const imgs = document.querySelectorAll('img');
        return Array.from(imgs).map(i => ({
            src: i.src?.substring(0, 100),
            w: i.naturalWidth,
            h: i.naturalHeight,
            complete: i.complete,
        }));
    }""")
    print(f"\nDOM images: {len(img_count)}")
    for i, img in enumerate(img_count[:20]):
        print(f"  [{i}] {img['w']}x{img['h']} complete={img['complete']} src={img['src']}")

    print(f"\nCaptured image tokens: {len(token_images)}")
    for token, info in list(token_images.items())[:10]:
        print(f"  {token}: {info['size']} bytes, {info['ct']}")
        print(f"    URL: {info['url']}")

    # Now try to convert blob images to base64 via canvas
    print("\n=== Trying canvas extraction ===")
    try:
        result = await target_frame.evaluate("""() => {
            const imgs = document.querySelectorAll('img');
            const results = [];
            for (const img of imgs) {
                if (!img.complete || img.naturalWidth === 0) continue;
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth;
                    canvas.height = img.naturalHeight;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    const dataUrl = canvas.toDataURL('image/png');
                    results.push({
                        size: dataUrl.length,
                        w: img.naturalWidth,
                        h: img.naturalHeight,
                    });
                } catch(e) {
                    results.push({error: e.message, src: img.src?.substring(0, 80)});
                }
            }
            return results;
        }""")
        print(f"Canvas results: {len(result)}")
        for r in result[:5]:
            print(f"  {r}")
    except Exception as e:
        print(f"Canvas error: {e}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
