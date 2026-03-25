"""Set cookies with partitionKey via CDP to access the partitioned cookie store."""
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

    # Step 1: Load page, capture XHR cookies
    xhr_cookie_str = None

    def on_req_extra(params):
        nonlocal xhr_cookie_str
        headers = params.get("headers", {})
        cookie = headers.get("Cookie") or ""
        if "QXV0aHpDb250ZXh0" in cookie and not xhr_cookie_str:
            xhr_cookie_str = cookie

    cdp.on("Network.requestWillBeSentExtraInfo", on_req_extra)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Step 1: Loading page to capture auth cookies...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    if not xhr_cookie_str:
        print("No auth cookies captured!")
        await cdp.detach(); await browser.close(); await pw.stop(); return

    print(f"  Auth cookies: {xhr_cookie_str[:100]}...")

    # Step 2: Parse cookies and set them with partitionKey
    print("\nStep 2: Setting cookies with partitionKey...")
    cookies = []
    for pair in xhr_cookie_str.split("; "):
        eq = pair.find("=")
        if eq < 0:
            continue
        name = pair[:eq].strip()
        value = pair[eq+1:].strip()
        if name and value:
            cookies.append({"name": name, "value": value})

    # The partition key is the top-level site
    partition_key = {
        "topLevelSite": "https://yuntu.oceanengine.com",
        "hasCrossSiteAncestor": True,
    }

    for cookie in cookies:
        for domain in [".larkoffice.com", "internal-api-drive-stream.larkoffice.com"]:
            try:
                result = await cdp.send("Network.setCookie", {
                    "name": cookie["name"],
                    "value": cookie["value"],
                    "domain": domain,
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "None",
                    "partitionKey": partition_key,
                })
                print(f"  Set {cookie['name']} on {domain}: {result}")
            except Exception as e:
                # Try without hasCrossSiteAncestor
                try:
                    result = await cdp.send("Network.setCookie", {
                        "name": cookie["name"],
                        "value": cookie["value"],
                        "domain": domain,
                        "path": "/",
                        "secure": True,
                        "httpOnly": True,
                        "sameSite": "None",
                        "partitionKey": {"topLevelSite": "https://yuntu.oceanengine.com"},
                    })
                    print(f"  Set {cookie['name']} on {domain} (no ancestor): {result}")
                except Exception as e2:
                    print(f"  Error {cookie['name']} on {domain}: {e2}")

    # Step 3: Verify cookies are set in partitioned store
    all_cookies = await cdp.send("Network.getAllCookies")
    lark_cookies = [c for c in all_cookies.get("cookies", []) if "lark" in c.get("domain", "")]
    partitioned = [c for c in lark_cookies if c.get("partitionKey")]
    print(f"\n  Total larkoffice cookies: {len(lark_cookies)}")
    print(f"  Partitioned: {len(partitioned)}")
    for c in partitioned[:5]:
        print(f"    {c['name']} on {c['domain']} partition={c.get('partitionKey')}")

    # Step 4: Test image download from iframe
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
    print(f"\nStep 4: Testing download of {len(matches)} images...")

    for i, (alt, img_url) in enumerate(matches[:5]):
        token_m = re.search(r"/cover/([^/?]+)", img_url)
        token = token_m.group(1) if token_m else "?"
        result = await target_frame.evaluate("""(url) => {
            return new Promise((resolve) => {
                const xhr = new XMLHttpRequest();
                xhr.open('GET', url, true);
                xhr.responseType = 'arraybuffer';
                xhr.withCredentials = true;
                xhr.onload = () => resolve({ ok: xhr.status === 200, status: xhr.status, size: xhr.response?.byteLength || 0 });
                xhr.onerror = () => resolve({ ok: false, error: 'network' });
                xhr.send();
            });
        }""", img_url)
        print(f"  [{i+1}] {token}: {result}")

    # Also try creating new <img> tags
    print("\nStep 5: Testing <img> tags...")
    for i, (alt, img_url) in enumerate(matches[:3]):
        token_m = re.search(r"/cover/([^/?]+)", img_url)
        token = token_m.group(1) if token_m else "?"
        result = await target_frame.evaluate("""(url) => {
            return new Promise((resolve) => {
                const img = new Image();
                img.onload = () => resolve({ ok: true, w: img.naturalWidth, h: img.naturalHeight });
                img.onerror = () => resolve({ ok: false, error: 'failed' });
                img.src = url;
                setTimeout(() => resolve({ ok: false, error: 'timeout' }), 8000);
            });
        }""", img_url)
        print(f"  [{i+1}] {token}: {result}")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
