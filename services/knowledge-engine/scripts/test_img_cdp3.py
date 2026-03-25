"""Use CDP requestWillBeSentExtraInfo to see actual cookies sent with image requests."""
import asyncio, logging, re, json
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    page = await ctx.new_page()

    cdp = await ctx.new_cdp_session(page)
    await cdp.send("Network.enable")

    request_details = {}
    extra_info = {}
    response_info = {}

    def on_request(params):
        url = params.get("request", {}).get("url", "")
        if "internal-api-drive-stream" in url:
            rid = params.get("requestId", "")
            rtype = params.get("type", "")
            request_details[rid] = {"url": url[:100], "type": rtype}

    def on_extra_info(params):
        rid = params.get("requestId", "")
        if rid in request_details or True:
            headers = params.get("headers", {})
            cookies_from_browser = params.get("associatedCookies", [])
            extra_info[rid] = {
                "headers": {k: v[:200] for k, v in headers.items()},
                "cookie_count": len(cookies_from_browser),
                "cookies_blocked": [c for c in cookies_from_browser if c.get("blockedReasons")],
                "cookies_sent": [c for c in cookies_from_browser if not c.get("blockedReasons")],
            }

    def on_response(params):
        url = params.get("response", {}).get("url", "")
        if "internal-api-drive-stream" in url:
            rid = params.get("requestId", "")
            status = params.get("response", {}).get("status", 0)
            response_info[rid] = {"status": status, "url": url[:100]}

    cdp.on("Network.requestWillBeSent", on_request)
    cdp.on("Network.requestWillBeSentExtraInfo", on_extra_info)
    cdp.on("Network.responseReceived", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    # Match up requests with their extra info and responses
    print(f"\n=== Matched request details ===")
    for rid, req in request_details.items():
        ei = extra_info.get(rid, {})
        resp = response_info.get(rid, {})
        status = resp.get("status", "?")

        print(f"\n[{rid}] {req['type']} → {status}")
        print(f"  URL: {req['url']}")

        if ei:
            cookie_count = ei.get("cookie_count", 0)
            sent = ei.get("cookies_sent", [])
            blocked = ei.get("cookies_blocked", [])
            print(f"  Cookies: {len(sent)} sent, {len(blocked)} blocked")

            if sent:
                for c in sent[:3]:
                    cookie = c.get("cookie", {})
                    print(f"    SENT: {cookie.get('name')}={cookie.get('value', '')[:40]}... "
                          f"domain={cookie.get('domain')} httpOnly={cookie.get('httpOnly')}")
            if blocked:
                for c in blocked[:3]:
                    cookie = c.get("cookie", {})
                    reasons = c.get("blockedReasons", [])
                    print(f"    BLOCKED ({reasons}): {cookie.get('name')}={cookie.get('value', '')[:40]}... "
                          f"domain={cookie.get('domain')}")

            # Check for special headers
            headers = ei.get("headers", {})
            for k in ["cookie", "Cookie", "sec-fetch-storage-access", "Sec-Fetch-Storage-Access",
                       "sec-fetch-dest", "Sec-Fetch-Dest", "sec-fetch-mode", "Sec-Fetch-Mode"]:
                if k in headers:
                    val = headers[k]
                    if k.lower() == "cookie":
                        val = val[:200] + "..." if len(val) > 200 else val
                    print(f"    Header {k}: {val}")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
