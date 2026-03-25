"""Try to find an alternative API endpoint for downloading images from Feishu docs.
Check if the yuntu page has any internal API that returns article content with images."""
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

    # Capture ALL API requests made by the page
    api_requests = []

    def on_request(params):
        url = params.get("request", {}).get("url", "")
        method = params.get("request", {}).get("method", "")
        rtype = params.get("type", "")
        if any(kw in url for kw in ["api", "yuntu", "knowledge", "content", "article", "doc"]):
            if "static" not in url and "js" not in url and "css" not in url:
                api_requests.append({
                    "url": url[:200],
                    "method": method,
                    "type": rtype,
                })

    cdp.on("Network.requestWillBeSent", on_request)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Loading page and monitoring API calls...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)

    print(f"\n=== API requests ({len(api_requests)}) ===")
    for r in api_requests:
        if "drive-stream" not in r["url"] and "feishu" not in r["url"]:
            print(f"  {r['method']} {r['url'][:120]}")

    # Check for yuntu's own content API
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    # Get the feishu doc token
    if target_frame:
        doc_info = await target_frame.evaluate("""() => {
            const data = window.DATA?.clientVars;
            if (!data) return null;
            return {
                docToken: data.objToken || data.token,
                objType: data.objType,
                hasBlocks: !!data.blocks,
                blockCount: data.blocks?.length || 0,
            };
        }""")
        print(f"\nDoc info: {doc_info}")

    # Try yuntu's own render API - maybe it has a different endpoint for content
    print("\n=== Testing yuntu content APIs ===")

    # Try the SSR API that we use for navigation
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        headers = {}
        # Get cookies from the page
        cookies = await ctx.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        headers["Cookie"] = cookie_str
        headers["User-Agent"] = "Mozilla/5.0"

        # Try getting the article content via yuntu API
        content_apis = [
            f"https://yuntu.oceanengine.com/api/v2/knowledge/content?pageId=143250&graphId=610&spaceId=221",
            f"https://yuntu.oceanengine.com/api/v1/knowledge/content?pageId=143250",
            f"https://yuntu.oceanengine.com/api/v2/knowledge/article/detail?pageId=143250&graphId=610",
            f"https://yuntu.oceanengine.com/support/api/content/143250",
        ]

        for api_url in content_apis:
            try:
                resp = await client.get(api_url, headers=headers)
                print(f"\n  {api_url[:80]}...")
                print(f"    Status: {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.text[:500]
                    print(f"    Response: {data}")
            except Exception as e:
                print(f"    Error: {e}")

    # Look for image-related URLs in API responses
    print("\n=== Checking Feishu doc clientVars for alternative image URLs ===")
    if target_frame:
        alt_urls = await target_frame.evaluate("""() => {
            const data = window.DATA?.clientVars;
            if (!data) return null;
            
            // Search for image-related data in the document structure
            const str = JSON.stringify(data);
            
            // Find all URLs
            const urlMatches = str.match(/https?:[^"']+/g) || [];
            const imageUrls = urlMatches.filter(u => 
                u.includes('image') || u.includes('cover') || u.includes('download') ||
                u.includes('img') || u.includes('.png') || u.includes('.jpg')
            );
            
            // Find all image tokens
            const tokenRE = /[A-Za-z0-9]{20,}/g;
            const tokens = str.match(tokenRE) || [];
            const imageTokens = new Set();
            for (const t of tokens) {
                if (t.length >= 20 && t.length <= 30) {
                    imageTokens.add(t);
                }
            }
            
            return {
                imageUrls: [...new Set(imageUrls)].slice(0, 10),
                sampleTokens: [...imageTokens].slice(0, 10),
                dataKeys: Object.keys(data).slice(0, 20),
            };
        }""")
        print(f"  Data keys: {alt_urls.get('dataKeys', [])}")
        print(f"  Image URLs: {alt_urls.get('imageUrls', [])[:5]}")
        print(f"  Tokens: {alt_urls.get('sampleTokens', [])[:5]}")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
