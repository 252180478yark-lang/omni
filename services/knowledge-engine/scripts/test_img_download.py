"""Debug: check cookies and test different download strategies."""
import asyncio, logging, json, re
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
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    # Check all cookies in context
    all_cookies = await ctx.cookies()
    domains = {}
    for c in all_cookies:
        d = c.get("domain", "")
        domains.setdefault(d, []).append(c["name"])
    print("=== Browser Context Cookies ===")
    for d, names in sorted(domains.items()):
        print(f"  {d}: {len(names)} cookies -> {names[:5]}...")

    # Find iframe and extract doc
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url or "feishu" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No feishu iframe found!")
        await browser.close()
        await pw.stop()
        return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No document extracted!")
        await browser.close()
        await pw.stop()
        return

    matches = IMG_RE.findall(doc["markdown"])
    print(f"\n=== Found {len(matches)} images ===")

    if matches:
        cdn_url = matches[0][1]
        print(f"\nTesting first image: {cdn_url[:120]}...")

        # Strategy 1: new page navigation
        print("\n--- Strategy: Navigate new page to image URL ---")
        dl_page = await ctx.new_page()
        try:
            resp = await dl_page.goto(cdn_url, wait_until="commit", timeout=10000)
            if resp:
                print(f"  Status: {resp.status}")
                print(f"  Headers: {dict(list(resp.headers.items())[:5])}")
                if resp.ok:
                    body = await resp.body()
                    print(f"  Body size: {len(body)} bytes")
                    with open("/tmp/test_img.png", "wb") as f:
                        f.write(body)
                    print("  Saved to /tmp/test_img.png")
        except Exception as e:
            print(f"  Error: {e}")
        await dl_page.close()

        # Strategy 2: frame.evaluate fetch
        print("\n--- Strategy: fetch() inside iframe ---")
        try:
            result = await target_frame.evaluate("""async (url) => {
                try {
                    const resp = await fetch(url, {credentials: 'include'});
                    if (!resp.ok) return {status: resp.status, error: resp.statusText};
                    const blob = await resp.blob();
                    return {status: resp.status, size: blob.size, type: blob.type};
                } catch(e) {
                    return {error: e.message};
                }
            }""", cdn_url)
            print(f"  Result: {result}")
        except Exception as e:
            print(f"  Error: {e}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
