"""Use XMLHttpRequest from iframe context to download images - matching Feishu's own approach."""
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

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Navigating...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

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
    print(f"Found {len(matches)} images in document\n")

    # Test XHR download for first 5 images
    for i, (alt, img_url) in enumerate(matches[:5]):
        print(f"[{i+1}] {alt or 'image'}")
        result = await target_frame.evaluate("""(url) => {
            return new Promise((resolve) => {
                const xhr = new XMLHttpRequest();
                xhr.open('GET', url, true);
                xhr.responseType = 'arraybuffer';
                xhr.withCredentials = true;
                xhr.onload = () => {
                    if (xhr.status === 200) {
                        const bytes = new Uint8Array(xhr.response);
                        // Convert to base64 in chunks to avoid stack overflow
                        let binary = '';
                        const chunkSize = 8192;
                        for (let i = 0; i < bytes.length; i += chunkSize) {
                            const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length));
                            binary += String.fromCharCode.apply(null, chunk);
                        }
                        resolve({
                            ok: true,
                            status: 200,
                            size: bytes.length,
                            b64: btoa(binary),
                            contentType: xhr.getResponseHeader('content-type'),
                        });
                    } else {
                        resolve({ ok: false, status: xhr.status });
                    }
                };
                xhr.onerror = () => resolve({ ok: false, error: 'network error' });
                xhr.send();
            });
        }""", img_url)

        if result.get("ok"):
            print(f"    SUCCESS: {result['size']} bytes, type={result['contentType']}")
            # Save to disk
            data = base64.b64decode(result["b64"])
            out_dir = Path("/tmp/test_xhr_images")
            out_dir.mkdir(exist_ok=True)
            ext = ".jpg" if "jpeg" in (result.get("contentType") or "") else ".png"
            out_path = out_dir / f"img_{i}{ext}"
            out_path.write_bytes(data)
            print(f"    Saved: {out_path} ({len(data)} bytes)")
        else:
            print(f"    FAILED: status={result.get('status')} error={result.get('error')}")

    # Now test ALL images
    print(f"\n=== Batch download all {len(matches)} images via XHR ===")
    success = 0
    failed = 0
    total_bytes = 0

    for i, (alt, img_url) in enumerate(matches):
        result = await target_frame.evaluate("""(url) => {
            return new Promise((resolve) => {
                const xhr = new XMLHttpRequest();
                xhr.open('GET', url, true);
                xhr.responseType = 'arraybuffer';
                xhr.withCredentials = true;
                xhr.onload = () => {
                    resolve({ ok: xhr.status === 200, status: xhr.status, size: xhr.response?.byteLength || 0 });
                };
                xhr.onerror = () => resolve({ ok: false, error: 'network error' });
                xhr.send();
            });
        }""", img_url)

        if result.get("ok"):
            success += 1
            total_bytes += result.get("size", 0)
            print(f"  [{i+1}/{len(matches)}] OK {result['size']} bytes")
        else:
            failed += 1
            print(f"  [{i+1}/{len(matches)}] FAIL status={result.get('status')}")

    print(f"\n=== Results: {success}/{len(matches)} succeeded, {total_bytes // 1024} KB total ===")

    await browser.close()
    await pw.stop()

asyncio.run(test())
