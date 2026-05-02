"""Inspect 罗盘真实首页 + 关键功能页 — 找真实 URL/selector。

输出:
  - snapshots/_inspect/compass_<page>.png 每页截图
  - snapshots/_inspect/compass_findings.json 包含每页的:
      final_url / title / 下载按钮 / 日期选择器 / KPI 卡 / 表格 / iframe
"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


# Probe these URLs (文档里的 + 一些猜测)
PAGES = {
    "home_root":              "https://compass.jinritemai.com/shop",
    "home_old":               "https://compass.jinritemai.com/shop/home",
    "business_part":          "https://compass.jinritemai.com/shop/business-part",
    "sell_analysis":          "https://compass.jinritemai.com/shop/sell-analysis",
    "refund_analysis":        "https://compass.jinritemai.com/shop/refund-analysis",
    "ecology":                "https://compass.jinritemai.com/shop/ecology-experience-score",
    "commodity_list":         "https://compass.jinritemai.com/shop/commodity-product-list",
    "logistics":              "https://compass.jinritemai.com/shop/logistics-diagnosis-index",
}

DOM_PROBE = r"""
() => {
  function describe(el) {
    return {
      tag: el.tagName.toLowerCase(),
      classes: (el.className && typeof el.className === 'string') ? el.className.slice(0, 80) : '',
      text: (el.innerText || '').trim().slice(0, 60),
    };
  }
  const out = {};
  out.url = window.location.href;
  out.title = document.title;
  out.body_sample = (document.body.innerText||'').slice(0, 300).replace(/\s+/g, ' ');
  out.body_blank = /功能建设中|敬请期待|404/.test(out.body_sample);

  out.export_btns = [];
  document.querySelectorAll('button, a, span, div[role="button"]').forEach(el => {
    const t = (el.innerText || '').trim();
    if (/^(下载|导出|批量下载|导出明细|下载明细|导出CSV|导出Excel)$/.test(t)) {
      out.export_btns.push(describe(el));
    }
  });
  out.export_btns = out.export_btns.slice(0, 8);

  out.date_pickers = [];
  document.querySelectorAll('input').forEach(el => {
    const ph = el.getAttribute('placeholder') || '';
    if (/日期|开始|结束|date|选择/i.test(ph)) {
      out.date_pickers.push({tag: 'input', placeholder: ph, classes: el.className.toString().slice(0, 60)});
    }
  });
  document.querySelectorAll('[class*="ange"]').forEach(el => {
    const c = el.className.toString();
    if (c.includes('Picker') || c.includes('picker')) {
      out.date_pickers.push(describe(el));
    }
  });
  out.date_pickers = out.date_pickers.slice(0, 8);

  out.kpi_cards = [];
  document.querySelectorAll('*').forEach(el => {
    if (el.children.length === 0) return;
    const t = (el.innerText || '').trim();
    if (t.length > 8 && t.length < 80) {
      if (/[\d,.]+万?[元%]?/.test(t)) {
        out.kpi_cards.push({
          tag: el.tagName,
          classes: (el.className||'').toString().slice(0, 60),
          text: t.replace(/\n+/g, ' / '),
        });
      }
    }
  });
  out.kpi_cards = out.kpi_cards.slice(0, 10);

  out.iframes = Array.from(document.querySelectorAll('iframe')).map(f => f.src).slice(0, 4);
  return out;
}
"""


async def main():
    from playwright.async_api import async_playwright
    out = Path("./snapshots/_inspect")
    out.mkdir(parents=True, exist_ok=True)
    sess = Path("./sessions/douyin_compass/user_data")

    findings = {}
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(sess), headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        for slug, url in PAGES.items():
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(6)
                shot = out / f"compass_{slug}.png"
                await page.screenshot(path=str(shot), full_page=False)
                info = await page.evaluate(DOM_PROBE)
                findings[slug] = {"target": url, **info}
                print(f"[{slug}]")
                print(f"  url     : {info['url']}")
                print(f"  title   : {info['title']!r}")
                print(f"  blank   : {info['body_blank']}")
                print(f"  body    : {info['body_sample'][:120]}")
                print(f"  exports : {[b['text'] for b in info['export_btns']]}")
                print(f"  pickers : {len(info['date_pickers'])} found")
                print(f"  kpi_n   : {len(info['kpi_cards'])} cards")
                print(f"  iframes : {info['iframes']}")
                print()
            except Exception as exc:
                print(f"[{slug}] FAIL: {exc}")
                findings[slug] = {"error": str(exc)}

        (out / "compass_findings.json").write_text(
            json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
