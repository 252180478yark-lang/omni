"""诊断 g-list 表格行渲染 — 看是不是虚拟滚动。"""
from __future__ import annotations

import asyncio
from pathlib import Path

STORAGE_STATE_FILE = Path("/app/sessions/douyin_shop_admin/storage_state.json")


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(storage_state=str(STORAGE_STATE_FILE))
        page = await ctx.new_page()
        await page.goto("https://fxg.jinritemai.com/ffa/g/list",
                        wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_selector("tr.ecom-g-table-row", timeout=20000)
        await asyncio.sleep(3)

        # before scroll
        n0 = await page.locator("tr.ecom-g-table-row").count()
        n0_l0 = await page.locator("tr.ecom-g-table-row.ecom-g-table-row-level-0").count()
        print(f"=== before scroll: {n0} rows total ({n0_l0} level-0)")

        # check first few rows for ID match
        import re
        rows = await page.locator("tr.ecom-g-table-row").all()
        with_id = 0
        without_id = 0
        for el in rows[:25]:
            try:
                txt = await el.inner_text()
                m = re.search(r'\b\d{15,20}\b', txt)
                if m:
                    with_id += 1
                else:
                    without_id += 1
            except Exception:
                pass
        print(f"  rows with ID match: {with_id} / {with_id + without_id} (missing: {without_id})")

        # 滚动表格到底（不同 selector 试）
        # 抖店可能用自定义虚拟滚动容器
        scroll_selectors = [
            'div.ecom-g-table-body',
            'div[class*="table-body"]',
            'div.ecom-g-table-container',
            '.ecom-g-table',
        ]
        for sel in scroll_selectors:
            count = await page.locator(sel).count()
            print(f"  scroll candidate {sel!r}: {count} matches")

        # 用 scrollHeight 滚动主页面 + table 内
        # 试 1：window scroll
        for i in range(5):
            await page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(0.3)

        # 试 2：table body scroll
        for sel in scroll_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.evaluate("el => el.scrollTop = el.scrollHeight")
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        await asyncio.sleep(2)

        n1 = await page.locator("tr.ecom-g-table-row").count()
        n1_l0 = await page.locator("tr.ecom-g-table-row.ecom-g-table-row-level-0").count()
        print(f"\n=== after scroll: {n1} rows total ({n1_l0} level-0)")

        # check IDs again
        rows = await page.locator("tr.ecom-g-table-row").all()
        with_id = 0
        for el in rows:
            try:
                txt = await el.inner_text()
                if re.search(r'\b\d{15,20}\b', txt):
                    with_id += 1
            except Exception:
                pass
        print(f"  rows with ID match: {with_id} / {n1}")

        # 列出前 3 行不带 ID 的 inner_text 看长啥样
        print(f"\n=== 前 3 行没 ID 的内容（debug）===")
        no_id_count = 0
        for i, el in enumerate(rows):
            if no_id_count >= 3:
                break
            try:
                txt = (await el.inner_text())[:150].replace("\n", " | ")
                if not re.search(r'\b\d{15,20}\b', txt):
                    print(f"  [{i}] {txt!r}")
                    no_id_count += 1
            except Exception:
                pass

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
