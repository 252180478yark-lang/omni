"""Use CDP Network.loadNetworkResource to download images in iframe context."""
import asyncio, logging, re, base64
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

    # Get frame ID for CDP
    frame_element = await page.query_selector('iframe[src*="larkoffice"]')

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    matches = IMG_RE.findall(doc["markdown"])

    tokens = []
    for _, u in matches:
        m = re.search(r"/cover/([^/?]+)/", u)
        if m:
            tokens.append(m.group(1))

    print(f"mount_node_token: {mount_token}")
    print(f"Image tokens: {len(tokens)}")

    # Create CDP session
    cdp = await ctx.new_cdp_session(page)

    # Get all frames to find the iframe's frame ID
    tree = await cdp.send("Page.getFrameTree")
    def find_frame(frame_tree, depth=0):
        f = frame_tree.get("frame", {})
        url = f.get("url", "")
        fid = f.get("id", "")
        results = []
        if "larkoffice" in url:
            results.append({"id": fid, "url": url[:100]})
        for child in frame_tree.get("childFrames", []):
            results.extend(find_frame(child, depth + 1))
        return results

    feishu_frames = find_frame(tree["frameTree"])
    print(f"\nFeishu frames: {feishu_frames}")

    if not feishu_frames:
        print("No feishu frame found via CDP!")
        await browser.close(); await pw.stop()
        return

    frame_id = feishu_frames[0]["id"]

    # Try Network.loadNetworkResource for first 3 tokens
    success = 0
    for token in tokens[:3]:
        cdn_url = (
            f"https://internal-api-drive-stream.larkoffice.com/space/api/box/stream/"
            f"download/v2/cover/{token}/?fallback_source=1&height=1280"
            f"&mount_point=docx_image&policy=equal&width=1280"
        )
        if mount_token:
            cdn_url += f"&mount_node_token={mount_token}"

        try:
            result = await cdp.send("Network.loadNetworkResource", {
                "url": cdn_url,
                "frameId": frame_id,
                "options": {
                    "disableCache": False,
                    "includeCredentials": True,
                },
            })
            resource = result.get("resource", {})
            print(f"\n  Token: {token}")
            print(f"  Success: {resource.get('success')}")
            print(f"  Status: {resource.get('httpStatusCode')}")
            print(f"  NetError: {resource.get('netError')}")

            if resource.get("success"):
                stream = resource.get("stream")
                if stream:
                    # Read the stream
                    data_parts = []
                    while True:
                        chunk = await cdp.send("IO.read", {"handle": stream, "size": 1024 * 1024})
                        data_parts.append(chunk.get("data", ""))
                        if chunk.get("eof"):
                            break
                    await cdp.send("IO.close", {"handle": stream})
                    full_data = "".join(data_parts)
                    if chunk.get("base64Encoded", False) or resource.get("httpStatusCode") == 200:
                        try:
                            img_bytes = base64.b64decode(full_data)
                        except:
                            img_bytes = full_data.encode()
                    else:
                        img_bytes = full_data.encode()
                    print(f"  Data size: {len(img_bytes)} bytes")
                    if len(img_bytes) > 1000:
                        success += 1
                        Path(f"/tmp/{token}.png").write_bytes(img_bytes)
                        print(f"  Saved!")
        except Exception as e:
            print(f"  CDP error for {token}: {e}")

    print(f"\nSuccess: {success}/3")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
