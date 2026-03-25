"""Deep-dive into Feishu iframe DOM to find the virtual scroll container."""
import asyncio, logging, re
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from playwright.async_api import async_playwright

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
                        captured[token] = len(body)
                        print(f"  ++ Captured: {token} ({len(body)} bytes)")
            except:
                pass

    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!"); await browser.close(); await pw.stop(); return

    # 1. Find ALL scrollable elements
    scroll_info = await target_frame.evaluate("""() => {
        const results = [];
        const walk = (el, depth) => {
            if (depth > 15) return;
            const style = getComputedStyle(el);
            const isScrollable = (
                (el.scrollHeight > el.clientHeight + 10 && 
                 (style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll'))
            );
            if (isScrollable) {
                results.push({
                    tag: el.tagName,
                    id: el.id?.substring(0, 40),
                    cls: el.className?.substring(0, 80),
                    scrollH: el.scrollHeight,
                    clientH: el.clientHeight,
                    scrollTop: el.scrollTop,
                    depth: depth,
                    children: el.children.length,
                });
            }
            for (const child of el.children) {
                walk(child, depth + 1);
            }
        };
        walk(document.body, 0);
        return results;
    }""")
    print(f"=== Scrollable elements: {len(scroll_info)} ===")
    for s in scroll_info:
        print(f"  {s['tag']}#{s['id']} .{s['cls'][:50]}")
        print(f"    scrollH={s['scrollH']} clientH={s['clientH']} depth={s['depth']} children={s['children']}")

    # 2. Try scrolling each scrollable container
    if scroll_info:
        for idx, s in enumerate(scroll_info):
            sel = None
            if s['id']:
                sel = f"#{s['id']}"
            elif s['cls']:
                first_cls = s['cls'].split()[0]
                sel = f".{first_cls}"

            if sel:
                print(f"\n--- Scrolling: {sel} (scrollH={s['scrollH']}) ---")
                before_captured = len(captured)

                try:
                    total_h = await target_frame.evaluate(f"document.querySelector('{sel}')?.scrollHeight || 0")
                    pos = 0
                    while pos < total_h:
                        await target_frame.evaluate(f"document.querySelector('{sel}')?.scrollTo(0, {pos})")
                        await page.wait_for_timeout(2000)
                        pos += 500
                        new_h = await target_frame.evaluate(f"document.querySelector('{sel}')?.scrollHeight || 0")
                        if new_h > total_h:
                            total_h = new_h
                            print(f"    scrollH grew to {total_h} at pos {pos}")

                    after_captured = len(captured)
                    print(f"  New images from this container: {after_captured - before_captured}")
                except Exception as e:
                    print(f"  Error scrolling {sel}: {e}")

    # 3. Also try keyboard navigation in the frame
    print("\n--- Trying keyboard navigation ---")
    before_kb = len(captured)
    await target_frame.click("body", timeout=3000)
    for i in range(30):
        await page.keyboard.press("PageDown")
        await page.wait_for_timeout(1000)
    after_kb = len(captured)
    print(f"  New images from keyboard nav: {after_kb - before_kb}")

    print(f"\n=== Total captured: {len(captured)} unique images ===")

    await browser.close()
    await pw.stop()

asyncio.run(test())
