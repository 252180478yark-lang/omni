"""Use CDP Fetch domain to intercept image requests and inject auth cookies."""
import asyncio, logging, re, json, base64
from pathlib import Path
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

    # Step 1: Navigate and wait for Feishu to init (sets cookies)
    auth_cookie_str = None
    captured_images = {}

    def on_extra_info(params):
        nonlocal auth_cookie_str
        headers = params.get("headers", {})
        cookie = headers.get("Cookie") or headers.get("cookie") or ""
        if "QXV0aHpDb250ZXh0" in cookie:
            auth_cookie_str = cookie

    def on_response_body(params):
        """Capture response bodies of image loads via CDP."""
        pass

    cdp.on("Network.requestWillBeSentExtraInfo", on_extra_info)

    # Also capture successful image responses
    async def capture_response(params):
        url = params.get("response", {}).get("url", "")
        status = params.get("response", {}).get("status", 0)
        if "internal-api-drive-stream" in url and status == 200:
            rid = params.get("requestId", "")
            try:
                body = await cdp.send("Network.getResponseBody", {"requestId": rid})
                if body.get("base64Encoded"):
                    data = base64.b64decode(body["body"])
                else:
                    data = body["body"].encode()
                token_m = re.search(r"/(cover|preview)/([^/?]+)", url)
                if token_m and len(data) > 500:
                    token = token_m.group(2)
                    if token not in captured_images or len(data) > len(captured_images[token]):
                        captured_images[token] = data
            except:
                pass

    cdp.on("Network.loadingFinished", lambda params: asyncio.ensure_future(
        _handle_loading_finished(cdp, params, captured_images)
    ))

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Step 1: Navigating and waiting for init...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    print(f"  Auth cookie captured: {auth_cookie_str is not None}")
    if auth_cookie_str:
        print(f"  Cookie: {auth_cookie_str[:100]}...")

    # Step 2: Get document
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!")
        await cdp.detach(); await browser.close(); await pw.stop(); return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No doc!")
        await cdp.detach(); await browser.close(); await pw.stop(); return

    matches = IMG_RE.findall(doc["markdown"])
    print(f"\nStep 2: Found {len(matches)} images")
    print(f"  Already captured from network: {len(captured_images)}")

    # Step 3: Use CDP Fetch to intercept and inject cookies for remaining images
    if auth_cookie_str:
        remaining = [
            (alt, url) for alt, url in matches
            if not any(token in url for token in captured_images.keys())
        ]
        print(f"\n  Remaining to fetch: {len(remaining)}")

        if remaining:
            # Enable Fetch interception for image CDN
            await cdp.send("Fetch.enable", {
                "patterns": [{
                    "urlPattern": "*internal-api-drive-stream*",
                    "requestStage": "Request"
                }]
            })

            fetch_completed = asyncio.Event()
            fetch_results = {}

            async def on_fetch_paused(params):
                request_id = params["requestId"]
                req_url = params["request"]["url"]
                headers = params["request"].get("headers", {})

                # Add auth cookies to the request
                new_headers = []
                for k, v in headers.items():
                    if k.lower() != "cookie":
                        new_headers.append({"name": k, "value": v})
                new_headers.append({"name": "Cookie", "value": auth_cookie_str})

                try:
                    await cdp.send("Fetch.continueRequest", {
                        "requestId": request_id,
                        "headers": new_headers,
                    })
                except Exception as e:
                    print(f"  Fetch.continueRequest error: {e}")

            cdp.on("Fetch.requestPaused", lambda p: asyncio.ensure_future(on_fetch_paused(p)))

            # Create img elements for remaining images
            print("\nStep 3: Creating <img> elements with CDP Fetch interception...")
            for i, (alt, img_url) in enumerate(remaining[:5]):
                token_m = re.search(r"/cover/([^/?]+)", img_url)
                token = token_m.group(1) if token_m else f"img_{i}"

                result = await target_frame.evaluate(f"""() => {{
                    return new Promise((resolve) => {{
                        const img = new Image();
                        img.crossOrigin = 'anonymous';
                        img.onload = () => {{
                            // Draw to canvas to extract data
                            const canvas = document.createElement('canvas');
                            canvas.width = img.naturalWidth;
                            canvas.height = img.naturalHeight;
                            const ctx = canvas.getContext('2d');
                            ctx.drawImage(img, 0, 0);
                            const dataUrl = canvas.toDataURL('image/png');
                            resolve({{ ok: true, width: img.naturalWidth, height: img.naturalHeight, size: dataUrl.length }});
                        }};
                        img.onerror = (e) => resolve({{ ok: false, error: 'load failed' }});
                        img.src = '{img_url}';
                        setTimeout(() => resolve({{ ok: false, error: 'timeout' }}), 10000);
                    }});
                }}""")
                print(f"  [{i+1}] {token}: {result}")

            await cdp.send("Fetch.disable")

    # Final count
    await page.wait_for_timeout(3000)
    print(f"\n=== Total captured: {len(captured_images)} images ===")
    total = sum(len(v) for v in captured_images.values())
    print(f"  Total size: {total // 1024} KB")

    await cdp.detach()
    await browser.close()
    await pw.stop()


async def _handle_loading_finished(cdp, params, captured_images):
    """Handle loadingFinished events to extract image bodies."""
    rid = params.get("requestId", "")
    try:
        body = await cdp.send("Network.getResponseBody", {"requestId": rid})
        if body.get("base64Encoded"):
            data = base64.b64decode(body["body"])
        else:
            data = body["body"].encode()

        # We need the URL, get it from the request mapping
        if len(data) > 500:
            captured_images[f"__rid_{rid}"] = data
    except:
        pass


asyncio.run(test())
