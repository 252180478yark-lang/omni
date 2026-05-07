"""
sku_bootstrapper.py — T11b

Syncs all SKUs from 抖店后台 g-list into mvp_sku.
  - Called once at scout-agent startup.
  - Then re-run daily at 08:00 for incremental updates.
  - Uses Playwright to scrape the g-list page (no public API).
  - Falls back gracefully: if scrape fails, existing rows are untouched.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.database import get_pool

log = logging.getLogger(__name__)


def _derive_sku_id(douyin_product_id: str, idx: int) -> str:
    """Derive a stable internal SKU id from the Douyin product ID."""
    prefix = re.sub(r"\D", "", douyin_product_id)[:6]
    return f"SKU-{prefix}-{idx:04d}"


def _classify_push_tier(sku: dict[str, Any]) -> str:
    gc = sku.get("growth_class", "")
    if gc == "excellent":
        return "main"
    if gc == "good":
        return "growth"
    if gc == "declining":
        return "declining"
    return "new"


async def bootstrap_skus() -> int:
    """Full sync of shop SKUs from 抖店后台 g-list. Returns number of upserted rows."""
    skus = await _fetch_g_list_skus()
    if not skus:
        log.warning("sku_bootstrapper: no SKUs fetched, keeping existing data")
        return 0

    pool = await get_pool()
    upserted = 0
    async with pool.acquire() as conn:
        for idx, sku in enumerate(skus):
            sku_id = _derive_sku_id(sku["douyin_product_id"], idx)
            push_tier = _classify_push_tier(sku)
            await conn.execute(
                """
                INSERT INTO mvp_sku (
                    id, name, category, douyin_product_id, douyin_url, douyin_shop_id,
                    source, platform_status, total_stock, available_stock, locked_stock,
                    growth_class, created_on_platform_at, status, push_tier,
                    price_min, price_max
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    'shop_admin', $7, $8, $9, $10,
                    $11, $12, 'active', $13,
                    $14, $15
                )
                ON CONFLICT (douyin_product_id) DO UPDATE SET
                    name               = EXCLUDED.name,
                    platform_status    = EXCLUDED.platform_status,
                    total_stock        = EXCLUDED.total_stock,
                    available_stock    = EXCLUDED.available_stock,
                    locked_stock       = EXCLUDED.locked_stock,
                    growth_class       = EXCLUDED.growth_class,
                    push_tier          = EXCLUDED.push_tier,
                    price_min          = EXCLUDED.price_min,
                    price_max          = EXCLUDED.price_max,
                    updated_at         = NOW()
                """,
                sku_id,
                sku.get("name", ""),
                sku.get("category", ""),
                sku["douyin_product_id"],
                sku.get("url", ""),
                settings.douyin_shop_id,
                sku.get("platform_status"),
                sku.get("total_stock"),
                sku.get("available_stock"),
                sku.get("locked_stock"),
                sku.get("growth_class"),
                sku.get("created_on_platform_at"),
                push_tier,
                sku.get("price_min"),
                sku.get("price_max"),
            )
            upserted += 1

    log.info("sku_bootstrapper: upserted %d SKUs", upserted)
    return upserted


async def _fetch_g_list_skus() -> list[dict[str, Any]]:
    """
    Scrape 抖店后台 g-list page with Playwright.

    The g-list page renders a product table at:
    https://fxg.jinritemai.com/ffa/g/list

    Each row contains: product name, product ID, status, stock info, growth class.
    We scroll through all pages collecting rows.

    翻页防御（2026-05-07 升级）：
    - 多套 next button selector fallback（抖店 SPA 改 UI 后老 selector 失效）
    - 按 douyin_product_id 去重（点 next 没真翻时不重复入库）
    - 同页检测（连续两页第一行 ID 相同 → break）
    - 详细 log（next_btn 候选数/disabled 状态/各页 ID 范围）
    """
    session_dir = Path(settings.sessions_dir) / "douyin_shop_admin"
    session_dir.mkdir(parents=True, exist_ok=True)
    storage_state_file = session_dir / "storage_state.json"

    skus: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            # 用 storage_state.json 跨 OS 共享 cookie（host 端 chromium 写的
            # user_data 在 Windows 用 DPAPI 加密，容器 Linux 解不出，所以
            # 不用 launch_persistent_context；改用 storage_state JSON 明文）
            # 老板登录脚本：python scripts/relogin_douyin_shop_admin.py
            if not storage_state_file.exists():
                log.warning(
                    "g-list: storage_state.json 不存在 → 老板需要先跑 "
                    "scripts/relogin_douyin_shop_admin.py 登录抖店"
                )
                return []

            browser = await p.chromium.launch(
                headless=settings.playwright_headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            # 超大 viewport：让虚拟列表 buffer 一次性容纳更多行（默认 1080 只能渲 ~8 行；
            # 4000 能渲 ~22 行，配合多轮滚动累积可拿全 29 个 SKU）
            ctx = await browser.new_context(
                storage_state=str(storage_state_file),
                viewport={"width": 1920, "height": 4000},
            )
            page = await ctx.new_page()

            # 抖店后台有大量 polling/analytics,networkidle 几乎不会触发;
            # 用 domcontentloaded + 等待表格 selector 出现
            await page.goto(
                "https://fxg.jinritemai.com/ffa/g/list",
                wait_until="domcontentloaded", timeout=60000,
            )
            # SPA 渲染等表格出现 (上限 20s)
            try:
                await page.wait_for_selector("tr.ecom-g-table-row", timeout=20000)
            except Exception as exc:
                log.warning("g-list: table selector not found in 20s: %s", exc)

            # Check session validity
            if "login" in page.url or "passport" in page.url:
                log.warning("g-list: session expired, cannot sync SKUs")
                await ctx.close()
                return []

            # 关键：改 page size 到 100/页（抖店选项 10/20/50/100）→ 一页装下全店 SKU
            # 避开虚拟滚动 + 翻页两个深坑（2026-05-07 切片 12 第三发现）
            await _set_page_size_max(page)

            # Collect rows across pages with dedup + duplicate-page detection
            prev_first_id: str | None = None
            page_num = 1
            while True:
                rows = await _extract_g_list_rows(page)

                # 同页检测：连续两页第一行 ID 相同 = 没真翻
                cur_first_id = rows[0]["douyin_product_id"] if rows else None
                if page_num > 1 and cur_first_id and cur_first_id == prev_first_id:
                    log.warning(
                        "g-list page %d: first ID %s 跟上页一样，next 按钮可能没真翻；break",
                        page_num, cur_first_id,
                    )
                    break

                # 去重：按 douyin_product_id 增量入 skus（避免重复抓相同 SKU）
                new_count = 0
                for r in rows:
                    pid = r.get("douyin_product_id")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        skus.append(r)
                        new_count += 1
                log.info(
                    "g-list page %d: %d rows raw / %d new (total unique=%d) first_id=%s",
                    page_num, len(rows), new_count, len(skus), cur_first_id,
                )
                prev_first_id = cur_first_id

                # 找 next 按钮（多套 selector fallback；抖店 SPA UI 改版兜底）
                # 注意：抖店用自家 ecom-g 组件库，不是 antd，但保留 antd 兜底
                # disabled 状态有多种写法（class / aria-disabled / button[disabled]），
                # 都尝试过滤
                next_selectors = [
                    # 抖店 ecom-g 组件库（主战场，2026-05-07 实测真实结构）
                    # disabled 状态用 aria-disabled 属性，不是 class
                    'li.ecom-g-pagination-next[aria-disabled="false"] button',
                    'li[title="下一页"][aria-disabled="false"] button',
                    # 旧版兼容（class 形式）
                    'li.ecom-g-pagination-next:not(.ecom-g-pagination-disabled) button:not([disabled])',
                    'button.ecom-g-pagination-item-link[aria-label*="next"]:not([disabled])',
                    'button.ecom-g-pagination-item-link[aria-label*="下一页"]:not([disabled])',
                    # arco-design 组件库（抖店有些页面用 arco）
                    'button.arco-pagination-item-next:not([disabled])',
                    # antd 兜底
                    'button.ant-pagination-next:not([disabled])',
                    'li.ant-pagination-next:not(.ant-pagination-disabled) a',
                    # 通用兜底（最弱，只匹配带"下一页/next"关键字的可点击元素）
                    '[role="button"][aria-label="下一页"]:not([aria-disabled="true"])',
                    '[role="button"][aria-label="Next page"]:not([aria-disabled="true"])',
                ]
                next_btn = None
                hit_selector = None
                for sel in next_selectors:
                    candidate = page.locator(sel)
                    n = await candidate.count()
                    if n > 0:
                        next_btn = candidate.first
                        hit_selector = sel
                        log.debug("g-list page %d: next 按钮命中 selector=%r (count=%d)",
                                  page_num, sel, n)
                        break

                if next_btn is None:
                    # 一个也没命中 → 翻不动了（也可能是单页）
                    # 列出所有 pagination 相关元素帮诊断
                    diag = await page.locator('[class*="pagination"]').count()
                    log.info(
                        "g-list page %d: 找不到 next 按钮（候选 %d 个 selector 全 0；"
                        "页内 pagination 元素 %d 个）；可能单页或 SPA selector 失效",
                        page_num, len(next_selectors), diag,
                    )
                    break

                try:
                    await next_btn.click()
                    # 不用 networkidle (抖店后台 polling 永远不静); 给 4s 让表格重渲
                    await asyncio.sleep(4)
                except Exception as exc:
                    log.warning("g-list page %d: next click 失败 (selector=%s): %s",
                                page_num, hit_selector, exc)
                    break
                page_num += 1
                if page_num > 30:  # safety cap（之前 20 太保守，可能漏页）
                    log.warning("g-list: 翻到 page %d 仍未结束，触发安全上限 break", page_num)
                    break

            await ctx.close()
            await browser.close()

    except Exception as exc:
        log.error("g-list scrape failed: %s", exc)
        return skus  # 返已抓到的部分，不丢

    log.info("g-list scrape 完成：共 %d unique SKU，跨 %d 页", len(skus), page_num)
    return skus


async def _set_page_size_max(page) -> None:
    """点击 size changer 改 page size 到 100/页（抖店最大）— 避开虚拟滚动+翻页双坑。

    选项：10 / 20 / 50 / 100 条/页。失败容忍（log warning 不抛）。
    """
    try:
        size_changer = page.locator('[class*="size-changer"]').first
        if await size_changer.count() == 0:
            log.debug("set_page_size: 找不到 size-changer，可能 SPA 改 UI；跳过")
            return
        await size_changer.click()
        await asyncio.sleep(1)

        # 选项里 "100 条/页" 通常 dup 出现（visible + hidden）
        # 用 :has-text 精准匹配第 1 个可见的
        opt_100 = page.locator('text="100 条/页"').first
        if await opt_100.count() == 0:
            log.debug("set_page_size: 没找到 '100 条/页' 选项")
            return
        await opt_100.click()
        await asyncio.sleep(2)  # 等表格重渲

        # 再等 row count 变多（确认换页生效）
        for _ in range(10):
            n = await page.locator("tr.ecom-g-table-row").count()
            if n > 11:
                log.info("set_page_size: 切到 100/页，当前 %d 行", n)
                return
            await asyncio.sleep(0.5)
        log.warning("set_page_size: 已切但 row count 仍 ≤11，可能 SPA 没刷新")
    except Exception as exc:
        log.warning("set_page_size 失败：%s", exc)


async def _scroll_and_collect_rows(
    page, max_attempts: int = 120
) -> dict[str, dict[str, Any]]:
    """抖店 g-list 用虚拟滚动 — 每滚一次只渲染当前视口附近的行（旧行被 virtualize 回收）。
    所以"row count 稳定"是错的判停标准（DOM 行数恒定 ~8-22）。

    正确做法：
    1. 边滚边累积 douyin_product_id 去重 dict
    2. 配合 4000px 大 viewport 一次容纳更多行
    3. 每 15 轮回滚到顶 + 再滚到底（cycle 模式触发完整渲染）
    4. 直到 dict size 连续 10 轮不变 → 滚遍了

    返 {product_id: row_data}。
    """
    collected: dict[str, dict[str, Any]] = {}
    last_size = -1
    stable_iters = 0

    for attempt in range(max_attempts):
        # 抓当前 DOM 里所有 row 的 id + data，加进 collected
        row_els = await page.query_selector_all(
            "tr.ecom-g-table-row.ecom-g-table-row-level-0"
        )
        if not row_els:
            row_els = await page.query_selector_all("tr.ecom-g-table-row")

        for row_el in row_els:
            try:
                row_text = (await row_el.inner_text()) or ""
                id_match = re.search(
                    r'ID[:\s]*(\d{15,20})', row_text
                ) or re.search(r'\b(\d{15,20})\b', row_text)
                if not id_match:
                    continue
                product_id = id_match.group(1)
                if product_id in collected:
                    continue
                # 提 row 数据（跟原 _extract_g_list_rows 同一逻辑）
                collected[product_id] = await _row_to_dict(row_el, row_text, product_id)
            except Exception as exc:
                log.debug("collect skip row: %s", exc)

        cur = len(collected)
        if cur == last_size:
            stable_iters += 1
            if stable_iters >= 10:  # 连续 10 轮 dict size 不变 → 滚遍了（之前 6 太短）
                log.debug("scroll_collect: 稳定 collected=%d (attempt=%d)", cur, attempt)
                return collected
        else:
            stable_iters = 0
            last_size = cur

        # 每 15 轮：回滚到顶 + 再滚到底（cycle 模式 — 触发完整虚拟列表 cache）
        if attempt > 0 and attempt % 15 == 0:
            try:
                await page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(0.5)
            except Exception:
                pass

        # 滚到最后一行（触发虚拟列表加载下一批）
        try:
            last_row = page.locator("tr.ecom-g-table-row").last
            if await last_row.count() > 0:
                await last_row.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        # JS 强制滚所有候选容器 + window 到底
        try:
            await page.evaluate(
                """() => {
                    const sels = ['.ecom-g-table', '.ecom-g-table-container',
                                  '.ecom-g-table-body', '[class*="table-body"]'];
                    for (const s of sels) {
                        document.querySelectorAll(s).forEach(el => {
                            el.scrollTop = el.scrollHeight;
                        });
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                }"""
            )
        except Exception:
            pass

        if attempt % 5 == 4:
            try:
                await page.keyboard.press("End")
            except Exception:
                pass

        await asyncio.sleep(0.6)

    log.warning(
        "scroll_collect: %d 轮后仍未稳定，返当前 %d 个 SKU", max_attempts, len(collected)
    )
    return collected


async def _row_to_dict(row_el, row_text: str, product_id: str) -> dict[str, Any]:
    """把表格行 element 转成 SKU dict。

    抖店 g-list 8 列结构（2026-05-07 实测）：
    - [0] selection / [1] goodsInformation / [2] sellingPrice / [3] totalInventory
    - [4] newSellTitle 销量 / [5] qualityScoreTitle / [6] timeSortTitle 时间+状态
    - [7] operating 操作按钮（含"下架/编辑"等按钮文字 — 不能用 row_text 判 status）
    """
    # name（第 1 列商品信息列第一行）
    info_cell = await row_el.query_selector('td[class*="goodsInformation"]')
    name = ""
    if info_cell:
        cell_text = (await info_cell.inner_text()).strip()
        name = cell_text.split('\n')[0].strip() if cell_text else ""
    if not name:
        name = row_text.split('ID')[0].strip()[:200]

    # price（第 2 列，'￥59.90' 或 '￥10-20' 区间）
    price_min: float | None = None
    price_max: float | None = None
    price_cell = await row_el.query_selector('td[class*="sellingPrice"]')
    if price_cell:
        price_text = (await price_cell.inner_text()).strip()
        # 提所有数字（含小数点）
        nums = re.findall(r"\d+(?:\.\d+)?", price_text)
        if nums:
            try:
                price_min = float(nums[0])
                price_max = float(nums[-1]) if len(nums) > 1 else price_min
            except ValueError:
                pass

    # stock（第 3 列）
    stock_cell = await row_el.query_selector('td[class*="totalInventory"]')
    stock_text = (await stock_cell.inner_text()).strip() if stock_cell else "0"
    try:
        total_stock = int(re.sub(r"\D", "", stock_text.split('\n')[0]) or "0")
    except ValueError:
        total_stock = 0

    # platform_status（第 6 列 timeSortTitle，文本 "2026/04/25 | 18:14:37 | 售卖中"）
    # 不能用 row_text 因为第 7 列操作按钮永远含"下架"两字 → 误判
    status_cell = await row_el.query_selector('td[class*="timeSortTitle"]')
    status_text = (await status_cell.inner_text()).strip() if status_cell else ""
    if "已售罄" in status_text:
        platform_status = "out_of_stock"
    elif "已下架" in status_text or "停售" in status_text:
        platform_status = "off_sale"
    elif "暂停" in status_text:
        platform_status = "paused"
    elif "审核" in status_text:
        platform_status = "under_review"
    elif "封禁" in status_text:
        platform_status = "banned"
    elif "售卖中" in status_text or "在售" in status_text:
        platform_status = "on_sale"
    else:
        platform_status = "unknown"

    # growth_class（第 5 列 qualityScoreTitle："优秀 | 88"）
    quality_cell = await row_el.query_selector('td[class*="qualityScoreTitle"]')
    quality_text = (await quality_cell.inner_text()).strip() if quality_cell else ""
    growth_class = None
    for kw, cls in [("优秀", "excellent"), ("优质", "good"),
                     ("待优化", "optimizing"), ("衰退", "declining")]:
        if kw in quality_text:
            growth_class = cls
            break

    return {
        "douyin_product_id": product_id,
        "name": name,
        "platform_status": platform_status,
        "total_stock": total_stock,
        "available_stock": total_stock,
        "locked_stock": 0,
        "growth_class": growth_class,
        "price_min": price_min,
        "price_max": price_max,
        "created_on_platform_at": None,
        "url": f"https://fxg.jinritemai.com/ffa/g/detail?id={product_id}",
    }


async def _extract_g_list_rows(page) -> list[dict[str, Any]]:
    """Extract product rows from 抖店后台 g-list page。

    虚拟滚动（2026-05-07 切片 12 重大发现）：抖店表格滚到底时**回收旧行**（DOM
    里 tr 数恒定 ~8-15 个）。所以不能"滚到稳定再 extract"——必须 **边滚边累积**
    去重 dict，等 dict size 不再增长才停。详见 _scroll_and_collect_rows。
    """
    try:
        await page.wait_for_selector("tr.ecom-g-table-row", timeout=15000)
        collected = await _scroll_and_collect_rows(page)
        log.info("extract: 边滚边累积 %d 个唯一 SKU", len(collected))
        return list(collected.values())
    except Exception as exc:
        log.warning("extract_g_list_rows: %s", exc)
        return []
