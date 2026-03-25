"""Use iframe's own JS context to fetch images - should carry Storage Access cookies."""
import asyncio, logging, re, json
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    page = await ctx.new_page()

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe found!")
        await browser.close(); await pw.stop(); return

    # Extract document to get image URLs
    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No doc extracted!")
        await browser.close(); await pw.stop(); return

    matches = IMG_RE.findall(doc["markdown"])
    print(f"Found {len(matches)} image URLs in document")

    if not matches:
        await browser.close(); await pw.stop(); return

    # Test: fetch first 3 images from WITHIN the iframe context
    for alt, img_url in matches[:5]:
        print(f"\nTrying to fetch: {alt or 'image'}")
        print(f"  URL: {img_url[:120]}...")

        result = await target_frame.evaluate("""async (url) => {
            try {
                const resp = await fetch(url, { credentials: 'include' });
                return {
                    ok: resp.ok,
                    status: resp.status,
                    contentType: resp.headers.get('content-type'),
                    size: parseInt(resp.headers.get('content-length') || '0'),
                    headers: Object.fromEntries([...resp.headers.entries()].slice(0, 10)),
                };
            } catch (e) {
                return { error: e.message };
            }
        }""", img_url)

        print(f"  Result: {json.dumps(result, indent=2)}")

    # If fetch works, try to actually download the image bytes
    test_url = matches[0][1]
    print(f"\n=== Full download test ===")
    download_result = await target_frame.evaluate("""async (url) => {
        try {
            const resp = await fetch(url, { credentials: 'include' });
            if (!resp.ok) return { error: `HTTP ${resp.status}` };
            const blob = await resp.blob();
            // Convert to base64 to pass back
            const reader = new FileReader();
            return await new Promise(resolve => {
                reader.onload = () => {
                    const b64 = reader.result.split(',')[1];
                    resolve({
                        ok: true,
                        size: blob.size,
                        type: blob.type,
                        b64_length: b64.length,
                        b64_prefix: b64.substring(0, 40),
                    });
                };
                reader.readAsDataURL(blob);
            });
        } catch (e) {
            return { error: e.message };
        }
    }""", test_url)
    print(f"  Download result: {json.dumps(download_result, indent=2)}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
