"""
HTML extraction utilities for pages that don't support CSV export
(e.g., 云图 5A cards, 沙基图, 触点 TOP10 tables).
"""
from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import Page

log = logging.getLogger(__name__)


async def extract_table_from_page(page: Page, selector: str) -> list[dict[str, str]]:
    """Extract the first matching HTML table as a list of dicts (header row as keys)."""
    html = await page.inner_html(selector)
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        log.warning("no <table> found inside selector '%s'", selector)
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    result = []
    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        result.append(dict(zip(headers, cells)))

    return result


async def extract_5a_cards_from_page(page: Page, card_selector: str) -> dict[str, Any]:
    """
    Extract 5A asset cards from 云图 assets-crowd-distribution page.
    Returns a dict like:
      {
        "o": {"count": "2.3亿", "industry_avg": "...", "outperform_pct": "超过同行85%"},
        "a1": {...}, "a2": {...}, "a3": {...}, "a4": {...}, "a5": {...},
      }
    """
    try:
        await page.wait_for_selector(card_selector, timeout=10000)
        html = await page.inner_html("body")
    except Exception as exc:
        log.warning("cannot find 5A cards: %s", exc)
        return {}

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(card_selector)
    result: dict[str, Any] = {}

    # Attempt generic extraction: card title + main number + sub-numbers
    for card in cards:
        title_el = card.find(class_=lambda c: c and "title" in c.lower())
        value_el = card.find(class_=lambda c: c and ("count" in c.lower() or "number" in c.lower()))
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        value = value_el.get_text(strip=True) if value_el else ""
        result[title] = {"raw_value": value}

    return result


async def get_page_text(page: Page, selector: str) -> str:
    """Return inner text of a selector, empty string if not found."""
    try:
        return (await page.inner_text(selector)).strip()
    except Exception:
        return ""
