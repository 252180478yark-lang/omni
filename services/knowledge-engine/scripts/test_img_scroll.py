"""Scroll through iframe and capture all loaded images via response interception."""
import asyncio, logging, re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
from playwright.async_api import async_playwright
from app.services.harvester import parse_feishu_document, FEISHU_GET_DATA_JS

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(
        storage_state="/app/data/harvester_auth.json",
        viewport={"width": 1920, "height": 10000},  # Very tall viewport
    )
    page = await ctx.new_page()

    captured_images = {}

    async def on_response(response):
        url = response.url
        if "internal-api-drive-stream" in url and response.ok:
            token_m = re.search(r"/(cover|preview)/([^/?]+)", url)
            if token_m:
                token = token_m.group(2)
                try:
                    body = await response.body()
                    if len(body) > 500:
                        ct = response.headers.get("content-type", "image/png")
                        captured_images[token] = {"data": body, "ct": ct}
                except:
                    pass

    page.on("response", on_response)

    url = "https://yuntu.oceanengine.com/support/content/143250?graphId=610&pageId=445&spaceId=221"
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(3000)

    target_frame = None
    for frame in page.frames:
        if "larkoffice" in frame.url:
            target_frame = frame
            break

    if not target_frame:
        print("No iframe!")
        await browser.close(); await pw.stop()
        return

    # Get scroll info from various containers
    scroll_info = await target_frame.evaluate("""() => {
        const doc = document.documentElement;
        const body = document.body;
        // Find the main scrollable container
        const containers = document.querySelectorAll('[class*="scroll"], [class*="content"], [class*="editor"]');
        const scrollables = [];
        for (const el of containers) {
            if (el.scrollHeight > el.clientHeight + 50) {
                scrollables.push({
                    tag: el.tagName,
                    class: el.className?.substring(0, 80),
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                });
            }
        }
        return {
            docScrollH: doc.scrollHeight,
            bodyScrollH: body.scrollHeight,
            scrollables: scrollables,
        };
    }""")
    print(f"Doc scrollHeight: {scroll_info['docScrollH']}")
    print(f"Body scrollHeight: {scroll_info['bodyScrollH']}")
    print(f"Scrollable containers: {len(scroll_info['scrollables'])}")
    for s in scroll_info['scrollables'][:5]:
        print(f"  {s['tag']} scrollH={s['scrollHeight']} clientH={s['clientHeight']} class={s['class']}")

    # Try scrolling the main container and all scrollable containers
    for s in scroll_info['scrollables']:
        cls = s['class']
        if cls:
            first_cls = cls.split()[0] if ' ' in cls else cls
            try:
                await target_frame.evaluate(f"""() => {{
                    const el = document.querySelector('.{first_cls}');
                    if (el) {{
                        const h = el.scrollHeight;
                        let pos = 0;
                        const interval = setInterval(() => {{
                            pos += 500;
                            el.scrollTo(0, pos);
                            if (pos >= h) clearInterval(interval);
                        }}, 200);
                    }}
                }}""")
            except:
                pass

    # Also scroll the main document
    await target_frame.evaluate("""() => {
        const h = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
        let pos = 0;
        const interval = setInterval(() => {
            pos += 500;
            window.scrollTo(0, pos);
            if (pos >= h) clearInterval(interval);
        }, 200);
    }""")

    # Wait for images to load
    await page.wait_for_timeout(10000)

    # Extract document
    raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
    doc = parse_feishu_document(raw)
    matches = IMG_RE.findall(doc["markdown"])
    tokens_in_doc = set()
    for _, cdn_url in matches:
        m = re.search(r"/cover/([^/?]+)/", cdn_url)
        if m:
            tokens_in_doc.add(m.group(1))

    print(f"\nTokens in document: {len(tokens_in_doc)}")
    print(f"Tokens captured: {len(captured_images)}")
    matched = tokens_in_doc & set(captured_images.keys())
    print(f"Matched: {len(matched)}")

    # Save captured images
    img_dir = Path("/tmp/test_imgs")
    img_dir.mkdir(exist_ok=True)
    for token, info in captured_images.items():
        if token in tokens_in_doc:
            ext = "jpg" if "jpeg" in info["ct"] else "png"
            (img_dir / f"{token}.{ext}").write_bytes(info["data"])

    print(f"\nSaved {len(matched)} images to /tmp/test_imgs/")
    for f in sorted(img_dir.iterdir()):
        print(f"  {f.name} — {f.stat().st_size} bytes")

    await browser.close()
    await pw.stop()

asyncio.run(test())
