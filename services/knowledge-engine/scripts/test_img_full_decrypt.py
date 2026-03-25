"""Full pipeline: capture ALL cdn_url API responses, download and decrypt ALL images."""
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

    # Use page.on("response") to capture cdn_url API responses
    cdn_url_data = {}

    async def on_api_response(response):
        if "cdn_url" not in response.url:
            return
        if response.status != 200:
            return
        try:
            body = await response.json()
            if body.get("data"):
                for item in body["data"]:
                    token = item.get("file_token", "")
                    if token and item.get("url"):
                        cdn_url_data[token] = {
                            "url": item["url"],
                            "secret": item.get("secret", ""),
                            "nonce": item.get("nonce", ""),
                            "cipher_type": item.get("cipher_type", ""),
                        }
        except:
            pass

    page.on("response", on_api_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Step 1: Loading page...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(15000)

    print(f"  CDN URL data: {len(cdn_url_data)} tokens")

    # Get document image tokens
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!"); await browser.close(); await pw.stop(); return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No doc!"); await browser.close(); await pw.stop(); return

    matches = IMG_RE.findall(doc["markdown"])
    tokens_needed = {}
    for alt, img_url in matches:
        token_m = re.search(r"/cover/([^/?]+)", img_url)
        if token_m:
            tokens_needed[token_m.group(1)] = img_url

    have_cdn = set(cdn_url_data.keys()) & set(tokens_needed.keys())
    missing = set(tokens_needed.keys()) - set(cdn_url_data.keys())
    print(f"  Doc images: {len(tokens_needed)}")
    print(f"  Have CDN URL: {len(have_cdn)}")
    print(f"  Missing: {len(missing)}")

    # List all captured tokens vs needed
    for t in sorted(cdn_url_data.keys()):
        in_doc = "IN DOC" if t in tokens_needed else "not in doc"
        print(f"    {t}: {in_doc}")

    # Step 2: Download and decrypt ALL available images
    print(f"\n=== Downloading and decrypting {len(have_cdn)} images ===")
    out_dir = Path("/tmp/test_all_images")
    out_dir.mkdir(exist_ok=True)
    success = 0

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for token in sorted(have_cdn):
            info = cdn_url_data[token]
            try:
                resp = await client.get(info["url"])
                if resp.status_code != 200:
                    print(f"  {token}: download failed ({resp.status_code})")
                    continue

                key = base64.b64decode(info["secret"])
                nonce = base64.b64decode(info["nonce"])
                aesgcm = AESGCM(key)
                decrypted = aesgcm.decrypt(nonce, resp.content, None)

                magic = decrypted[:4]
                ext = ".jpg" if magic[:3] == b'\xff\xd8\xff' else \
                      ".png" if magic[:4] == b'\x89PNG' else \
                      ".gif" if magic[:4] == b'GIF8' else \
                      ".webp" if magic[:4] == b'RIFF' else ".bin"

                out_path = out_dir / f"{token}{ext}"
                out_path.write_bytes(decrypted)
                print(f"  {token}: {len(decrypted):>8} bytes {ext}")
                success += 1
            except Exception as e:
                print(f"  {token}: error - {e}")

    print(f"\n=== RESULT: {success}/{len(have_cdn)} decrypted ===")
    print(f"=== Total from doc: {success}/{len(tokens_needed)} ===")

    # For missing tokens, try to trigger the Feishu editor to call cdn_url for them
    if missing:
        print(f"\n=== Trying to get CDN URLs for {len(missing)} missing tokens ===")
        # The editor already called cdn_url for some tokens. The missing ones might
        # not have been requested yet. Let's try calling the cdn_url API from
        # the Feishu editor's own code by triggering image block rendering.

        # Try to call the API using the iframe's XHR (which has auth)
        missing_list = list(missing)
        batch = [{"file_token": t, "width": 1280, "height": 1280, "policy": "near"} for t in missing_list]

        # Use XHR instead of fetch to match the Feishu editor's behavior
        result = await target_frame.evaluate("""(payload) => {
            return new Promise((resolve) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', '/space/api/box/file/cdn_url/', true);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.withCredentials = true;
                xhr.onload = function() {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch(e) {
                        resolve({ error: xhr.responseText?.substring(0, 200) });
                    }
                };
                xhr.onerror = () => resolve({ error: 'network error' });
                xhr.send(JSON.stringify(payload));
            });
        }""", batch)

        print(f"  API response: code={result.get('code')} msg={result.get('msg', result.get('message', ''))}")

        if result.get("data"):
            new_count = 0
            for item in result["data"]:
                token = item.get("file_token", "")
                if token and item.get("url"):
                    cdn_url_data[token] = {
                        "url": item["url"],
                        "secret": item.get("secret", ""),
                        "nonce": item.get("nonce", ""),
                    }
                    new_count += 1
            print(f"  Got {new_count} new CDN URLs!")

            # Download and decrypt the new ones
            new_have = set(cdn_url_data.keys()) & set(tokens_needed.keys()) - have_cdn
            if new_have:
                print(f"\n  Downloading {len(new_have)} additional images...")
                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    for token in sorted(new_have):
                        info = cdn_url_data[token]
                        try:
                            resp = await client.get(info["url"])
                            if resp.status_code != 200:
                                continue
                            key = base64.b64decode(info["secret"])
                            nonce = base64.b64decode(info["nonce"])
                            aesgcm = AESGCM(key)
                            decrypted = aesgcm.decrypt(nonce, resp.content, None)
                            magic = decrypted[:4]
                            ext = ".jpg" if magic[:3] == b'\xff\xd8\xff' else \
                                  ".png" if magic[:4] == b'\x89PNG' else ".bin"
                            out_path = out_dir / f"{token}{ext}"
                            out_path.write_bytes(decrypted)
                            print(f"    {token}: {len(decrypted):>8} bytes")
                            success += 1
                        except Exception as e:
                            print(f"    {token}: error - {e}")

    total_imgs = len(list(out_dir.glob("*")))
    total_size = sum(f.stat().st_size for f in out_dir.glob("*"))
    print(f"\n=== FINAL: {total_imgs} images, {total_size // 1024} KB total ===")

    await browser.close()
    await pw.stop()

asyncio.run(test())
