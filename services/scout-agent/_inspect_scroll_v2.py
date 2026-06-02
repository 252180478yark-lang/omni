"""更深度诊断 g-list 虚拟滚动：尝试多种滚动方式，看哪个真触发。"""
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
        ctx = await browser.new_context(
            storage_state=str(STORAGE_STATE_FILE),
            viewport={"width": 1920, "height": 1080},  # 大视口
        )
        page = await ctx.new_page()
        await page.goto("https://fxg.jinritemai.com/ffa/g/list",
                        wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_selector("tr.ecom-g-table-row", timeout=20000)
        await asyncio.sleep(3)

        async def count_rows():
            return await page.locator("tr.ecom-g-table-row").count()

        print(f"[init] viewport=1920x1080, rows={await count_rows()}")

        # 方法 1: 滚 window
        for i in range(5):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.8)
        print(f"[after window scroll x5] rows={await count_rows()}")

        # 方法 2: 找所有可能的滚动容器
        scroll_info = await page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('*').forEach(el => {
                const cs = getComputedStyle(el);
                if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') &&
                    el.scrollHeight > el.clientHeight + 20) {
                    results.push({
                        tag: el.tagName,
                        cls: (el.className || '').toString().slice(0, 80),
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                    });
                }
            });
            return results.slice(0, 20);
        }""")
        print(f"\n=== scrollable elements ({len(scroll_info)} found) ===")
        for s in scroll_info:
            print(f"  <{s['tag']} class={s['cls']!r}> scroll={s['scrollHeight']} client={s['clientHeight']}")

        # 方法 3: 滚动每一个 scrollable 容器到底
        await page.evaluate("""() => {
            document.querySelectorAll('*').forEach(el => {
                const cs = getComputedStyle(el);
                if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') &&
                    el.scrollHeight > el.clientHeight + 20) {
                    el.scrollTop = el.scrollHeight;
                }
            });
        }""")
        await asyncio.sleep(2)
        print(f"\n[after scroll all containers] rows={await count_rows()}")

        # 方法 4: scroll_into_view 最后一行 + wait
        for i in range(5):
            try:
                last_row = page.locator("tr.ecom-g-table-row").last
                await last_row.scroll_into_view_if_needed(timeout=3000)
                await asyncio.sleep(1)
            except Exception as exc:
                print(f"  scroll_into_view err: {exc}")
        print(f"[after scroll_into_view x5] rows={await count_rows()}")

        # 方法 5: 键盘 PageDown
        await page.locator("tr.ecom-g-table-row").first.click()  # focus
        for i in range(15):
            await page.keyboard.press("PageDown")
            await asyncio.sleep(0.3)
        await asyncio.sleep(2)
        print(f"[after PageDown x15] rows={await count_rows()}")

        # 方法 6: 试试改 pageSize（如果有 size changer）
        size_changer = page.locator('[class*="size-changer"]')
        if await size_changer.count() > 0:
            print(f"\n[size_changer 存在 {await size_changer.count()} 个]")
            await size_changer.first.click()
            await asyncio.sleep(1)
            # 找选项 list
            options = await page.locator('[class*="select-item-option"]').all()
            print(f"  找到 {len(options)} 个选项")
            for opt in options[:5]:
                try:
                    txt = await opt.inner_text()
                    print(f"    option: {txt!r}")
                except Exception:
                    pass

        # 方法 7: 检查总行数（"共 N 件商品"）
        total_text = await page.locator('.ecom-g-pagination-total-text').first.inner_text()
        print(f"\n[pagination total] {total_text!r}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
