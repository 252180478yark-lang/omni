"""Explore opendoc SDK state and viewport to find how to expand render zone."""
import asyncio, logging, re, json as json_mod
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

# Capture ALL postMessages with full content
CAPTURE_ALL_MSG_JS = """
(() => {
    window.__omni_all_messages = [];
    window.addEventListener('message', (event) => {
        try {
            const str = typeof event.data === 'object' ? JSON.stringify(event.data) : String(event.data);
            window.__omni_all_messages.push({
                time: Date.now(),
                data: str.substring(0, 2000),
                origin: event.origin,
            });
        } catch(e) {}
    }, true);
})();
"""

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
    await ctx.add_init_script(CAPTURE_ALL_MSG_JS)
    page = await ctx.new_page()

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
            except:
                pass
    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(12000)
    print(f"Initial images: {len(captured)}")

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!"); await browser.close(); await pw.stop(); return

    # 1. Explore viewport object
    viewport_info = await target_frame.evaluate("""() => {
        if (!window.viewport) return { exists: false };
        const vp = window.viewport;
        const props = {};
        for (const key of Object.getOwnPropertyNames(Object.getPrototypeOf(vp) || {}).concat(Object.keys(vp))) {
            try {
                const val = vp[key];
                const t = typeof val;
                if (t === 'function') {
                    props[key] = `function(${val.length} args)`;
                } else if (t === 'object' && val !== null) {
                    props[key] = JSON.stringify(val).substring(0, 200);
                } else {
                    props[key] = String(val).substring(0, 100);
                }
            } catch(e) { props[key] = `error: ${e.message}`; }
        }
        return { exists: true, props };
    }""")
    print(f"\n=== viewport object ===")
    if viewport_info.get("exists"):
        for k, v in sorted(viewport_info["props"].items()):
            print(f"  {k}: {v}")

    # 2. Explore __opendoc_state__
    state_info = await target_frame.evaluate("""() => {
        if (!window.__opendoc_state__) return { exists: false };
        const state = window.__opendoc_state__;
        const props = {};
        for (const key of Object.keys(state)) {
            try {
                const val = state[key];
                const t = typeof val;
                if (t === 'function') {
                    props[key] = `function(${val.length} args)`;
                } else if (t === 'object' && val !== null) {
                    props[key] = JSON.stringify(val).substring(0, 300);
                } else {
                    props[key] = String(val).substring(0, 100);
                }
            } catch(e) { props[key] = `error: ${e.message}`; }
        }
        return { exists: true, props };
    }""")
    print(f"\n=== __opendoc_state__ ===")
    if state_info.get("exists"):
        for k, v in sorted(state_info["props"].items()):
            print(f"  {k}: {v}")

    # 3. Explore ccmsdk
    sdk_info = await target_frame.evaluate("""() => {
        if (!window.ccmsdk) return { exists: false };
        const sdk = window.ccmsdk;
        const props = {};
        for (const key of Object.keys(sdk)) {
            try {
                const val = sdk[key];
                const t = typeof val;
                if (t === 'function') {
                    props[key] = `function(${val.length} args)`;
                } else if (t === 'object' && val !== null) {
                    props[key] = JSON.stringify(val).substring(0, 200);
                } else {
                    props[key] = String(val).substring(0, 100);
                }
            } catch(e) { props[key] = `error: ${e.message}`; }
        }
        return { exists: true, props };
    }""")
    print(f"\n=== ccmsdk ===")
    if sdk_info.get("exists"):
        for k, v in sorted(sdk_info["props"].items()):
            print(f"  {k}: {v}")

    # 4. Look at ALL postMessages
    all_msgs = await target_frame.evaluate("window.__omni_all_messages || []")
    print(f"\n=== All messages to iframe: {len(all_msgs)} ===")
    for msg in all_msgs:
        data = msg.get("data", "")
        # Look for scroll/viewport/render related
        if any(kw in data.lower() for kw in ["scroll", "viewport", "render", "visible", "height", "setscroll"]):
            print(f"  [{msg['origin'][:30]}] {data[:300]}")

    # 5. Try to directly call viewport/SDK methods to expand render zone
    print("\n=== Trying to expand render zone ===")
    before = len(captured)

    # Try modifying viewport
    result = await target_frame.evaluate("""() => {
        const results = [];
        
        // Try viewport methods
        if (window.viewport) {
            if (typeof viewport.setViewportHeight === 'function') {
                viewport.setViewportHeight(50000);
                results.push('called setViewportHeight(50000)');
            }
            if (typeof viewport.resize === 'function') {
                viewport.resize(1920, 50000);
                results.push('called resize');
            }
        }
        
        // Try __opendoc_state__
        if (window.__opendoc_state__) {
            if (window.__opendoc_state__.scrollInfo) {
                window.__opendoc_state__.scrollInfo.viewportHeight = 50000;
                window.__opendoc_state__.scrollInfo.clientHeight = 50000;
                results.push('modified scrollInfo');
            }
        }
        
        return results;
    }""")
    print(f"  Actions: {result}")
    await page.wait_for_timeout(8000)
    print(f"  Images after: {len(captured)} (was {before})")

    await browser.close()
    await pw.stop()

asyncio.run(test())
