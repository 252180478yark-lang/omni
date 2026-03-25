"""Intercept postMessage between parent and iframe to expand the visible render zone."""
import asyncio, logging, re, base64
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

# Inject into the iframe: intercept postMessage to log and modify scroll/viewport messages
INTERCEPT_MSG_JS = """
(() => {
    window.__omni_messages = [];
    const origPostMessage = window.parent.postMessage.bind(window.parent);
    
    // Log all messages FROM iframe TO parent
    const origParentPM = window.parent.postMessage;
    
    // Intercept messages received BY iframe FROM parent
    window.addEventListener('message', (event) => {
        const data = event.data;
        if (typeof data === 'object' && data !== null) {
            const str = JSON.stringify(data).substring(0, 300);
            if (str.includes('scroll') || str.includes('viewport') || str.includes('visible') || 
                str.includes('height') || str.includes('render') || str.includes('offset') ||
                str.includes('rect') || str.includes('area') || str.includes('position')) {
                window.__omni_messages.push({
                    direction: 'parent->iframe',
                    time: Date.now(),
                    data: str,
                });
            }
        }
    }, true);  // Use capture phase to see messages before Feishu handles them
})();
"""

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")

    # Inject message interceptor into all frames
    await ctx.add_init_script(INTERCEPT_MSG_JS)

    page = await ctx.new_page()

    # Track images
    captured = {}
    async def on_response(response):
        if "internal-api-drive-stream" not in response.url or not response.ok:
            return
        token_m = re.search(r"/(cover|preview)/([^/?]+)", response.url)
        if token_m:
            try:
                body = await response.body()
                if len(body) > 500:
                    token = token_m.group(2)
                    if token not in captured or len(body) > len(captured[token]):
                        captured[token] = body
                        print(f"  ++ {token} ({len(body)} bytes) [total: {len(captured)}]")
            except:
                pass
    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    print("Loading page...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)
    print(f"  Initial images: {len(captured)}")

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!")
        await browser.close(); await pw.stop(); return

    # Check captured messages
    messages = await target_frame.evaluate("window.__omni_messages || []")
    print(f"\n=== Captured messages (scroll/viewport related): {len(messages)} ===")
    for msg in messages[:20]:
        print(f"  [{msg['direction']}] {msg['data'][:200]}")

    # Also check what messages the parent page is sending
    parent_msgs = await page.evaluate("""() => {
        return window.__omni_messages || [];
    }""")
    print(f"\n=== Parent messages: {len(parent_msgs)} ===")
    for msg in parent_msgs[:10]:
        print(f"  [{msg['direction']}] {msg['data'][:200]}")

    # Check ALL message listener types on the iframe window
    print("\n=== Looking for opendoc SDK config ===")
    opendoc_info = await target_frame.evaluate("""() => {
        // Check for global opendoc-related objects
        const checks = {
            __lark_opendoc__: typeof window.__lark_opendoc__,
            __opendoc_config__: typeof window.__opendoc_config__,
            lark: typeof window.lark,
            tt: typeof window.tt,
            DATA: typeof window.DATA,
            __NEXT_DATA__: typeof window.__NEXT_DATA__,
        };
        
        // Check for any window property that might contain scroll/viewport config
        const interesting = {};
        for (const key of Object.getOwnPropertyNames(window)) {
            if (key.includes('scroll') || key.includes('viewport') || 
                key.includes('render') || key.includes('opendoc') ||
                key.includes('sdk') || key.includes('bridge')) {
                try {
                    interesting[key] = typeof window[key];
                } catch(e) {}
            }
        }
        
        return { checks, interesting };
    }""")
    print(f"  Checks: {opendoc_info['checks']}")
    print(f"  Interesting globals: {opendoc_info['interesting']}")

    # Check for JSBridge or opendoc SDK
    sdk_info = await target_frame.evaluate("""() => {
        // Look for any bridge/SDK objects
        const results = [];
        const search = (obj, path, depth) => {
            if (depth > 3 || !obj || typeof obj !== 'object') return;
            for (const key of Object.keys(obj)) {
                if (key.toLowerCase().includes('scroll') || 
                    key.toLowerCase().includes('viewport') ||
                    key.toLowerCase().includes('render') ||
                    key.toLowerCase().includes('visible')) {
                    try {
                        const val = obj[key];
                        const type = typeof val;
                        results.push(`${path}.${key} (${type})`);
                        if (type === 'function') {
                            results.push(`  -> ${val.toString().substring(0, 100)}`);
                        } else if (type === 'object' && val !== null) {
                            results.push(`  -> ${JSON.stringify(val).substring(0, 100)}`);
                        }
                    } catch(e) {}
                }
            }
        };
        
        // Check common SDK entry points
        if (window.lark) search(window.lark, 'lark', 0);
        if (window.tt) search(window.tt, 'tt', 0);
        if (window.__lark_opendoc__) search(window.__lark_opendoc__, '__lark_opendoc__', 0);
        
        return results;
    }""")
    print(f"\n=== SDK scroll/viewport properties ===")
    for s in sdk_info[:20]:
        print(f"  {s}")

    # Try to send fake viewport message from parent to iframe
    print("\n=== Sending fake viewport messages ===")
    feishu_origin = "https://bytedance.larkoffice.com"

    # Common opendoc message formats
    fake_messages = [
        {"type": "setViewportRect", "data": {"top": 0, "bottom": 50000, "height": 50000}},
        {"type": "scroll", "data": {"scrollTop": 0, "scrollHeight": 50000, "clientHeight": 50000}},
        {"type": "opendoc.scroll", "scrollTop": 0, "viewportHeight": 50000},
        {"method": "setViewport", "params": {"top": 0, "height": 50000}},
        {"event": "scroll", "scrollTop": 0, "viewportHeight": 50000, "scrollHeight": 50000},
    ]

    before = len(captured)
    for msg in fake_messages:
        await page.evaluate(f"""() => {{
            const iframe = document.querySelector('iframe[src*="larkoffice"]') || 
                          Array.from(document.querySelectorAll('iframe')).find(f => f.contentWindow);
            if (iframe) {{
                iframe.contentWindow.postMessage({json.dumps(msg)}, '*');
            }}
        }}""")
    await page.wait_for_timeout(5000)
    print(f"  After fake messages: {len(captured)} images (was {before})")

    # Get doc info
    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if doc:
        matches = IMG_RE.findall(doc["markdown"])
        print(f"\n  Total images in doc: {len(matches)}")
        print(f"  Captured: {len(captured)}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
