"""Extract mount_node_token from CDN requests and use it to download all images."""
import asyncio, logging, re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS
import httpx

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    page = await ctx.new_page()

    cdn_full_urls = []

    async def on_request(request):
        if "internal-api-drive-stream" in request.url:
            cdn_full_urls.append(request.url)

    page.on("request", on_request)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(8000)

    print(f"Captured {len(cdn_full_urls)} CDN request URLs")
    if cdn_full_urls:
        first = cdn_full_urls[0]
        parsed = urlparse(first)
        qs = parse_qs(parsed.query)
        print(f"\nFull URL: {first}")
        print(f"\nQuery params:")
        for k, v in qs.items():
            print(f"  {k}: {v[0][:80]}")

        mount_node_token = qs.get("mount_node_token", [None])[0]
        print(f"\nmount_node_token: {mount_node_token}")

        if mount_node_token:
            # Extract document content
            target_frame = None
            for frame in page.frames:
                if "larkoffice" in frame.url:
                    target_frame = frame
                    break

            raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
            doc = parse_feishu_document(raw)
            matches = IMG_RE.findall(doc["markdown"])
            print(f"\nTotal image tokens in doc: {len(matches)}")

            # Try downloading images with mount_node_token
            img_dir = Path("/tmp/test_images")
            img_dir.mkdir(exist_ok=True)
            success = 0
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Origin": "https://bytedance.larkoffice.com",
                "Referer": "https://bytedance.larkoffice.com/",
            }
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
                for i, (alt, cdn_url) in enumerate(matches[:5]):
                    # Rebuild URL with mount_node_token
                    p = urlparse(cdn_url)
                    orig_qs = parse_qs(p.query)
                    orig_qs["mount_node_token"] = [mount_node_token]
                    new_url = f"{p.scheme}://{p.netloc}{p.path}?{urlencode({k: v[0] for k, v in orig_qs.items()})}"

                    resp = await client.get(new_url)
                    ct = resp.headers.get("content-type", "?")
                    print(f"  [{i}] {resp.status_code} {ct} ({len(resp.content)} bytes) token={re.search(r'/cover/([^/?]+)', cdn_url).group(1)}")
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        success += 1

            print(f"\nSuccess: {success}/5")

    await browser.close()
    await pw.stop()

asyncio.run(test())
