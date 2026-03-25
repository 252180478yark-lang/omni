"""Intercept the /space/api/box/file/cdn_url/ API to find alternative image download URLs."""
import asyncio, logging, re, base64, json
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

    # Capture cdn_url API requests and responses
    cdn_url_requests = {}

    def on_request(params):
        url = params.get("request", {}).get("url", "")
        if "cdn_url" in url or "box/file" in url:
            rid = params.get("requestId", "")
            body = params.get("request", {}).get("postData", "")
            cdn_url_requests[rid] = {
                "url": url[:200],
                "method": params.get("request", {}).get("method", ""),
                "body": body[:500] if body else "",
            }

    async def on_response(params):
        rid = params.get("requestId", "")
        if rid in cdn_url_requests:
            status = params.get("response", {}).get("status", 0)
            cdn_url_requests[rid]["status"] = status

    async def on_finished(params):
        rid = params.get("requestId", "")
        if rid in cdn_url_requests:
            try:
                body = await cdp.send("Network.getResponseBody", {"requestId": rid})
                resp_text = body.get("body", "")
                if body.get("base64Encoded"):
                    resp_text = base64.b64decode(resp_text).decode("utf-8", errors="replace")
                cdn_url_requests[rid]["response"] = resp_text[:2000]
            except:
                cdn_url_requests[rid]["response"] = "(could not get body)"

    cdp.on("Network.requestWillBeSent", on_request)
    cdp.on("Network.responseReceived", lambda p: asyncio.ensure_future(on_response(p)))
    cdp.on("Network.loadingFinished", lambda p: asyncio.ensure_future(on_finished(p)))

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Loading page and intercepting cdn_url API...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    print(f"\n=== cdn_url API calls: {len(cdn_url_requests)} ===")
    for rid, req in cdn_url_requests.items():
        print(f"\n  [{rid}] {req['method']} {req['url'][:100]}")
        print(f"    Status: {req.get('status', '?')}")
        if req.get("body"):
            print(f"    Request body: {req['body'][:300]}")
        if req.get("response"):
            resp = req["response"][:500]
            print(f"    Response: {resp}")

    # Also check captured cookies for the larkoffice API
    xhr_cookies = {}
    def on_extra(params):
        headers = params.get("headers", {})
        cookie = headers.get("Cookie") or ""
        if "QXV0aHpDb250ZXh0" in cookie:
            url = ""
            for rid, req in cdn_url_requests.items():
                if rid == params.get("requestId"):
                    url = req.get("url", "")
            if url:
                xhr_cookies[url[:80]] = cookie[:300]

    cdp.on("Network.requestWillBeSentExtraInfo", on_extra)

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
