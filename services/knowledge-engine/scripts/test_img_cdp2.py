"""Use CDP to get ALL cookies (including partitioned/HttpOnly) and download images."""
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

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(10000)

    # Use CDP to get ALL cookies
    cdp = await ctx.new_cdp_session(page)

    # Get all cookies via CDP
    result = await cdp.send("Network.getAllCookies")
    all_cookies = result.get("cookies", [])
    print(f"\n=== CDP: Total cookies: {len(all_cookies)} ===")

    by_domain = {}
    for c in all_cookies:
        d = c.get("domain", "")
        if d not in by_domain:
            by_domain[d] = []
        by_domain[d].append(c)

    for domain in sorted(by_domain.keys()):
        clist = by_domain[domain]
        has_lark = "lark" in domain.lower()
        if has_lark or "drive" in domain.lower() or "stream" in domain.lower():
            print(f"\n  *** {domain}: {len(clist)} cookies ***")
            for c in clist:
                httponly = " [HttpOnly]" if c.get("httpOnly") else ""
                partitioned = " [Partitioned]" if c.get("partitionKey") else ""
                print(f"    {c['name']}={c['value'][:60]}...{httponly}{partitioned}")
        else:
            print(f"  {domain}: {len(clist)} cookies")

    # Get image URLs from document
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
    print(f"\nFound {len(matches)} images")

    # Build cookie string from ALL larkoffice-related cookies
    lark_cookie_str = "; ".join(
        f"{c['name']}={c['value']}"
        for c in all_cookies
        if "lark" in c.get("domain", "").lower()
    )
    print(f"\nLarkoffice cookie count: {sum(1 for c in all_cookies if 'lark' in c.get('domain', '').lower())}")

    if lark_cookie_str:
        # Try download with larkoffice cookies
        headers = {
            "Cookie": lark_cookie_str,
            "Origin": "https://bytedance.larkoffice.com",
            "Referer": "https://bytedance.larkoffice.com/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/131.0.0.0 Safari/537.36",
        }
        print(f"\n=== Testing httpx with larkoffice cookies ===")
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            for i, (alt, img_url) in enumerate(matches[:3]):
                resp = await client.get(img_url, headers=headers)
                print(f"  [{i+1}] status={resp.status_code} size={len(resp.content)}")

    # Try another approach: use CDP Network.requestIntercepted to capture auth headers
    # Let's use CDP to capture the actual request with full headers
    await cdp.send("Network.enable")

    captured_full = {}

    def on_network_event(params):
        req_url = params.get("request", {}).get("url", "")
        if "internal-api-drive-stream" in req_url:
            req = params.get("request", {})
            headers = req.get("headers", {})
            req_id = params.get("requestId", "?")
            print(f"\n  [CDP] Request {req_id}: {req_url[:100]}")
            for k, v in sorted(headers.items()):
                if k.lower() in ("cookie", "authorization", "sec-fetch-storage-access"):
                    print(f"    {k}: {v[:200]}")
            captured_full[req_id] = headers

    cdp.on("Network.requestWillBeSent", on_network_event)

    # Reload to trigger fresh requests
    print("\n=== Reloading page to capture CDP network ===")
    await page.reload(wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)

    print(f"\n=== CDP captured {len(captured_full)} image requests ===")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
