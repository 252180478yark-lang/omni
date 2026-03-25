"""Download encrypted images from feishucdn.com and decrypt them using AES-GCM."""
import asyncio, logging, re, base64, json
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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

    # Capture cdn_url API responses
    cdn_url_data = {}
    request_urls = {}
    request_bodies = {}

    def on_request(params):
        url = params.get("request", {}).get("url", "")
        rid = params.get("requestId", "")
        if "cdn_url" in url:
            request_urls[rid] = url
            body = params.get("request", {}).get("postData", "")
            request_bodies[rid] = body

    async def on_finished(params):
        rid = params.get("requestId", "")
        if rid not in request_urls:
            return
        try:
            body_result = await cdp.send("Network.getResponseBody", {"requestId": rid})
            text = body_result.get("body", "")
            if body_result.get("base64Encoded"):
                text = base64.b64decode(text).decode()
            data = json.loads(text)
            if data.get("data"):
                for item in data["data"]:
                    token = item.get("file_token", "")
                    if token:
                        cdn_url_data[token] = {
                            "url": item.get("url", ""),
                            "secret": item.get("secret", ""),
                            "nonce": item.get("nonce", ""),
                            "cipher_type": item.get("cipher_type", ""),
                        }
        except:
            pass

    cdp.on("Network.requestWillBeSent", on_request)
    cdp.on("Network.loadingFinished", lambda p: asyncio.ensure_future(on_finished(p)))

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Step 1: Loading page to capture CDN URLs...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    print(f"  CDN URL data captured for {len(cdn_url_data)} tokens")

    # Get document image tokens
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!"); await cdp.detach(); await browser.close(); await pw.stop(); return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No doc!"); await cdp.detach(); await browser.close(); await pw.stop(); return

    matches = IMG_RE.findall(doc["markdown"])
    tokens_needed = {}
    for alt, img_url in matches:
        token_m = re.search(r"/cover/([^/?]+)", img_url)
        if token_m:
            tokens_needed[token_m.group(1)] = img_url

    print(f"  Tokens in doc: {len(tokens_needed)}")
    have_cdn = set(cdn_url_data.keys()) & set(tokens_needed.keys())
    print(f"  Have CDN URL: {len(have_cdn)}")
    missing = set(tokens_needed.keys()) - set(cdn_url_data.keys())
    print(f"  Missing CDN URL: {len(missing)}")
    if missing:
        print(f"  Missing tokens: {list(missing)[:5]}")

    # Step 2: Download and decrypt images
    print(f"\n=== Step 2: Download and decrypt {len(have_cdn)} images ===")

    out_dir = Path("/tmp/test_decrypted_images")
    out_dir.mkdir(exist_ok=True)
    success = 0
    total_bytes = 0

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for token in sorted(have_cdn):
            info = cdn_url_data[token]
            cdn_url = info["url"]
            secret_b64 = info["secret"]
            nonce_b64 = info["nonce"]

            print(f"\n  [{token}]")
            print(f"    CDN URL: {cdn_url}")
            print(f"    Secret: {secret_b64}")
            print(f"    Nonce: {nonce_b64}")

            # Download encrypted data (should be public - no auth needed)
            resp = await client.get(cdn_url)
            print(f"    Download: {resp.status_code} ({len(resp.content)} bytes)")

            if resp.status_code != 200:
                print(f"    FAILED to download!")
                continue

            encrypted_data = resp.content

            # Decrypt using AES-GCM
            try:
                key = base64.b64decode(secret_b64)
                nonce = base64.b64decode(nonce_b64)

                print(f"    Key size: {len(key)} bytes, Nonce size: {len(nonce)} bytes")

                aesgcm = AESGCM(key)
                decrypted = aesgcm.decrypt(nonce, encrypted_data, None)

                # Check if it's a valid image
                magic = decrypted[:4]
                if magic[:3] == b'\xff\xd8\xff':
                    ext = ".jpg"
                elif magic[:4] == b'\x89PNG':
                    ext = ".png"
                elif magic[:4] == b'GIF8':
                    ext = ".gif"
                elif magic[:4] == b'RIFF':
                    ext = ".webp"
                else:
                    ext = ".bin"
                    print(f"    Unknown magic: {magic.hex()}")

                out_path = out_dir / f"{token}{ext}"
                out_path.write_bytes(decrypted)
                print(f"    Decrypted: {len(decrypted)} bytes → {out_path.name} ({ext})")
                success += 1
                total_bytes += len(decrypted)

            except Exception as e:
                print(f"    Decryption error: {e}")

    print(f"\n=== RESULT: {success}/{len(have_cdn)} decrypted, {total_bytes // 1024} KB total ===")

    # For missing tokens, try calling the API ourselves
    if missing:
        print(f"\n=== Calling cdn_url API for {len(missing)} missing tokens ===")
        missing_list = list(missing)
        # We need to call this from the iframe context
        batch_size = 10
        for i in range(0, len(missing_list), batch_size):
            batch = missing_list[i:i+batch_size]
            payload = [{"file_token": t, "width": 1280, "height": 1280, "policy": "near"} for t in batch]

            result = await target_frame.evaluate(f"""async () => {{
                try {{
                    const resp = await fetch('https://bytedance.larkoffice.com/space/api/box/file/cdn_url/', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        credentials: 'include',
                        body: JSON.stringify({json.dumps(payload)}),
                    }});
                    return await resp.json();
                }} catch(e) {{
                    return {{ error: e.message }};
                }}
            }}""")
            print(f"  Batch {i//batch_size + 1}: {json.dumps(result)[:300]}")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
