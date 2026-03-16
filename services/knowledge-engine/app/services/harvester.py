"""Knowledge Harvester — crawl help-center pages and extract structured content.

Uses Playwright for authenticated browser automation and extracts full document
content from Feishu iframe embeds via window.DATA.clientVars block parsing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}

# ═══ Job Store (in-memory, personal-use) ═══

_jobs: dict[str, dict] = {}


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


# ═══ Feishu Block Tree Parser ═══

FEISHU_GET_DATA_JS = """() => {
    try {
        if (window.DATA && window.DATA.clientVars) {
            return JSON.stringify(window.DATA.clientVars);
        }
    } catch(e) {}
    return null;
}"""


def _get_text(bd: dict) -> str:
    """Extract plain text from a Feishu block data dict.

    Handles multiple storage layouts:
      - text.initialAttributedTexts.text  (primary)
      - text.initialAttributedTexts.aPool (attributed segments)
      - snippet.text  (code blocks)
    """
    t = bd.get("text", {})
    if isinstance(t, dict):
        iat = t.get("initialAttributedTexts", {})
        texts = iat.get("text", {})
        if texts and isinstance(texts, dict):
            ordered = sorted(texts.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)
            return "".join(str(v) for _, v in ordered if v)
        if isinstance(texts, str) and texts:
            return texts
        apool = iat.get("aPool", [])
        if apool and isinstance(apool, list):
            parts = []
            for seg in apool:
                if isinstance(seg, dict):
                    insert = seg.get("insert", "")
                    if insert:
                        parts.append(str(insert))
                elif isinstance(seg, str):
                    parts.append(seg)
            if parts:
                return "".join(parts)
    snippet = bd.get("snippet", {})
    if isinstance(snippet, dict):
        s_text = snippet.get("text", "")
        if s_text:
            return str(s_text)
    return ""


def _get_image_info(bd: dict) -> dict | None:
    img = bd.get("image", {})
    if not img or not isinstance(img, dict):
        token = bd.get("token", "")
        if not token:
            return None
        return {
            "token": token,
            "name": "image.png",
            "cdn_url": (
                f"https://internal-api-drive-stream.larkoffice.com/space/api/box/stream/"
                f"download/v2/cover/{token}/?fallback_source=1&height=1280"
                f"&mount_point=docx_image&policy=equal&width=1280"
            ),
        }
    token = img.get("token", "")
    if not token:
        return None
    return {
        "token": token,
        "name": img.get("name", "image.png"),
        "cdn_url": (
            f"https://internal-api-drive-stream.larkoffice.com/space/api/box/stream/"
            f"download/v2/cover/{token}/?fallback_source=1&height=1280"
            f"&mount_point=docx_image&policy=equal&width=1280"
        ),
    }


def _cell_to_text(bmap: dict, cell_children: list) -> str:
    """Render table cell children as compact multi-line text for table cells.

    Unlike _blocks_to_md which outputs one-item-per-line, this joins
    nested content with <br> to preserve structure inside markdown tables.
    """
    parts: list[str] = []
    for cid in cell_children:
        block = bmap.get(cid, {})
        bd = block.get("data", {})
        btype = bd.get("type", "unknown")
        text = _get_text(bd)
        children = bd.get("children", [])

        if btype == "text":
            if text.strip():
                parts.append(text.strip())
        elif btype.startswith("heading"):
            if text.strip():
                parts.append(f"**{text.strip()}**")
        elif btype in ("ordered", "bullet"):
            for i, sub_id in enumerate(children, 1):
                sb = bmap.get(sub_id, {}).get("data", {})
                st = _get_text(sb)
                prefix = f"{i}." if btype == "ordered" else "•"
                if st.strip():
                    parts.append(f"{prefix} {st.strip()}")
                sub_ch = sb.get("children", [])
                if sub_ch:
                    nested = _cell_to_text(bmap, sub_ch)
                    if nested:
                        parts.append(f"  {nested}")
        elif btype == "image":
            img = _get_image_info(bd)
            if img:
                parts.append(f"![{img['name']}]({img['cdn_url']})")
        elif btype in ("callout", "quote_container"):
            if text.strip():
                parts.append(text.strip())
            if children:
                nested = _cell_to_text(bmap, children)
                if nested:
                    parts.append(nested)
        elif btype == "todo":
            mark = "✓" if bd.get("checked") else "☐"
            if text.strip():
                parts.append(f"{mark} {text.strip()}")
        elif btype == "code_block":
            if text.strip():
                parts.append(f"`{text.strip()}`")
        else:
            if text.strip():
                parts.append(text.strip())
            if children:
                nested = _cell_to_text(bmap, children)
                if nested:
                    parts.append(nested)
    return " <br> ".join(parts)


def _blocks_to_md(bmap: dict, block_ids: list, indent: str = "") -> list[str]:
    """Recursively convert Feishu block IDs into Markdown lines."""
    lines: list[str] = []
    for bid in block_ids:
        block = bmap.get(bid, {})
        bd = block.get("data", {})
        btype = bd.get("type", "unknown")
        text = _get_text(bd)
        children = bd.get("children", [])

        if btype == "page":
            lines.extend(_blocks_to_md(bmap, children, indent))

        elif btype.startswith("heading"):
            level = int(btype[-1]) if btype[-1].isdigit() else 1
            if text.strip():
                lines.append(f"{'#' * level} {text}")

        elif btype == "text":
            if text.strip():
                lines.append(f"{indent}{text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent))

        elif btype in ("ordered", "bullet"):
            for i, cid in enumerate(children, 1):
                cb = bmap.get(cid, {}).get("data", {})
                ct = _get_text(cb)
                sub = cb.get("children", [])
                prefix = f"{i}. " if btype == "ordered" else "- "
                lines.append(f"{indent}{prefix}{ct}" if ct.strip() else f"{indent}{prefix}...")
                if sub:
                    lines.extend(_blocks_to_md(bmap, sub, indent + "   "))

        elif btype == "todo":
            mark = "x" if bd.get("checked") else " "
            lines.append(f"{indent}- [{mark}] {text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent + "   "))

        elif btype == "toggle_list":
            if text.strip():
                lines.append(f"{indent}<details><summary>{text}</summary>")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent))
            if text.strip():
                lines.append(f"{indent}</details>")

        elif btype == "image":
            img = _get_image_info(bd)
            if img:
                lines.append(f"{indent}![{img['name']}]({img['cdn_url']})")

        elif btype == "whiteboard":
            token = bd.get("token", "")
            if token:
                lines.append(f"{indent}[画板: {token}]")

        elif btype == "table":
            rows_id = bd.get("rows_id", [])
            cols_id = bd.get("columns_id", [])
            cell_set = bd.get("cell_set", {})
            if not rows_id or not cols_id:
                if children:
                    lines.extend(_blocks_to_md(bmap, children, indent))
            else:
                for ri, row_id in enumerate(rows_id):
                    row_cells = []
                    for col_id in cols_id:
                        cell_info = cell_set.get(row_id + col_id, {})
                        cell_bid = cell_info.get("block_id", "")
                        if cell_bid:
                            cell_bd = bmap.get(cell_bid, {}).get("data", {})
                            cell_ch = cell_bd.get("children", [])
                            cell_text = _cell_to_text(bmap, cell_ch)
                            cell_text = cell_text.replace("|", "\\|")
                            row_cells.append(cell_text if cell_text.strip() else " ")
                        else:
                            row_cells.append(" ")
                    lines.append("| " + " | ".join(row_cells) + " |")
                    if ri == 0:
                        lines.append("|" + "|".join(" --- " for _ in cols_id) + "|")

        elif btype == "table_cell":
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent))

        elif btype in ("table_row",):
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent))

        elif btype in ("callout", "quote_container"):
            if text.strip():
                lines.append(f"{indent}> {text}")
            for sl in _blocks_to_md(bmap, children, indent):
                lines.append(f"{indent}> {sl}")

        elif btype == "code_block":
            lang = bd.get("language", "")
            lines.append(f"{indent}```{lang}")
            if text.strip():
                lines.append(text)
            if children:
                for cid in children:
                    ct = _get_text(bmap.get(cid, {}).get("data", {}))
                    if ct:
                        lines.append(ct)
            lines.append(f"{indent}```")

        elif btype in ("grid", "grid_column", "column_list", "column"):
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent))

        elif btype in ("synced_block", "synced_source"):
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent))

        elif btype == "bookmark":
            link = bd.get("link", {})
            url = link.get("url", "") if isinstance(link, dict) else str(link) if link else ""
            if url:
                lines.append(f"{indent}[{text or url}]({url})")
            elif text.strip():
                lines.append(f"{indent}{text}")

        elif btype == "embed":
            embed_url = bd.get("url", "") or bd.get("embedUrl", "")
            if embed_url:
                lines.append(f"{indent}[嵌入内容]({embed_url})")
            elif text.strip():
                lines.append(f"{indent}{text}")

        elif btype == "file":
            fname = bd.get("file", {}).get("name", "") if isinstance(bd.get("file"), dict) else ""
            lines.append(f"{indent}[文件: {fname or text}]")

        elif btype == "divider":
            lines.append("---")

        elif btype in ("iframe", "bitable", "mindnote", "sheet", "diagram"):
            if text.strip():
                lines.append(f"{indent}[{btype}: {text}]")
            elif children:
                lines.extend(_blocks_to_md(bmap, children, indent))

        else:
            if text.strip():
                lines.append(f"{indent}{text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent))

    return lines


def parse_feishu_document(client_vars_json: str) -> dict | None:
    try:
        cv = json.loads(client_vars_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if cv.get("code") != 0:
        return None
    d = cv.get("data", {})
    bmap = d.get("block_map", {})
    if not bmap:
        return None

    page_bid = None
    page_title = ""
    for bid, block in bmap.items():
        bd = block.get("data", {})
        if bd.get("type") == "page":
            page_bid = bid
            page_title = _get_text(bd)
            break

    if not page_bid:
        return None

    md_lines = _blocks_to_md(bmap, [page_bid])

    text_lines = [l for l in md_lines if not l.startswith("![")]
    return {
        "title": page_title,
        "markdown": "\n\n".join(md_lines),
        "text": "\n".join(text_lines),
        "block_count": len(bmap),
    }


# ═══ Navigation Tree ═══

async def fetch_nav_tree(url: str) -> dict:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    gid = qs.get("graphId", [""])[0]
    pid = qs.get("pageId", [""])[0]
    sid = qs.get("spaceId", [""])[0]

    api_url = (
        f"https://yuntu.oceanengine.com/support/content/root"
        f"?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
        f"&__ssrDirect=true&graphId={gid}&mappingType=1"
        f"&pageId={pid}&spaceId={sid}"
    )

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
        resp = await client.get(api_url)
        resp.raise_for_status()
        text = resp.text.strip()
        if text.startswith("{"):
            brace = end = 0
            for i, ch in enumerate(text):
                if ch == "{":
                    brace += 1
                elif ch == "}":
                    brace -= 1
                    if brace == 0:
                        end = i + 1
                        break
            data = json.loads(text[:end])
        else:
            data = json.loads(text)

    nodes = data.get("nodes", [])
    graph = data.get("graph", {})
    articles: list[dict] = []

    def walk(node_list: list, path: str = "") -> None:
        for n in node_list:
            name = n.get("mappingName", "")
            is_leaf = n.get("mappingType") == 2
            mid = n.get("mappingId")
            current_path = f"{path}/{name}" if path else name
            if is_leaf and mid:
                articles.append({
                    "title": name,
                    "mapping_id": mid,
                    "graph_path": current_path,
                    "target_id": n.get("targetId") or mid,
                })
            for child in n.get("children", []):
                walk([child], current_path)

    walk(nodes)

    return {
        "graph_name": graph.get("graphName", ""),
        "graph_id": graph.get("graphId", ""),
        "articles": articles,
        "total_articles": len(articles),
    }


# ═══ Crawl Pipeline ═══

async def crawl_articles(
    url: str,
    auth_state_path: str,
    max_pages: int | None = None,
    job_id: str | None = None,
) -> dict:
    from playwright.async_api import async_playwright

    if job_id is None:
        job_id = str(uuid4())

    _jobs[job_id] = {"status": "crawling", "progress": 0, "chapters": [], "error": None}

    try:
        tree = await fetch_nav_tree(url)
        articles = tree["articles"]
        if max_pages:
            articles = articles[:max_pages]

        _jobs[job_id]["status"] = "browser_starting"
        _jobs[job_id]["total"] = len(articles)

        pw = await async_playwright().__aenter__()
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=auth_state_path)
        page = await ctx.new_page()

        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        gid = qs.get("graphId", [""])[0]
        pid = qs.get("pageId", [""])[0]
        sid = qs.get("spaceId", [""])[0]
        base_url = f"https://support.oceanengine.com/support/content/root?graphId={gid}&pageId={pid}&spaceId={sid}"

        await page.goto(base_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(".base-tree-title span[title]", timeout=15000)
        except Exception:
            pass

        _jobs[job_id]["status"] = "extracting"
        chapters: list[dict] = []
        prev_hash = ""

        for idx, article in enumerate(articles):
            title = article["title"]
            _jobs[job_id]["progress"] = idx

            for attempt in range(3):
                try:
                    clicked = await page.evaluate("""(t) => {
                        const spans = document.querySelectorAll('.base-tree-title span[title]');
                        for (const s of spans) { if (s.getAttribute('title') === t) { s.click(); return true; } }
                        return false;
                    }""", title)

                    if not clicked and attempt == 0:
                        await page.evaluate("""() => {
                            document.querySelectorAll('.base-tree-treenode:not(.base-tree-treenode-open) .base-tree-switcher:not(.base-tree-switcher-noop)')
                                .forEach(s => s.click());
                        }""")
                        await page.wait_for_timeout(1000)
                        await page.evaluate("""(t) => {
                            const spans = document.querySelectorAll('.base-tree-title span[title]');
                            for (const s of spans) { if (s.getAttribute('title') === t) { s.click(); return true; } }
                        }""", title)

                    await page.wait_for_timeout(3000)

                    target_frame = None
                    for _ in range(10):
                        for frame in page.frames:
                            if any(k in frame.url for k in ["larkoffice", "feishu", "larksuite"]):
                                target_frame = frame
                                break
                        if target_frame:
                            break
                        await page.wait_for_timeout(2000)

                    if target_frame:
                        for _ in range(8):
                            try:
                                raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
                                if raw:
                                    parsed_doc = parse_feishu_document(raw)
                                    if parsed_doc and len(parsed_doc["text"]) > 30:
                                        cur_hash = str(hash(parsed_doc["text"][:200]))
                                        if cur_hash != prev_hash:
                                            prev_hash = cur_hash
                                            chapters.append({
                                                "index": idx,
                                                "title": title,
                                                "graph_path": article["graph_path"],
                                                "markdown": parsed_doc["markdown"],
                                                "text": parsed_doc["text"],
                                                "word_count": len(parsed_doc["text"]),
                                                "block_count": parsed_doc["block_count"],
                                                "source_url": page.url,
                                            })
                                            break
                            except Exception:
                                pass
                            await page.wait_for_timeout(2000)

                    if chapters and chapters[-1]["index"] == idx:
                        break
                    if attempt < 2:
                        await page.wait_for_timeout(3000)
                except Exception:
                    if attempt == 2:
                        chapters.append({
                            "index": idx,
                            "title": title,
                            "graph_path": article["graph_path"],
                            "markdown": "",
                            "text": "",
                            "word_count": 0,
                            "error": "extraction_failed",
                        })

            await page.wait_for_timeout(2000)
            logger.info("Harvester [%d/%d] %s — %d chars", idx + 1, len(articles), title,
                        chapters[-1]["word_count"] if chapters else 0)

        await browser.close()
        await pw.__aexit__(None, None, None)

        _jobs[job_id].update({
            "status": "done",
            "progress": len(articles),
            "chapters": chapters,
            "graph_name": tree["graph_name"],
            "total_articles": tree["total_articles"],
        })

    except Exception as e:
        logger.exception("Harvester crawl failed")
        _jobs[job_id].update({"status": "failed", "error": str(e)})

    return _jobs[job_id]
