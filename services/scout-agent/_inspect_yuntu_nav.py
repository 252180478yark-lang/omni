"""Inspect 云图 nav 结构 — 找所有左侧菜单的真实 URL。"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


async def main():
    from playwright.async_api import async_playwright
    out = Path("./snapshots/_inspect")
    out.mkdir(parents=True, exist_ok=True)
    sess = Path("./sessions/yuntu/user_data")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(sess), headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Land on yuntu workspace home
        await page.goto("https://yuntu.oceanengine.com/yuntu_brand/ecom",
                        wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(8)

        await page.screenshot(path=str(out / "yuntu_home.png"), full_page=True)
        print(f"yuntu home url: {page.url}")
        print(f"saved: yuntu_home.png")

        # Dump all anchors + clickable nav items
        nav = await page.evaluate("""
() => {
  const items = [];
  // 1. <a> tags with href
  document.querySelectorAll('a').forEach(a => {
    const txt = (a.innerText || '').trim();
    if (txt && txt.length < 20 && a.href) {
      items.push({type: 'a', text: txt, href: a.href});
    }
  });
  // 2. menu items (often spans/divs in SPA nav)
  document.querySelectorAll('[class*="menu"] [class*="item"], [class*="nav"] [class*="item"], li[class*="menu"]').forEach(el => {
    const txt = (el.innerText || '').trim().split('\\n')[0];
    if (txt && txt.length < 20) {
      const a = el.querySelector('a');
      items.push({
        type: 'menu',
        text: txt,
        href: a ? a.href : null,
        cls: (el.className||'').toString().slice(0, 60),
      });
    }
  });
  // de-dup by text
  const seen = new Set();
  return items.filter(i => {
    const key = i.text + (i.href || '');
    if (seen.has(key)) return false;
    seen.add(key); return true;
  }).slice(0, 60);
}
""")
        (out / "yuntu_nav.json").write_text(
            json.dumps(nav, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n=== {len(nav)} nav items ===")
        for n in nav:
            print(f"  [{n['type']:4s}] {n['text'][:25]:30s} -> {n.get('href','')[:80]}")

        # If we find "5A资产" or similar, click it and dump landed url
        targets = ["5A关系资产", "5A资产", "关系资产", "5A流转", "品牌心智", "GMV", "触点效能", "搜索"]
        for target in targets:
            try:
                # Try clicking by text
                el = await page.get_by_text(target, exact=False).first.element_handle(timeout=2000)
                if not el:
                    continue
                await el.click(timeout=3000)
                await asyncio.sleep(4)
                print(f"  clicked '{target}' -> {page.url}")
                shot = out / f"yuntu_nav_{target}.png"
                await page.screenshot(path=str(shot))
            except Exception as exc:
                print(f"  click '{target}' failed: {str(exc)[:80]}")

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
