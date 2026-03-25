"""Inject <img> elements and extract via canvas in iframe."""
import asyncio, logging, re, json
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

    # Capture mount_node_token from CDN requests
    mount_token = None
    async def on_req(request):
        nonlocal mount_token
        if "internal-api-drive-stream" in request.url and not mount_token:
            m = re.search(r"mount_node_token=([^&]+)", request.url)
            if m:
                mount_token = m.group(1)

    page.on("request", on_req)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(8000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!")
        await browser.close(); await pw.stop()
        return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    matches = IMG_RE.findall(doc["markdown"])
    print(f"mount_node_token: {mount_token}")
    print(f"Total image tokens: {len(matches)}")

    # Try downloading images by injecting <img> and reading via canvas
    tokens = []
    for alt, cdn_url in matches:
        m = re.search(r"/cover/([^/?]+)/", cdn_url)
        if m:
            tokens.append(m.group(1))

    # Test with first 5 tokens
    for token in tokens[:5]:
        cdn_url = (
            f"https://internal-api-drive-stream.larkoffice.com/space/api/box/stream/"
            f"download/v2/cover/{token}/?fallback_source=1&height=1280"
            f"&mount_point=docx_image&policy=equal&width=1280"
        )
        if mount_token:
            cdn_url += f"&mount_node_token={mount_token}"

        result = await target_frame.evaluate("""async (url) => {
            return new Promise((resolve) => {
                const img = new Image();
                img.crossOrigin = 'use-credentials';
                img.onload = () => {
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = img.naturalWidth;
                        canvas.height = img.naturalHeight;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0);
                        const dataUrl = canvas.toDataURL('image/png');
                        resolve({
                            success: true,
                            width: img.naturalWidth,
                            height: img.naturalHeight,
                            dataUrlLength: dataUrl.length,
                        });
                    } catch(e) {
                        resolve({success: false, error: 'canvas: ' + e.message});
                    }
                };
                img.onerror = (e) => {
                    // Try without crossOrigin
                    const img2 = new Image();
                    img2.onload = () => {
                        resolve({
                            success: false,
                            error: 'loaded_no_cors',
                            width: img2.naturalWidth,
                            height: img2.naturalHeight,
                        });
                    };
                    img2.onerror = () => {
                        resolve({success: false, error: 'failed_completely'});
                    };
                    img2.src = url;
                };
                img.src = url;
                setTimeout(() => resolve({success: false, error: 'timeout'}), 10000);
            });
        }""", cdn_url)

        print(f"  {token}: {result}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
