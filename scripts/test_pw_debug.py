"""Debug: check page structure and take screenshot."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

AUTH_FILE = Path(r"E:\app\data\harvester_auth.json")
URL = "https://yuntu.oceanengine.com/support/content/2258?graphId=610&pageId=445&spaceId=221"


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state=str(AUTH_FILE))
    page = await ctx.new_page()

    print(f"Going to {URL}")
    await page.goto(URL, wait_until="networkidle", timeout=30000)

    print(f"URL: {page.url}")
    title = await page.title()
    print(f"Title: {title}")

    # Wait a bit for dynamic content
    await page.wait_for_timeout(5000)

    # Check all iframes
    for i, frame in enumerate(page.frames):
        print(f"  Frame [{i}]: {frame.url[:120]}")

    # Check for content div
    content = await page.evaluate("""() => {
        const iframes = document.querySelectorAll('iframe');
        const info = [];
        iframes.forEach((iframe, i) => {
            info.push({
                index: i,
                src: iframe.src || '(empty)',
                width: iframe.offsetWidth,
                height: iframe.offsetHeight,
                style: iframe.getAttribute('style') || ''
            });
        });
        return {
            iframe_count: iframes.length,
            iframes: info,
            body_text_length: document.body.innerText.length,
            body_text_preview: document.body.innerText.substring(0, 500),
        };
    }""")
    print(f"\nIframes: {content['iframe_count']}")
    for iframe in content['iframes']:
        print(f"  [{iframe['index']}] src={iframe['src'][:100]} size={iframe['width']}x{iframe['height']}")
    print(f"\nBody text length: {content['body_text_length']}")
    print(f"Body preview:\n{content['body_text_preview'][:300]}")

    # Screenshot
    await page.screenshot(path="e:/agent/omni/scripts/yuntu_debug.png", full_page=True)
    print("\nScreenshot saved to scripts/yuntu_debug.png")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
