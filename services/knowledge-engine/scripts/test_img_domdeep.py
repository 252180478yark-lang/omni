"""Deep DOM analysis - find the ACTUAL content container and scrollable area."""
import asyncio, logging, re, base64
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

    img_responses = {}
    request_urls = {}

    def on_request(params):
        url = params.get("request", {}).get("url", "")
        if "internal-api-drive-stream" in url:
            request_urls[params.get("requestId", "")] = url

    async def on_finished(params):
        rid = params.get("requestId", "")
        if rid not in request_urls:
            return
        url = request_urls[rid]
        token_m = re.search(r"/(cover|preview)/([^/?]+)", url)
        if not token_m:
            return
        try:
            body = await cdp.send("Network.getResponseBody", {"requestId": rid})
            data = base64.b64decode(body["body"]) if body.get("base64Encoded") else body["body"].encode()
            if len(data) > 500:
                token = token_m.group(2)
                if token not in img_responses or len(data) > len(img_responses[token]):
                    img_responses[token] = data
                    print(f"  ++ {token} ({len(data)} bytes) [total: {len(img_responses)}]")
        except:
            pass

    cdp.on("Network.requestWillBeSent", on_request)
    cdp.on("Network.loadingFinished", lambda p: asyncio.ensure_future(on_finished(p)))

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(10000)

    # List all Playwright frames
    print("=== All Playwright frames ===")
    for i, frame in enumerate(page.frames):
        print(f"  [{i}] {frame.name or '(unnamed)'}: {frame.url[:100]}")

    # Find scrollable elements in MAIN page
    main_scroll = await page.evaluate("""() => {
        const results = [];
        const walk = (el, depth) => {
            if (depth > 20) return;
            const style = getComputedStyle(el);
            const isScrollable = (
                el.scrollHeight > el.clientHeight + 20 &&
                (style.overflowY === 'auto' || style.overflowY === 'scroll' ||
                 style.overflow === 'auto' || style.overflow === 'scroll')
            );
            if (isScrollable || el.scrollHeight > 2000) {
                results.push({
                    tag: el.tagName,
                    id: el.id?.substring(0, 50),
                    cls: Array.from(el.classList || []).slice(0, 3).join(' '),
                    scrollH: el.scrollHeight,
                    clientH: el.clientHeight,
                    scrollTop: el.scrollTop,
                    overflow: style.overflowY,
                    depth,
                });
            }
            for (const child of el.children) {
                walk(child, depth + 1);
            }
        };
        walk(document.documentElement, 0);
        return results;
    }""")
    print(f"\n=== Main page scrollable/tall elements: {len(main_scroll)} ===")
    for s in main_scroll:
        print(f"  {s['tag']}#{s['id']}.{s['cls']} scrollH={s['scrollH']} clientH={s['clientH']} overflow={s['overflow']} depth={s['depth']}")

    # Also look in each frame for scrollable elements
    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if target_frame:
        frame_scroll = await target_frame.evaluate("""() => {
            const results = [];
            const walk = (el, depth) => {
                if (depth > 20) return;
                if (el.scrollHeight > el.clientHeight + 10 || el.scrollHeight > 500) {
                    const style = getComputedStyle(el);
                    results.push({
                        tag: el.tagName,
                        id: el.id?.substring(0, 50),
                        cls: Array.from(el.classList || []).slice(0, 3).join(' '),
                        scrollH: el.scrollHeight,
                        clientH: el.clientHeight,
                        overflow: style.overflowY,
                        depth,
                        children: el.children.length,
                    });
                }
                for (const child of el.children) {
                    walk(child, depth + 1);
                }
            };
            walk(document.documentElement, 0);
            return results;
        }""")
        print(f"\n=== Frame scrollable/tall elements: {len(frame_scroll)} ===")
        for s in frame_scroll:
            print(f"  {'  ' * s['depth']}{s['tag']}#{s['id']}.{s['cls']} sH={s['scrollH']} cH={s['clientH']} overflow={s['overflow']} children={s['children']}")

    # Try scrolling the main page content container
    if main_scroll:
        # Find the best scrollable container
        best = max(main_scroll, key=lambda s: s['scrollH'] - s['clientH'])
        print(f"\n=== Best scrollable: {best['tag']}#{best['id']}.{best['cls']} ===")
        print(f"  scrollH={best['scrollH']} clientH={best['clientH']}")

        sel = None
        if best['id']:
            sel = f"#{best['id']}"
        elif best['cls']:
            sel = f".{best['cls'].split()[0]}"

        if sel:
            before = len(img_responses)
            print(f"\n  Scrolling {sel}...")
            total_h = await page.evaluate(f"document.querySelector('{sel}')?.scrollHeight || 0")
            pos = 0
            while pos < total_h:
                await page.evaluate(f"document.querySelector('{sel}')?.scrollTo(0, {pos})")
                await page.wait_for_timeout(2000)
                pos += 600
                new_h = await page.evaluate(f"document.querySelector('{sel}')?.scrollHeight || 0")
                if new_h > total_h:
                    total_h = new_h
                    print(f"    scrollH grew to {total_h} at pos={pos}")
            await page.wait_for_timeout(5000)
            after = len(img_responses)
            print(f"  New images from scrolling: {after - before}")

    print(f"\n=== FINAL: {len(img_responses)} unique images ===")

    await cdp.detach()
    await browser.close()
    await pw.stop()

asyncio.run(test())
