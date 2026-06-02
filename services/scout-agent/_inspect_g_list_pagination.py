"""诊断 g-list 翻页 DOM 结构 — 列出实际的 pagination 元素 outerHTML。

容器里跑：
docker exec omni-scout-agent python /app/_inspect_g_list_pagination.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

STORAGE_STATE_FILE = Path("/app/sessions/douyin_shop_admin/storage_state.json")


async def main():
    from playwright.async_api import async_playwright

    if not STORAGE_STATE_FILE.exists():
        print(f"[ERROR] storage_state.json not found at {STORAGE_STATE_FILE}")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(storage_state=str(STORAGE_STATE_FILE))
        page = await ctx.new_page()
        await page.goto("https://fxg.jinritemai.com/ffa/g/list",
                        wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector("tr.ecom-g-table-row", timeout=20000)
        except Exception as exc:
            print(f"[WARN] table selector timeout: {exc}")

        await asyncio.sleep(3)  # 多等 SPA 渲染

        # 1. 当前 URL
        print(f"\n=== URL ===\n{page.url}\n")

        # 2. 所有 pagination 相关元素
        pag_els = await page.locator('[class*="pagination"], [class*="Pagination"]').all()
        print(f"=== pagination elements ({len(pag_els)} 个) ===")
        for i, el in enumerate(pag_els[:25]):
            try:
                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                cls = await el.get_attribute("class") or ""
                text = (await el.inner_text())[:80].replace("\n", " | ")
                print(f"  [{i}] <{tag} class={cls!r}> text={text!r}")
            except Exception as exc:
                print(f"  [{i}] err: {exc}")

        # 3. 包含 "下一页" / "next" 关键字的可点击元素
        print(f"\n=== '下一页'/'next' 关键字元素 ===")
        next_text = await page.locator(':text("下一页"), :text("Next page")').all()
        print(f"  text 命中：{len(next_text)} 个")
        for i, el in enumerate(next_text[:5]):
            try:
                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                cls = await el.get_attribute("class") or ""
                aria = await el.get_attribute("aria-label") or ""
                disabled = await el.get_attribute("disabled")
                outer = (await el.evaluate("e => e.outerHTML"))[:200]
                print(f"  [{i}] <{tag} class={cls!r} aria={aria!r} disabled={disabled!r}>")
                print(f"       outer: {outer}")
            except Exception as exc:
                print(f"  [{i}] err: {exc}")

        # 4. aria-label="下一页" 直接搜
        print(f"\n=== aria-label='下一页'/'Next page' ===")
        aria_next = await page.locator('[aria-label="下一页"], [aria-label="Next page"]').all()
        print(f"  aria 命中：{len(aria_next)} 个")
        for i, el in enumerate(aria_next[:5]):
            try:
                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                cls = await el.get_attribute("class") or ""
                outer = (await el.evaluate("e => e.outerHTML"))[:300]
                print(f"  [{i}] <{tag} class={cls!r}>")
                print(f"       outer: {outer}")
            except Exception as exc:
                print(f"  [{i}] err: {exc}")

        # 5. SVG 图标按钮（抖店常用图标按钮做翻页）
        print(f"\n=== SVG 图标按钮（pagination 区域内的）===")
        svg_buttons = await page.locator('[class*="pagination"] button, [class*="Pagination"] button').all()
        print(f"  pagination button: {len(svg_buttons)} 个")
        for i, el in enumerate(svg_buttons[:10]):
            try:
                cls = await el.get_attribute("class") or ""
                aria = await el.get_attribute("aria-label") or ""
                disabled = await el.get_attribute("disabled")
                title = await el.get_attribute("title") or ""
                inner_html = (await el.evaluate("e => e.innerHTML"))[:150]
                print(f"  [{i}] class={cls[:60]!r} aria={aria!r} title={title!r} disabled={disabled!r}")
                print(f"       inner: {inner_html}")
            except Exception as exc:
                print(f"  [{i}] err: {exc}")

        # 6. 整个 pagination 区域 HTML（取第一个父级容器）
        print(f"\n=== pagination 父容器 outerHTML（前 1500 字符）===")
        pag_root = page.locator('[class*="agination"]').first
        if await pag_root.count() > 0:
            try:
                outer = (await pag_root.evaluate("e => e.outerHTML"))[:1500]
                print(outer)
            except Exception as exc:
                print(f"  err: {exc}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
