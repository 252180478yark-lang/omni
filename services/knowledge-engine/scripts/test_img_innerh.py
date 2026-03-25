"""Check iframe's window.innerHeight and try to change it via parent page iframe element."""
import asyncio, logging, re
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state="/app/data/harvester_auth.json")
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
                        print(f"  ++ {token} ({len(body)} bytes) [total: {len(captured)}]")
            except:
                pass
    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(10000)
    print(f"Initial: {len(captured)} images")

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!"); await browser.close(); await pw.stop(); return

    # Check iframe window dimensions
    dims = await target_frame.evaluate("""() => ({
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        outerWidth: window.outerWidth,
        outerHeight: window.outerHeight,
        docScrollH: document.documentElement.scrollHeight,
        docClientH: document.documentElement.clientHeight,
        bodyScrollH: document.body.scrollHeight,
        bodyClientH: document.body.clientHeight,
    })""")
    print(f"\nIframe dimensions: {dims}")

    # Find the iframe element on parent page  
    iframe_details = await page.evaluate("""() => {
        // Search ALL elements for the one containing the larkoffice frame
        const frames = document.querySelectorAll('iframe');
        const details = [];
        for (const f of frames) {
            try {
                details.push({
                    src: f.src?.substring(0, 80) || '(no src)',
                    width: f.offsetWidth,
                    height: f.offsetHeight,
                    style_h: f.style.height,
                    style_w: f.style.width,
                    parent_h: f.parentElement?.offsetHeight,
                    parent_tag: f.parentElement?.tagName,
                    parent_cls: f.parentElement?.className?.substring(0, 60),
                    computed_h: getComputedStyle(f).height,
                    computed_w: getComputedStyle(f).width,
                });
            } catch(e) {}
        }
        
        // Also check the #lark-doc-dom element
        const larkDom = document.querySelector('#lark-doc-dom');
        let larkDomInfo = null;
        if (larkDom) {
            const iframe = larkDom.querySelector('iframe');
            larkDomInfo = {
                height: larkDom.offsetHeight,
                scrollH: larkDom.scrollHeight,
                style_h: larkDom.style.height,
                hasIframe: !!iframe,
                iframeH: iframe?.offsetHeight,
            };
        }
        
        return { frames: details, larkDom: larkDomInfo };
    }""")
    print(f"\nParent page iframes:")
    for f in iframe_details["frames"]:
        print(f"  {f['src'][:50]} {f['width']}x{f['height']} computed={f['computed_w']}x{f['computed_h']}")
        print(f"    parent: {f['parent_tag']}.{f['parent_cls'][:30]} h={f['parent_h']}")
    print(f"  #lark-doc-dom: {iframe_details['larkDom']}")

    # Find the actual iframe element by traversing to find the one with the larkoffice URL
    # The frame might not have a src attribute - it could be set via JS
    frame_element_handle = await page.evaluate("""() => {
        // Try to find iframe by checking each frame's contentWindow URL
        const frames = document.querySelectorAll('iframe');
        for (const f of frames) {
            try {
                if (f.contentWindow && f.contentWindow.location.href.includes('larkoffice')) {
                    return {
                        found: true,
                        width: f.offsetWidth,
                        height: f.offsetHeight,
                        id: f.id,
                        name: f.name,
                    };
                }
            } catch(e) {
                // Cross-origin - check name attribute
                if (f.name && f.name.includes('opendoc')) {
                    return {
                        found: true,
                        width: f.offsetWidth,
                        height: f.offsetHeight,
                        id: f.id,
                        name: f.name,
                        note: 'cross-origin, matched by name',
                    };
                }
            }
        }
        
        // Try all frames including those without src
        for (const f of frames) {
            if (f.offsetHeight > 100) {
                return {
                    found: true,
                    width: f.offsetWidth,
                    height: f.offsetHeight,
                    id: f.id,
                    name: f.name,
                    src: f.src?.substring(0, 80),
                    note: 'matched by height > 100',
                };
            }
        }
        
        return { found: false };
    }""")
    print(f"\nFrame element search: {frame_element_handle}")

    # Try to find and resize via the name attribute
    frame_name = target_frame.name
    print(f"\nTarget frame name: '{frame_name}'")

    if frame_name:
        resize_result = await page.evaluate(f"""() => {{
            const f = document.querySelector('iframe[name="{frame_name}"]');
            if (!f) return {{ error: 'not found by name' }};
            
            const before = {{ w: f.offsetWidth, h: f.offsetHeight }};
            
            // Resize iframe and ALL ancestors
            f.style.height = '50000px';
            f.style.maxHeight = '50000px';
            let el = f.parentElement;
            for (let i = 0; i < 15 && el; i++) {{
                el.style.height = 'auto';
                el.style.maxHeight = 'none';
                el.style.overflow = 'visible';
                el = el.parentElement;
            }}
            
            return {{ before, after: {{ w: f.offsetWidth, h: f.offsetHeight }} }};
        }}""")
        print(f"  Resize result: {resize_result}")

        if resize_result.get("after", {}).get("h", 0) > 1000:
            # Check if innerHeight changed
            new_dims = await target_frame.evaluate("({ innerH: window.innerHeight, innerW: window.innerWidth })")
            print(f"  Iframe innerHeight after resize: {new_dims}")

            # Wait for new images
            print("  Waiting 15s for new images...")
            await page.wait_for_timeout(15000)
            print(f"  Images after resize: {len(captured)}")

    # Final count
    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    if doc:
        matches = IMG_RE.findall(doc["markdown"])
        tokens = set()
        for _, u in matches:
            m = re.search(r"/cover/([^/?]+)", u)
            if m: tokens.add(m.group(1))
        print(f"\n  Total in doc: {len(tokens)}, captured: {len(captured)}")

    await browser.close()
    await pw.stop()

asyncio.run(test())
