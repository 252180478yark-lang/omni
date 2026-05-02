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
                    growth_class, created_on_platform_at, status, push_tier
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    'shop_admin', $7, $8, $9, $10,
                    $11, $12, 'active', $13
                )
                ON CONFLICT (douyin_product_id) DO UPDATE SET
                    name               = EXCLUDED.name,
                    platform_status    = EXCLUDED.platform_status,
                    total_stock        = EXCLUDED.total_stock,
                    available_stock    = EXCLUDED.available_stock,
                    locked_stock       = EXCLUDED.locked_stock,
                    growth_class       = EXCLUDED.growth_class,
                    push_tier          = EXCLUDED.push_tier,
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
    """
    session_dir = Path(settings.sessions_dir) / "douyin_shop_admin"
    session_dir.mkdir(parents=True, exist_ok=True)
    storage_file = session_dir / "storage_state.json"

    skus: list[dict[str, Any]] = []

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            # Persistent context loads cookies from user_data_dir; storage_state
            # is not a valid kwarg here (API rejects it).
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(session_dir / "user_data"),
                headless=settings.playwright_headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

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

            # Collect rows across pages
            page_num = 1
            while True:
                rows = await _extract_g_list_rows(page)
                skus.extend(rows)
                log.info("g-list page %d: %d rows (total=%d)", page_num, len(rows), len(skus))

                # 抖店后台用 ecom-g-pagination (自家 UI 库),不是 antd
                next_btn = page.locator(
                    'button.ecom-g-pagination-item-link[aria-label*="next"], '
                    'li.ecom-g-pagination-next:not(.ecom-g-pagination-disabled) button, '
                    'button.ant-pagination-next:not([disabled])'
                )
                if await next_btn.count() == 0:
                    break
                try:
                    await next_btn.first.click()
                    # 不用 networkidle (抖店后台 polling 永远不静); 给 4s 让表格重渲
                    await asyncio.sleep(4)
                except Exception as exc:
                    log.warning("g-list pagination click failed: %s", exc)
                    break
                page_num += 1
                if page_num > 20:  # safety cap
                    break

            await ctx.close()

    except Exception as exc:
        log.error("g-list scrape failed: %s", exc)
        return []

    return skus


async def _extract_g_list_rows(page) -> list[dict[str, Any]]:
    """Extract product rows from 抖店后台 g-list page.

    Real selectors (verified 2026-05 via _inspect_shop_admin.py):
      - 表格行: tr.ecom-g-table-row (level-0 = data rows)
      - 商品信息列: td.ecom-g-table-cell.style_goodsInformation*
      - 售价列: td.ecom-g-table-cell.style_sellingPrice*
      - 库存列: td.ecom-g-table-cell.style_totalInventory*
      - 商品 ID: appears as "ID:DDDDDDDDDDDDD" in row text + visible in HTML id attrs
    """
    rows = []
    try:
        await page.wait_for_selector("tr.ecom-g-table-row", timeout=15000)
        row_els = await page.query_selector_all("tr.ecom-g-table-row.ecom-g-table-row-level-0")
        if not row_els:  # fallback if level-0 selector misses
            row_els = await page.query_selector_all("tr.ecom-g-table-row")

        for row_el in row_els:
            try:
                row_text = (await row_el.inner_text()) or ""
                # Product ID: "ID:3757631870687379783" pattern in row text,
                # or any 15-20 digit number (douyin product ids are 18-19 digits).
                id_match = re.search(r'ID[:\s]*(\d{15,20})', row_text) or re.search(r'\b(\d{15,20})\b', row_text)
                if not id_match:
                    continue
                product_id = id_match.group(1)

                # Goods info cell — first non-checkbox cell holds name + ID
                info_cell = await row_el.query_selector('td[class*="goodsInformation"]')
                name = ""
                if info_cell:
                    cell_text = (await info_cell.inner_text()).strip()
                    # First line is typically the product name
                    name = cell_text.split('\n')[0].strip() if cell_text else ""
                if not name:
                    # Fallback: take first ~50 chars of row text up to "ID:"
                    name = row_text.split('ID')[0].strip()[:200]

                # Inventory cell
                stock_cell = await row_el.query_selector('td[class*="totalInventory"]')
                stock_text = (await stock_cell.inner_text()).strip() if stock_cell else "0"
                try:
                    total_stock = int(re.sub(r"\D", "", stock_text.split('\n')[0]) or "0")
                except ValueError:
                    total_stock = 0

                # Status: 抖店没有显式 status 列,但 row text 含 "现货模式" / "下架" 等
                if "下架" in row_text or "停售" in row_text:
                    platform_status = "off_sale"
                elif "暂停" in row_text:
                    platform_status = "paused"
                else:
                    platform_status = "on_sale"

                # Growth class (商品诊断分类) — last-ish column shows 优秀/优质/待优化/衰退
                growth_class = None
                for kw, cls in [("优秀", "excellent"), ("优质", "good"),
                                 ("待优化", "optimizing"), ("衰退", "declining")]:
                    if kw in row_text:
                        growth_class = cls
                        break

                rows.append({
                    "douyin_product_id": product_id,
                    "name": name,
                    "platform_status": platform_status,
                    "total_stock": total_stock,
                    "available_stock": total_stock,
                    "locked_stock": 0,
                    "growth_class": growth_class,
                    "created_on_platform_at": None,
                    "url": f"https://fxg.jinritemai.com/ffa/g/detail?id={product_id}",
                })
            except Exception as exc:
                log.debug("skip row: %s", exc)
    except Exception as exc:
        log.warning("extract_g_list_rows: %s", exc)

    return rows
