"""Capture detailed request/response headers for image loads to understand auth mechanism."""
import asyncio, logging, re, json
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    page = await ctx.new_page()

    # Capture BOTH request and response details for image CDN
    async def on_request(request):
        if "internal-api-drive-stream" not in request.url:
            return
        headers = request.headers
        print(f"\n>>> REQUEST: {request.url[:120]}")
        print(f"    Method: {request.method}")
        print(f"    Resource type: {request.resource_type}")
        for k, v in sorted(headers.items()):
            if k.startswith("sec-") or k in ("cookie", "authorization", "origin", "referer"):
                print(f"    {k}: {v[:120] if len(v) > 120 else v}")

    async def on_response(response):
        if "internal-api-drive-stream" not in response.url:
            return
        print(f"\n<<< RESPONSE: {response.status} {response.url[:120]}")
        headers = response.headers
        for k, v in sorted(headers.items()):
            if k in ("content-type", "content-length", "set-cookie", "x-tt-logid", "access-control-allow-origin"):
                print(f"    {k}: {v[:120] if len(v) > 120 else v}")

    page.on("request", on_request)
    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)

    # Now try to replicate the same request headers from JS
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if target_frame:
        print("\n\n=== Checking iframe cookies and Storage Access ===")
        cookie_info = await target_frame.evaluate("""() => {
            return {
                cookies: document.cookie.substring(0, 500),
                origin: location.origin,
                hasStorageAccess: typeof document.hasStorageAccess === 'function',
            };
        }""")
        print(f"  Origin: {cookie_info['origin']}")
        print(f"  Has StorageAccess API: {cookie_info['hasStorageAccess']}")
        print(f"  Cookies (first 500): {cookie_info['cookies'][:200]}")

        if cookie_info['hasStorageAccess']:
            has_access = await target_frame.evaluate("document.hasStorageAccess()")
            print(f"  hasStorageAccess(): {has_access}")

            # Try requesting storage access
            try:
                req_result = await target_frame.evaluate("""async () => {
                    try {
                        await document.requestStorageAccess();
                        return { granted: true };
                    } catch(e) {
                        return { granted: false, error: e.message };
                    }
                }""")
                print(f"  requestStorageAccess(): {req_result}")

                # Re-check
                has_access2 = await target_frame.evaluate("document.hasStorageAccess()")
                print(f"  hasStorageAccess() after request: {has_access2}")
            except Exception as e:
                print(f"  requestStorageAccess error: {e}")

        # Try fetch with explicit Storage Access header
        print("\n=== Trying fetch with Storage Access header ===")
        from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS
        raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
        doc = parse_feishu_document(raw)
        if doc:
            img_re = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")
            matches = img_re.findall(doc["markdown"])
            if matches:
                test_url = matches[0][1]
                result = await target_frame.evaluate("""async (url) => {
                    try {
                        // Try with various fetch options
                        const tests = [
                            { mode: 'cors', credentials: 'include' },
                            { mode: 'no-cors', credentials: 'include' },
                            { mode: 'cors', credentials: 'same-origin' },
                        ];
                        const results = [];
                        for (const opts of tests) {
                            try {
                                const r = await fetch(url, opts);
                                results.push({ opts, status: r.status, ok: r.ok, type: r.type });
                            } catch (e) {
                                results.push({ opts, error: e.message });
                            }
                        }
                        return results;
                    } catch (e) {
                        return { error: e.message };
                    }
                }""", test_url)
                print(f"  Fetch attempts: {json.dumps(result, indent=2)}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
