"""DOM inspector v3: probe known candidate URLs, screenshot each, dump real
nav structure once we land on a real workspace page.
"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


CANDIDATE_URLS = [
    "https://compass.jinritemai.com/shop",
    "https://compass.jinritemai.com/shop/home",
    "https://compass.jinritemai.com/shop/index",
    "https://compass.jinritemai.com/m/index",
    "https://compass.jinritemai.com/shop/business-part",
    "https://compass.jinritemai.com/shop/sell-analysis",
]


async def inspect():
    from playwright.async_api import async_playwright

    out_dir = Path("./snapshots/_inspect")
    out_dir.mkdir(parents=True, exist_ok=True)
    session_dir = Path("./sessions/douyin_compass/user_data")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        for i, url in enumerate(CANDIDATE_URLS):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(5)
                final = page.url
                title = await page.title()
                slug = url.rsplit("/", 1)[-1] or "root"
                shot = out_dir / f"probe_{i:02d}_{slug}.png"
                await page.screenshot(path=str(shot))
                # Detect "功能建设中" or empty body
                body_text = await page.evaluate(
                    "() => (document.body.innerText || '').slice(0, 200)"
                )
                is_blank = "功能建设中" in body_text or len(body_text.strip()) < 50
                print(f"[{i}] {url}")
                print(f"    final: {final}")
                print(f"    title: {title}")
                print(f"    blank?: {is_blank}")
                print(f"    body  : {body_text[:120].replace(chr(10),' / ')!r}")
                print(f"    shot  : {shot.name}")
                print()
            except Exception as exc:
                print(f"[{i}] {url} FAILED: {exc}")

        # On the LAST loaded page (whatever it is), dump real nav
        print("=== Final-page nav anchors (any href) ===")
        anchors = await page.evaluate("""
() => {
  const out = [];
  document.querySelectorAll('a, [role="menuitem"], li[class*="menu"], li[class*="nav"]').forEach(el => {
    const txt = (el.innerText || '').trim();
    if (!txt || txt.length > 12) return;
    const href = el.getAttribute('href') || el.getAttribute('data-href') || '';
    out.push({text: txt, href: href, classes: (el.className && typeof el.className === 'string') ? el.className.slice(0, 80) : ''});
  });
  return out.slice(0, 40);
}
""")
        for a in anchors:
            print(f"  '{a['text']}' -> {a['href']!r}  cls={a['classes'][:40]}")

        (out_dir / "probe_results.json").write_text(
            json.dumps({"anchors": anchors}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(inspect())
