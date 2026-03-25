"""Extract all cookies after Feishu iframe initializes, then use httpx to download images."""
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

    # Track successful image XHR requests to compare headers
    success_headers = {}
    async def on_request(request):
        if "internal-api-drive-stream" in request.url and request.resource_type == "xhr":
            success_headers[request.url[:80]] = dict(request.headers)

    page.on("request", on_request)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)

    # Print headers of successful XHR requests
    if success_headers:
        sample_url = list(success_headers.keys())[0]
        headers = success_headers[sample_url]
        print(f"\n=== Successful XHR request headers ===")
        for k, v in sorted(headers.items()):
            val = v[:200] if len(v) > 200 else v
            print(f"  {k}: {val}")

    # Extract ALL cookies from the browser context
    cookies = await ctx.cookies()
    print(f"\n=== Total cookies in browser: {len(cookies)} ===")

    # Group by domain
    by_domain = {}
    for c in cookies:
        d = c.get("domain", "")
        if d not in by_domain:
            by_domain[d] = []
        by_domain[d].append(c)

    for domain, clist in sorted(by_domain.items()):
        print(f"\n  {domain}: {len(clist)} cookies")
        for c in clist[:5]:
            print(f"    {c['name']}={c['value'][:50]}...")

    # Get image URLs
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!"); await browser.close(); await pw.stop(); return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No doc!"); await browser.close(); await pw.stop(); return

    matches = IMG_RE.findall(doc["markdown"])
    print(f"\nFound {len(matches)} images")

    # Build cookie string for larkoffice domain
    lark_cookies = {}
    for c in cookies:
        domain = c.get("domain", "")
        if "larkoffice" in domain or "lark" in domain:
            lark_cookies[c["name"]] = c["value"]

    print(f"\nLarkoffice cookies: {len(lark_cookies)}")
    for k, v in list(lark_cookies.items())[:10]:
        print(f"  {k}={v[:60]}")

    cookie_str = "; ".join(f"{k}={v}" for k, v in lark_cookies.items())

    # Try downloading with httpx using these cookies
    headers_to_use = {
        "Cookie": cookie_str,
        "Origin": "https://bytedance.larkoffice.com",
        "Referer": "https://bytedance.larkoffice.com/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/131.0.0.0 Safari/537.36",
    }

    # Also add headers from successful XHR if available
    if success_headers:
        sample = list(success_headers.values())[0]
        for key in ["sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"]:
            if key in sample:
                headers_to_use[key] = sample[key]

    print(f"\n=== Testing httpx download with extracted cookies ===")
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        for i, (alt, img_url) in enumerate(matches[:5]):
            resp = await client.get(img_url, headers=headers_to_use)
            if resp.status_code == 200:
                print(f"  [{i+1}] OK: {len(resp.content)} bytes, type={resp.headers.get('content-type')}")
            else:
                print(f"  [{i+1}] FAIL: {resp.status_code}")
                if i == 0:
                    print(f"    Response: {resp.text[:200]}")

    # Also try with ALL cookies (not just larkoffice)
    all_cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    headers_to_use["Cookie"] = all_cookie_str
    print(f"\n=== Testing httpx with ALL cookies ({len(cookies)} total) ===")
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        for i, (alt, img_url) in enumerate(matches[:3]):
            resp = await client.get(img_url, headers=headers_to_use)
            if resp.status_code == 200:
                print(f"  [{i+1}] OK: {len(resp.content)} bytes")
            else:
                print(f"  [{i+1}] FAIL: {resp.status_code}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
