"""Inspect 抖店后台 (fxg.jinritemai.com) — find true product-list URL +
real DOM table selectors.

Probes a few candidate URLs (商品/g-list patterns), screenshots each, then on
the page that looks most like a product table dumps the actual <table> /
<tr> classes, ant-* prefixes, etc.
"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


CANDIDATES = [
    "https://fxg.jinritemai.com/ffa/g/list",
    "https://fxg.jinritemai.com/ffa/mshop/homepage/index",
    "https://fxg.jinritemai.com/",
    "https://fxg.jinritemai.com/ffa/g/index",
    "https://fxg.jinritemai.com/m/goods",
]


async def main():
    from playwright.async_api import async_playwright

    out = Path("./snapshots/_inspect")
    out.mkdir(parents=True, exist_ok=True)

    sess = Path("./sessions/douyin_shop_admin/user_data")
    findings = {}

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(sess), headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        for i, url in enumerate(CANDIDATES):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(5)
                final = page.url
                title = await page.title()
                body = await page.evaluate("() => (document.body.innerText||'').slice(0,200)")
                shot = out / f"sa_{i:02d}_{url.rsplit('/',1)[-1] or 'root'}.png"
                await page.screenshot(path=str(shot))
                row_count = await page.evaluate("""
() => ({
  ant_rows: document.querySelectorAll('tr.ant-table-row').length,
  any_tr: document.querySelectorAll('tr').length,
  byted_rows: document.querySelectorAll('[class*="byted"][class*="row"]').length,
  goods_card: document.querySelectorAll('[class*="goods"], [class*="product"]').length,
  // sample first table
  table_class: (document.querySelector('table')?.className || '').slice(0,80),
  first_tr_class: (document.querySelector('tbody tr')?.className || '').slice(0,80),
  has_iframe: document.querySelectorAll('iframe').length,
  visible_text_sample: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,160),
})
""")
                blank = "功能建设中" in body or row_count.get("any_tr", 0) == 0
                findings[url] = {"final": final, "title": title, "blank": blank, **row_count}
                print(f"[{i}] {url}")
                print(f"    final: {final}")
                print(f"    title: {title!r}")
                print(f"    blank: {blank}")
                print(f"    row_count: {row_count}")
                print(f"    shot: {shot.name}")
                print()
            except Exception as exc:
                print(f"[{i}] {url} FAILED: {exc}")
                findings[url] = {"error": str(exc)}

        # On whichever URL had the most rows, also dump real selectors
        best_url = max(
            (u for u in findings if "any_tr" in findings[u]),
            key=lambda u: findings[u].get("any_tr", 0),
            default=None,
        )
        if best_url and findings[best_url].get("any_tr", 0) > 0:
            print(f"=== Best page: {best_url} (rows={findings[best_url]['any_tr']}) ===")
            await page.goto(best_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            details = await page.evaluate("""
() => {
  const out = {};
  // Top-level table
  const tbl = document.querySelector('table') || document.querySelector('[role="table"]');
  out.table_tag = tbl ? tbl.tagName : null;
  out.table_class = tbl ? tbl.className : null;
  // First 3 tbody rows
  const trs = Array.from(document.querySelectorAll('tbody tr')).slice(0, 3);
  out.rows = trs.map(tr => ({
    classes: tr.className,
    cell_count: tr.querySelectorAll('td').length,
    text_sample: (tr.innerText||'').slice(0, 120).replace(/\\s+/g,' '),
    cells_first_class: Array.from(tr.querySelectorAll('td')).slice(0,4).map(td => (td.className||'').slice(0,40)),
  }));
  // Any pagination
  out.pagination = (document.querySelector('[class*="agination"]')?.className || '').slice(0, 60);
  // Look for product id patterns in text
  out.id_patterns = Array.from(document.querySelectorAll('*')).slice(0,500).reduce((acc,el) => {
    const t = el.innerText||'';
    const m = t.match(/\\b(\\d{15,20})\\b/);
    if (m && acc.length < 5) acc.push({id: m[1], tag: el.tagName, cls: (el.className||'').slice(0,40)});
    return acc;
  }, []);
  return out;
}
""")
            print(json.dumps(details, ensure_ascii=False, indent=2))
            findings["_best_details"] = details

        (out / "shop_admin_findings.json").write_text(
            json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
