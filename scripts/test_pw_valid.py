"""Test with a valid article from the nav tree."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
import httpx

AUTH_FILE = Path(r"E:\app\data\harvester_auth.json")
BASE_URL = "https://yuntu.oceanengine.com/support/content/root?graphId=610&pageId=445&spaceId=221"


async def main():
    # First get nav tree to find valid articles
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post("http://localhost:8002/api/v1/knowledge/harvester/tree", json={"url": BASE_URL})
        tree = r.json()["data"]
        articles = tree["articles"]
        print(f"Found {len(articles)} articles")
        for a in articles[:5]:
            print(f"  [{a['mapping_id']}] {a['title']}")

    if not articles:
        return

    # Pick first article
    art = articles[0]
    mid = art["mapping_id"]
    article_url = f"https://yuntu.oceanengine.com/support/content/{mid}?graphId=610&pageId=445&spaceId=221"
    print(f"\nTesting: {art['title']} ({mid})")
    print(f"URL: {article_url}")

    # Test SSR API first
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as c:
        ssr_url = (
            f"https://yuntu.oceanengine.com/support/content/{mid}"
            f"?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
            f"&__ssrDirect=true&graphId=610&mappingType=2&pageId=445&spaceId=221"
        )
        r = await c.get(ssr_url)
        if r.status_code == 200:
            data = json.loads(r.text)
            cd = data.get("contentData", {})
            ct = cd.get("contentType", "")
            content = cd.get("content", "")[:200] if cd.get("content") else "(empty)"
            print(f"SSR contentType: {ct}")
            print(f"SSR content preview: {content}")
        else:
            print(f"SSR failed: {r.status_code}")

    # Now test browser
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(storage_state=str(AUTH_FILE))
    page = await ctx.new_page()

    print(f"\nBrowser navigating...")
    await page.goto(article_url, wait_until="networkidle", timeout=30000)
    print(f"Final URL: {page.url}")

    await page.wait_for_timeout(5000)

    # Check frames
    for i, frame in enumerate(page.frames):
        print(f"  Frame [{i}]: {frame.url[:120]}")

    # Check body
    body_info = await page.evaluate("""() => ({
        text_len: document.body.innerText.length,
        text: document.body.innerText.substring(0, 500),
        iframes: Array.from(document.querySelectorAll('iframe')).map(f => ({
            src: f.src || f.getAttribute('src') || '(none)',
            w: f.offsetWidth,
            h: f.offsetHeight
        }))
    })""")
    print(f"\nBody text: {body_info['text_len']} chars")
    print(f"Preview: {body_info['text'][:300]}")
    print(f"Iframes: {body_info['iframes']}")

    await page.screenshot(path="e:/agent/omni/scripts/yuntu_valid.png", full_page=True)
    print("\nScreenshot saved")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
