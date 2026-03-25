"""Hijack Feishu's own XHR to piggyback on its auth for downloading ALL images."""
import asyncio, logging, re, base64, json
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

# This script is injected into ALL frames before any page JS runs.
# It monkeypatches XMLHttpRequest to capture the auth cookies from 
# Feishu's own image XHR requests, then uses them to download ALL images.
XHR_HIJACK_JS = """
(() => {
    window.__omni_img_results = {};
    window.__omni_img_queue = [];
    window.__omni_auth_captured = false;
    
    const OrigXHR = window.XMLHttpRequest;
    const origOpen = OrigXHR.prototype.open;
    const origSend = OrigXHR.prototype.send;
    
    OrigXHR.prototype.open = function(method, url, ...args) {
        this.__omni_url = url;
        this.__omni_method = method;
        return origOpen.call(this, method, url, ...args);
    };
    
    OrigXHR.prototype.send = function(body) {
        if (this.__omni_url && 
            this.__omni_url.includes('internal-api-drive-stream') &&
            this.__omni_url.includes('/cover/')) {
            
            const origOnload = this.onload;
            const origOnreadystatechange = this.onreadystatechange;
            
            this.addEventListener('load', function() {
                if (this.status === 200 && !window.__omni_auth_captured) {
                    window.__omni_auth_captured = true;
                    console.log('[OMNI] Auth XHR succeeded! Starting queue download...');
                    
                    // Download all queued images using the same auth context
                    setTimeout(() => {
                        const queue = window.__omni_img_queue;
                        console.log('[OMNI] Queue has ' + queue.length + ' items');
                        
                        let completed = 0;
                        for (const item of queue) {
                            const xhr = new OrigXHR();
                            xhr.open('GET', item.url, true);
                            xhr.responseType = 'arraybuffer';
                            xhr.withCredentials = true;
                            xhr.onload = function() {
                                completed++;
                                if (this.status === 200 && this.response) {
                                    const bytes = new Uint8Array(this.response);
                                    let binary = '';
                                    const chunkSize = 8192;
                                    for (let i = 0; i < bytes.length; i += chunkSize) {
                                        const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length));
                                        binary += String.fromCharCode.apply(null, chunk);
                                    }
                                    window.__omni_img_results[item.token] = {
                                        ok: true,
                                        size: bytes.length,
                                        b64: btoa(binary),
                                    };
                                    console.log('[OMNI] Downloaded: ' + item.token + ' (' + bytes.length + ' bytes) [' + completed + '/' + queue.length + ']');
                                } else {
                                    window.__omni_img_results[item.token] = { ok: false, status: this.status };
                                    console.log('[OMNI] Failed: ' + item.token + ' status=' + this.status);
                                }
                            };
                            xhr.onerror = function() {
                                completed++;
                                window.__omni_img_results[item.token] = { ok: false, error: 'network' };
                            };
                            xhr.send();
                        }
                    }, 1000);
                }
            });
        }
        return origSend.call(this, body);
    };
})();
"""

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")

    # Inject the XHR hijack into ALL frames
    await ctx.add_init_script(XHR_HIJACK_JS)

    page = await ctx.new_page()

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Step 1: Navigate and wait for Feishu to init...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)

    # Get target frame and extract document
    print(f"  Frames: {[f.url[:60] for f in page.frames]}")
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe! Trying without init script...")
        # The init script might break the page. Try without it.
        await browser.close()
        browser = await pw.chromium.launch(headless=True)
        ctx2 = await browser.new_context(storage_state="/app/data/harvester_auth.json")
        page = await ctx2.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(12000)
        print(f"  Frames (no init): {[f.url[:60] for f in page.frames]}")
        for frame in page.frames:
            if "larkoffice" in frame.url:
                target_frame = frame
                break
        if not target_frame:
            print("Still no iframe!")
            await browser.close(); await pw.stop(); return

    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if not doc:
        print("No doc!")
        await browser.close(); await pw.stop(); return

    matches = IMG_RE.findall(doc["markdown"])
    print(f"Found {len(matches)} images in document")

    # Build the download queue
    queue_items = []
    for alt, img_url in matches:
        token_m = re.search(r"/cover/([^/?]+)", img_url)
        if token_m:
            queue_items.append({"token": token_m.group(1), "url": img_url})

    print(f"Queue: {len(queue_items)} images")

    # Inject the queue into the iframe
    print("\nStep 2: Injecting download queue...")
    await target_frame.evaluate(f"window.__omni_img_queue = {json.dumps(queue_items)}")

    # Check if auth was already captured
    auth_ok = await target_frame.evaluate("window.__omni_auth_captured")
    print(f"  Auth already captured: {auth_ok}")

    if auth_ok:
        # Auth was already captured, trigger download now
        await target_frame.evaluate("""() => {
            const OrigXHR = XMLHttpRequest;
            const queue = window.__omni_img_queue;
            console.log('[OMNI] Manually triggering download for ' + queue.length + ' items');
            
            let completed = 0;
            for (const item of queue) {
                const xhr = new OrigXHR();
                xhr.open('GET', item.url, true);
                xhr.responseType = 'arraybuffer';
                xhr.withCredentials = true;
                xhr.onload = function() {
                    completed++;
                    if (this.status === 200 && this.response) {
                        const bytes = new Uint8Array(this.response);
                        let binary = '';
                        const chunkSize = 8192;
                        for (let i = 0; i < bytes.length; i += chunkSize) {
                            const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length));
                            binary += String.fromCharCode.apply(null, chunk);
                        }
                        window.__omni_img_results[item.token] = {
                            ok: true,
                            size: bytes.length,
                            b64: btoa(binary),
                        };
                    } else {
                        window.__omni_img_results[item.token] = { ok: false, status: this.status };
                    }
                };
                xhr.onerror = function() {
                    completed++;
                    window.__omni_img_results[item.token] = { ok: false, error: 'network' };
                };
                xhr.send();
            }
        }""")

    # Wait for downloads
    print("\nStep 3: Waiting for downloads...")
    for i in range(30):
        await page.wait_for_timeout(2000)
        results = await target_frame.evaluate("""() => {
            const r = window.__omni_img_results;
            const ok = Object.values(r).filter(v => v.ok).length;
            const fail = Object.values(r).filter(v => !v.ok).length;
            return { total: Object.keys(r).length, ok, fail };
        }""")
        print(f"  [{i*2}s] Results: {results['ok']} ok, {results['fail']} fail, {results['total']} total / {len(queue_items)}")
        if results['total'] >= len(queue_items):
            break

    # Get final results
    final = await target_frame.evaluate("""() => {
        const r = window.__omni_img_results;
        const summary = {};
        for (const [token, val] of Object.entries(r)) {
            if (val.ok) {
                summary[token] = { ok: true, size: val.size };
            } else {
                summary[token] = { ok: false, status: val.status, error: val.error };
            }
        }
        return summary;
    }""")

    ok_count = sum(1 for v in final.values() if v.get("ok"))
    fail_count = sum(1 for v in final.values() if not v.get("ok"))
    total_size = sum(v.get("size", 0) for v in final.values() if v.get("ok"))
    print(f"\n=== RESULT: {ok_count} ok, {fail_count} failed out of {len(queue_items)} ===")
    print(f"  Total size: {total_size // 1024} KB")

    for token, result in list(final.items())[:5]:
        print(f"  {token}: {result}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
