"""Inspect 云图 5A 资产页真实 DOM — 找 6 张大卡的 selector + 数字位置。"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


URL = "https://yuntu.oceanengine.com/yuntu_brand/ecom/assets/crowd/distribution"


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

        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(8)  # SPA 重渲染

        print(f"final url: {page.url}")
        await page.screenshot(path=str(out / "yuntu_5a_full.png"), full_page=True)
        print(f"saved full screenshot: yuntu_5a_full.png")

        # Hunt for 5A cards
        info = await page.evaluate("""
() => {
  const out = {};

  // Look for elements containing "O 机会" or "A1" / "A2" etc.
  const tagged = [];
  document.querySelectorAll('*').forEach(el => {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 200) return;
    // Must look like a 5A card label
    if (/^(O|A1|A2|A3|A4|A5)([\\s\\-—:：].{0,15})?$/m.test(t.split('\\n')[0])) {
      tagged.push({
        tag: el.tagName,
        cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 80) : '',
        text: t.slice(0, 120).replace(/\\n+/g, ' / '),
        // climb up to find the parent card
        parent_cls: el.parentElement ? (el.parentElement.className||'').toString().slice(0, 80) : '',
      });
    }
  });
  out.label_candidates = tagged.slice(0, 12);

  // Look for big numbers (5A counts are usually displayed as "13.2万", "9,400" etc)
  const numbers = [];
  document.querySelectorAll('*').forEach(el => {
    const t = (el.innerText || '').trim();
    if (!t) return;
    if (/^[\\d,.]+万?$/.test(t) && t.length < 12) {
      numbers.push({
        cls: (el.className||'').toString().slice(0,60),
        text: t,
        parent_cls: el.parentElement ? (el.parentElement.className||'').toString().slice(0, 60) : '',
      });
    }
  });
  out.number_elements = numbers.slice(0, 20);

  // Common card-container class patterns
  const candidates = ['crowd', 'asset', 'five', '5a', 'card', 'panel', 'distribution'];
  out.card_containers = [];
  candidates.forEach(kw => {
    document.querySelectorAll(`[class*="${kw}"]`).forEach(el => {
      out.card_containers.push({
        kw: kw,
        cls: (el.className||'').toString().slice(0, 100),
        children_count: el.children.length,
        text_sample: (el.innerText||'').slice(0, 80).replace(/\\n+/g, ' / '),
      });
    });
  });
  // de-dup by cls
  const seen = new Set();
  out.card_containers = out.card_containers.filter(c => {
    if (seen.has(c.cls)) return false;
    seen.add(c.cls); return true;
  }).slice(0, 15);

  // Page title for context
  out.title = document.title;
  out.url = window.location.href;
  out.body_sample = (document.body.innerText||'').slice(0, 400).replace(/\\s+/g, ' ');
  return out;
}
""")
        (out / "yuntu_5a_dom.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"saved DOM analysis: yuntu_5a_dom.json")
        print()
        print(f"=== Body sample ===")
        print(info.get("body_sample", "")[:300])
        print()
        print(f"=== 5A label candidates ({len(info.get('label_candidates', []))}) ===")
        for c in info.get("label_candidates", [])[:6]:
            print(f"  {c['tag']}.{c['cls'][:50]} text={c['text'][:60]}")
        print()
        print(f"=== Number elements ({len(info.get('number_elements', []))}) ===")
        for n in info.get("number_elements", [])[:8]:
            print(f"  {n['text']}  parent={n['parent_cls'][:50]}")
        print()
        print(f"=== Card containers ({len(info.get('card_containers', []))}) ===")
        for c in info.get("card_containers", [])[:8]:
            print(f"  [{c['kw']}] {c['cls'][:60]} -> {c['children_count']} kids: {c['text_sample'][:60]}")

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
