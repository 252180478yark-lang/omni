"""Use the exact cookies and headers from successful Feishu XHR to download all images."""
import asyncio, logging, re, json
import httpx
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

    # Collect cookies from successful XHR via CDP
    xhr_cookies = {}

    def on_extra_info(params):
        rid = params.get("requestId", "")
        headers = params.get("headers", {})
        cookie_header = headers.get("Cookie") or headers.get("cookie")
        if cookie_header and "larkoffice" not in cookie_header:
            pass
        # Save cookie from any request that has larkoffice-related cookies
        if cookie_header and ("passport_web_did" in cookie_header or "QXV0aHpDb250ZXh0" in cookie_header):
            xhr_cookies["cookie_str"] = cookie_header
            xhr_cookies["all_headers"] = {k: v for k, v in headers.items()}

    cdp.on("Network.requestWillBeSentExtraInfo", on_extra_info)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    if not xhr_cookies:
        print("No successful XHR cookies captured!")
        await cdp.detach(); await browser.close(); await pw.stop(); return

    print(f"\nCaptured cookie string: {xhr_cookies['cookie_str']}")
    print(f"\nFull headers from successful XHR:")
    for k, v in sorted(xhr_cookies['all_headers'].items()):
        print(f"  {k}: {v[:150]}")

    # Get document & image URLs
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!"); await cdp.detach(); await browser.close(); await pw.stop(); return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No doc!"); await cdp.detach(); await browser.close(); await pw.stop(); return

    matches = IMG_RE.findall(doc["markdown"])
    print(f"\nFound {len(matches)} images\n")

    # Use the EXACT headers from the successful XHR
    req_headers = {
        "Cookie": xhr_cookies["cookie_str"],
        "Origin": xhr_cookies["all_headers"].get("Origin", "https://bytedance.larkoffice.com"),
        "Referer": xhr_cookies["all_headers"].get("Referer", "https://bytedance.larkoffice.com/"),
        "User-Agent": xhr_cookies["all_headers"].get("User-Agent", ""),
        "Sec-Fetch-Storage-Access": "active",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }
    # Copy sec-ch-ua headers
    for k, v in xhr_cookies["all_headers"].items():
        if k.startswith("sec-ch-"):
            req_headers[k] = v

    print("=== Downloading ALL images with exact XHR headers ===")
    success = 0
    total_bytes = 0

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for i, (alt, img_url) in enumerate(matches):
            resp = await client.get(img_url, headers=req_headers)
            if resp.status_code == 200 and len(resp.content) > 500:
                success += 1
                total_bytes += len(resp.content)
                ct = resp.headers.get("content-type", "?")
                print(f"  [{i+1}/{len(matches)}] OK: {len(resp.content):>8} bytes  {ct}")
            else:
                print(f"  [{i+1}/{len(matches)}] FAIL: status={resp.status_code} size={len(resp.content)}")

    print(f"\n=== Results: {success}/{len(matches)} succeeded, {total_bytes // 1024} KB total ===")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
