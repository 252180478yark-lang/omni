"""Knowledge Harvester — crawl help-center pages and extract structured content.

Uses Playwright for authenticated browser automation and extracts full document
content from Feishu iframe embeds via window.DATA.clientVars block parsing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx

from app.services.content_cleaner import (
    clean_image_markdown,
    clean_ssr_content,
    validate_image_description,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}

# ═══ Job Store (in-memory, personal-use) ═══

_jobs: dict[str, dict] = {}
_login_sessions: dict[str, dict] = {}


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def get_login_session(session_id: str) -> dict | None:
    return _login_sessions.get(session_id)


# ═══ Browser Login ═══

async def start_browser_login(
    target_url: str,
    auth_state_path: str,
    session_id: str | None = None,
) -> dict:
    """Launch a visible browser for the user to log in, then capture cookies.

    The browser opens on the local desktop.  The function polls for session
    cookies and automatically saves them once the user has logged in.
    """
    if session_id is None:
        session_id = str(uuid4())

    session: dict = {
        "status": "launching",
        "cookies_saved": 0,
        "error": None,
    }
    _login_sessions[session_id] = session

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        session.update({"status": "failed", "error": "Playwright not installed"})
        return session

    async def _run():
        pw = None
        browser = None
        try:
            session["status"] = "browser_open"
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=False)
            ctx = await browser.new_context()
            page = await ctx.new_page()

            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

            session["status"] = "waiting_login"

            # Poll until we detect authenticated session cookies or timeout (5 min)
            deadline = time.time() + 300
            while time.time() < deadline:
                await asyncio.sleep(3)
                try:
                    current_url = page.url
                except Exception:
                    break

                cookies = await ctx.cookies()
                session_cookies = [
                    c for c in cookies
                    if any(k in c["name"].lower() for k in ("session", "sid_tt", "sid_guard", "uid_tt"))
                ]
                if session_cookies and "login" not in current_url.lower():
                    session["status"] = "saving"
                    # Filter to relevant domains
                    target_cookies = [
                        c for c in cookies
                        if any(d in c.get("domain", "") for d in ("oceanengine", "bytedance", "toutiao"))
                    ]
                    if not target_cookies:
                        target_cookies = cookies

                    # Save as Playwright storage state
                    pw_cookies = []
                    for c in target_cookies:
                        pw_cookies.append({
                            "name": c["name"],
                            "value": c["value"],
                            "domain": c["domain"],
                            "path": c.get("path", "/"),
                            "httpOnly": c.get("httpOnly", False),
                            "secure": c.get("secure", True),
                            "sameSite": c.get("sameSite", "None"),
                        })
                    state = {"cookies": pw_cookies, "origins": []}
                    p = Path(auth_state_path)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps(state, ensure_ascii=False, indent=2))

                    session.update({
                        "status": "done",
                        "cookies_saved": len(pw_cookies),
                    })
                    logger.info("Browser login: saved %d cookies to %s", len(pw_cookies), p)

                    # Keep browser open briefly so user sees success
                    await asyncio.sleep(2)
                    break
            else:
                session.update({"status": "timeout", "error": "Login timed out (5 min)"})

        except Exception as e:
            logger.exception("Browser login failed")
            session.update({"status": "failed", "error": str(e)})
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if pw:
                try:
                    await pw.stop()
                except Exception:
                    pass

    asyncio.create_task(_run())
    return {"session_id": session_id, "status": session["status"]}


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

    # Join lines with intelligent spacing: table rows (starting with |)
    # must be separated by single newlines to render as valid markdown tables.
    parts: list[str] = []
    for i, line in enumerate(md_lines):
        if i == 0:
            parts.append(line)
            continue
        prev = md_lines[i - 1]
        is_table_row = line.lstrip().startswith("|")
        prev_is_table_row = prev.lstrip().startswith("|")
        if is_table_row and prev_is_table_row:
            parts.append("\n" + line)
        else:
            parts.append("\n\n" + line)

    return {
        "title": page_title,
        "markdown": "".join(parts),
        "text": "\n".join(text_lines),
        "block_count": len(bmap),
    }


def _parse_block_map(bmap: dict) -> dict | None:
    """Parse a raw block_map dict (from paginated client_vars responses)."""
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

    parts: list[str] = []
    for i, line in enumerate(md_lines):
        if i == 0:
            parts.append(line)
            continue
        prev = md_lines[i - 1]
        is_table_row = line.lstrip().startswith("|")
        prev_is_table_row = prev.lstrip().startswith("|")
        if is_table_row and prev_is_table_row:
            parts.append("\n" + line)
        else:
            parts.append("\n\n" + line)

    return {
        "title": page_title,
        "markdown": "".join(parts),
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
            children = n.get("subTreeNodes") or n.get("children") or []
            walk(children, current_path)

    walk(nodes)

    return {
        "graph_name": graph.get("graphName", ""),
        "graph_id": graph.get("graphId", ""),
        "articles": articles,
        "total_articles": len(articles),
    }


# ═══ Crawl Pipeline ═══

async def _fetch_article_ssr(
    client: httpx.AsyncClient,
    mapping_id: int | str,
    gid: str,
    pid: str,
    sid: str,
) -> dict | None:
    """Fetch article metadata via SSR API (works without auth)."""
    api_url = (
        f"https://yuntu.oceanengine.com/support/content/{mapping_id}"
        f"?__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
        f"&__ssrDirect=true&graphId={gid}&mappingType=2"
        f"&pageId={pid}&spaceId={sid}"
    )
    try:
        resp = await client.get(api_url)
        if resp.status_code == 200:
            data = json.loads(resp.text)
            return data.get("contentData")
    except Exception:
        pass
    return None


async def _extract_feishu_via_browser(
    page,
    article_url: str,
    cdn_url_data: dict[str, dict],
    timeout_ms: int = 30000,
) -> dict | None:
    """Navigate to article page and extract Feishu docx content.

    ``cdn_url_data`` is populated by a response handler in the caller that
    intercepts /space/api/box/file/cdn_url/ responses with encrypted CDN URLs.
    """
    logger.info("Browser navigating to: %s", article_url)
    try:
        await page.goto(article_url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        logger.warning("Navigation failed: %s", e)
        return None

    final_url = page.url
    logger.info("Page URL after navigation: %s", final_url)
    if "login" in final_url.lower() or "passport" in final_url.lower():
        logger.warning("Redirected to login page — auth cookies may be invalid")
        return None

    target_frame = None
    elapsed = 0
    while elapsed < timeout_ms:
        for frame in page.frames:
            if any(k in frame.url for k in ["larkoffice", "feishu", "larksuite"]):
                target_frame = frame
                break
        if target_frame:
            logger.info("Found Feishu iframe: %s", target_frame.url[:150])
            break
        await page.wait_for_timeout(2000)
        elapsed += 2000

    if not target_frame:
        logger.warning("No Feishu iframe found after %dms", timeout_ms)
        return None

    for attempt in range(10):
        try:
            raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
            if raw:
                doc = parse_feishu_document(raw)
                if doc and len(doc.get("text", "")) > 30:
                    logger.info("Extracted %d chars from iframe (attempt %d)", len(doc["text"]), attempt + 1)

                    # Collect image tokens from the document
                    img_tokens: set[str] = set()
                    for _, u in _IMG_RE.findall(doc.get("markdown", "")):
                        tm = re.search(r"/cover/([^/?]+)", u)
                        if tm:
                            img_tokens.add(tm.group(1))

                    missing = img_tokens - set(cdn_url_data.keys())
                    if missing:
                        # Step 1: Scroll iframe to trigger lazy-loaded CDN requests
                        try:
                            await target_frame.evaluate("""() => {
                                return new Promise(resolve => {
                                    const containers = [
                                        document.scrollingElement,
                                        document.documentElement,
                                        ...document.querySelectorAll('[class*="render"], [class*="layout"], [class*="editor"], [class*="doc"]')
                                    ].filter(Boolean);
                                    const el = containers.find(e => e.scrollHeight > e.clientHeight + 100) || containers[0];
                                    if (!el) { resolve(); return; }
                                    const step = Math.max(400, Math.floor(el.scrollHeight / 20));
                                    let pos = 0;
                                    const timer = setInterval(() => {
                                        pos += step;
                                        el.scrollTo(0, pos);
                                        if (pos >= el.scrollHeight) { clearInterval(timer); el.scrollTo(0, 0); resolve(); }
                                    }, 100);
                                    setTimeout(() => { clearInterval(timer); resolve(); }, 15000);
                                });
                            }""")
                        except Exception:
                            pass
                        await page.wait_for_timeout(3000)

                        # Step 2: Batch-fetch CDN keys for still-missing tokens
                        still_missing = list(img_tokens - set(cdn_url_data.keys()))
                        if still_missing:
                            logger.info("Batch-fetching CDN keys for %d missing image tokens", len(still_missing))
                            for i in range(0, len(still_missing), 10):
                                batch = still_missing[i:i + 10]
                                try:
                                    batch_result = await target_frame.evaluate(
                                        """(tokens) => {
                                        return new Promise(async (resolve) => {
                                            try {
                                                const resp = await fetch('/space/api/box/file/cdn_url/', {
                                                    method: 'POST',
                                                    headers: {'Content-Type': 'application/json'},
                                                    body: JSON.stringify({file_tokens: tokens, type: 'image'}),
                                                    credentials: 'include'
                                                });
                                                const data = await resp.json();
                                                resolve(JSON.stringify(data));
                                            } catch(e) {
                                                resolve(JSON.stringify({error: e.message}));
                                            }
                                        });
                                    }""",
                                        batch,
                                    )
                                    if batch_result:
                                        batch_data = json.loads(batch_result)
                                        for item in batch_data.get("data") or []:
                                            token = item.get("file_token", "")
                                            if token and item.get("url"):
                                                cdn_url_data[token] = {
                                                    "url": item["url"],
                                                    "secret": item.get("secret", ""),
                                                    "nonce": item.get("nonce", ""),
                                                }
                                except Exception as e:
                                    logger.debug("Batch CDN fetch error: %s", e)

                        logger.info("CDN keys collected: %d/%d image tokens", len(img_tokens & set(cdn_url_data.keys())), len(img_tokens))
                    else:
                        await page.wait_for_timeout(2000)

                    return doc
                logger.debug("Data found but too short (attempt %d)", attempt + 1)
        except Exception as e:
            logger.debug("Frame evaluate error (attempt %d): %s", attempt + 1, e)
        await page.wait_for_timeout(2000)

    logger.warning("Failed to extract content after 10 attempts")
    return None


_IMG_RE = re.compile(r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)")

IMAGE_DIR = Path(
    __import__("os").environ.get("HARVESTER_IMAGE_DIR", "/app/data/images")
)


def _detect_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] == b"RIFF":
        return "webp"
    return "png"


async def _download_encrypted_images(
    cdn_url_data: dict[str, dict],
    tokens_needed: set[str],
    job_id: str,
) -> dict[str, bytes]:
    """Download images from feishucdn.com and decrypt with AES-GCM.

    cdn_url_data maps token -> {url, secret, nonce}.
    Returns token -> decrypted bytes for successfully downloaded images.
    """
    from base64 import b64decode

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        logger.warning("cryptography package not available; skipping encrypted image download")
        return {}

    available = tokens_needed & set(cdn_url_data.keys())
    if not available:
        return {}

    img_dir = IMAGE_DIR / job_id
    img_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, bytes] = {}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for token in available:
            info = cdn_url_data[token]
            url = info.get("url", "")
            secret = info.get("secret", "")
            nonce_b64 = info.get("nonce", "")
            if not (url and secret and nonce_b64):
                continue
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                key = b64decode(secret)
                nonce = b64decode(nonce_b64)
                decrypted = AESGCM(key).decrypt(nonce, resp.content, None)
                if len(decrypted) > 100:
                    result[token] = decrypted
            except Exception:
                logger.debug("Failed to decrypt image %s", token, exc_info=True)

    logger.info("Encrypted CDN: downloaded %d/%d images for job %s", len(result), len(available), job_id)
    return result


def _save_captured_images(
    captured: dict[str, bytes],
    markdown: str,
    job_id: str,
    article_index: int,
) -> tuple[str, int, int]:
    """Replace CDN image URLs with locally stored versions for captured images.

    `captured` maps image token -> raw image bytes.
    Returns (updated_markdown, saved_count, total_count).
    """
    matches = _IMG_RE.findall(markdown)
    if not matches:
        return markdown, 0, 0

    img_dir = IMAGE_DIR / job_id
    img_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    for alt_text, cdn_url in matches:
        token_match = re.search(r"/cover/([^/]+)/", cdn_url)
        if not token_match:
            continue
        token = token_match.group(1)

        if token in captured and len(captured[token]) > 500:
            data = captured[token]
            ext = _detect_ext(data)
            filename = f"{token}.{ext}"
            (img_dir / filename).write_bytes(data)
            local_url = f"/api/omni/knowledge/harvester/images/{job_id}/{filename}"
            markdown = markdown.replace(cdn_url, local_url)
            saved += 1

    logger.info("Article [%d] images: %d/%d saved", article_index, saved, len(matches))
    return markdown, saved, len(matches)


# ═══ Image Analysis via LLM ═══

_LOCAL_IMG_RE = re.compile(
    r"!\[([^\]]*)\]\((/api/omni/knowledge/harvester/images/[^)]+)\)"
)

AI_HUB_URL = "http://omni-ai-provider-hub:8001"
_IMAGE_ANALYSIS_PROMPT = (
    "请用中文详细描述这张图片的内容。"
    "如果是产品界面截图，请描述界面上的关键元素、按钮、数据和操作流程。"
    "如果包含图表或数据，请提取关键数字和趋势。"
    "如果是流程图或架构图，请描述节点和连线关系。"
    "输出纯文本描述，不超过300字。"
)


def list_job_images(job_id: str) -> list[dict]:
    """Return list of image info dicts for a job (from disk)."""
    img_dir = IMAGE_DIR / job_id
    if not img_dir.exists():
        return []
    images = []
    for f in sorted(img_dir.iterdir()):
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            images.append({
                "filename": f.name,
                "token": f.stem,
                "size": f.stat().st_size,
                "url": f"/api/omni/knowledge/harvester/images/{job_id}/{f.name}",
            })
    return images


def get_chapter_images(job_id: str, chapter_index: int) -> list[dict]:
    """Extract image references from a chapter's markdown."""
    job = _jobs.get(job_id)
    if not job:
        return []
    chapter = next((c for c in job["chapters"] if c["index"] == chapter_index), None)
    if not chapter:
        return []
    md = chapter.get("markdown", "")
    images = []
    for alt, url in _LOCAL_IMG_RE.findall(md):
        filename = url.rsplit("/", 1)[-1]
        filepath = IMAGE_DIR / job_id / filename
        images.append({
            "filename": filename,
            "token": Path(filename).stem,
            "alt": alt,
            "url": url,
            "exists": filepath.exists(),
            "size": filepath.stat().st_size if filepath.exists() else 0,
        })
    return images


async def analyze_images(
    job_id: str,
    filenames: list[str],
    prompt: str = "",
) -> list[dict]:
    """Send images to AI hub for analysis, return descriptions."""
    import base64

    img_dir = IMAGE_DIR / job_id
    default_prompt = (
        "请用中文详细描述这张图片的内容。"
        "如果是产品界面截图，请描述界面上的关键元素、按钮、数据和操作流程。"
        "如果包含图表或数据，请提取关键数字和趋势。"
        "输出纯文本描述，不超过300字。"
    )
    analysis_prompt = prompt or default_prompt
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for fname in filenames:
            filepath = img_dir / Path(fname).name
            if not filepath.exists():
                results.append({"filename": fname, "error": "not_found"})
                continue

            data = filepath.read_bytes()
            ext = filepath.suffix.lower().lstrip(".")
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
            b64 = base64.b64encode(data).decode()
            data_uri = f"data:{mime};base64,{b64}"

            try:
                resp = await client.post(
                    f"{AI_HUB_URL}/api/v1/ai/chat",
                    json={
                        "messages": [
                            {"role": "user", "content": [
                                {"type": "text", "text": analysis_prompt},
                                {"type": "image_url", "image_url": {"url": data_uri}},
                            ]},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1024,
                    },
                )
                if resp.status_code == 200:
                    body = resp.json()
                    raw_description = body.get("content", "") or body.get("data", {}).get("content", "")
                    description = validate_image_description(raw_description)
                    if description:
                        results.append({"filename": fname, "description": description})
                        logger.info("Analyzed image %s: %d chars", fname, len(description))
                    else:
                        results.append({"filename": fname, "error": "invalid_ai_response", "raw": (raw_description or "")[:200]})
                        logger.warning("Image %s: AI response rejected: %.100s", fname, raw_description)
                else:
                    results.append({"filename": fname, "error": f"ai_hub_{resp.status_code}"})
                    logger.warning("AI hub returned %d for image %s", resp.status_code, fname)
            except Exception as e:
                results.append({"filename": fname, "error": str(e)})
                logger.warning("Image analysis failed for %s: %s", fname, e)

    return results


def merge_image_descriptions(
    job_id: str,
    chapter_index: int,
    descriptions: dict[str, str],
) -> dict | None:
    """Merge image descriptions into chapter markdown, return updated chapter."""
    job = _jobs.get(job_id)
    if not job:
        return None
    chapter = next((c for c in job["chapters"] if c["index"] == chapter_index), None)
    if not chapter:
        return None

    md = chapter.get("markdown", "")
    for match in _LOCAL_IMG_RE.finditer(md):
        alt, url = match.group(1), match.group(2)
        filename = url.rsplit("/", 1)[-1]
        raw_desc = descriptions.get(filename)
        desc = validate_image_description(raw_desc) if raw_desc else None
        if desc:
            original = match.group(0)
            replacement = f"{original}\n\n> **图片解读**: {desc}\n"
            md = md.replace(original, replacement, 1)

    chapter["markdown"] = md
    chapter["text"] = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", md)
    chapter["word_count"] = len(chapter["text"])
    chapter["image_descriptions"] = descriptions
    return chapter


async def _auto_analyze_and_merge(
    job_id: str,
    markdown: str,
    ai_hub_url: str,
) -> tuple[str, int]:
    """Analyze all saved local images in markdown via LLM and merge descriptions."""
    import base64

    matches = list(_LOCAL_IMG_RE.finditer(markdown))
    if not matches:
        return markdown, 0

    img_dir = IMAGE_DIR / job_id
    analyzed = 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        for match in matches:
            alt, url = match.group(1), match.group(2)
            filename = url.rsplit("/", 1)[-1]
            filepath = img_dir / filename
            if not filepath.exists():
                continue

            data = filepath.read_bytes()
            ext = filepath.suffix.lower().lstrip(".")
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
            b64 = base64.b64encode(data).decode()
            data_uri = f"data:{mime};base64,{b64}"

            try:
                resp = await client.post(
                    f"{ai_hub_url}/api/v1/ai/chat",
                    json={
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": _IMAGE_ANALYSIS_PROMPT},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ]}],
                        "temperature": 0.3,
                        "max_tokens": 1024,
                    },
                )
                if resp.status_code == 200:
                    body = resp.json()
                    raw_desc = body.get("content", "") or body.get("data", {}).get("content", "")
                    desc = validate_image_description(raw_desc)
                    if desc:
                        original = match.group(0)
                        replacement = f"{original}\n\n> **[图片内容]** {desc}\n"
                        markdown = markdown.replace(original, replacement, 1)
                        analyzed += 1
                        logger.info("Auto-analyzed image %s: %d chars", filename, len(desc))
                    else:
                        logger.warning("Image %s: AI response rejected (mock/invalid): %.100s", filename, raw_desc)
            except Exception as e:
                logger.warning("Auto image analysis failed for %s: %s", filename, e)

    return markdown, analyzed


def _is_feishu_url(url: str) -> bool:
    return any(d in url for d in ("larkoffice.com/docx/", "feishu.cn/docx/", "larksuite.com/docx/",
                                   "larkoffice.com/wiki/", "feishu.cn/wiki/", "larksuite.com/wiki/"))


async def _extract_feishu_direct(
    page,
    url: str,
    cdn_url_data: dict[str, dict],
    timeout_ms: int = 30000,
) -> dict | None:
    """Navigate to a Feishu/Lark doc URL and extract content via client_vars API."""
    merged_blocks: dict = {}

    async def _on_client_vars_response(response):
        if "/docx/pages/client_vars" not in response.url or response.status != 200:
            return
        try:
            body = await response.json()
            bmap = (body.get("data") or {}).get("block_map") or {}
            merged_blocks.update(bmap)
        except Exception:
            pass

    page.on("response", _on_client_vars_response)

    logger.info("Feishu direct: navigating to %s", url)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        page.remove_listener("response", _on_client_vars_response)
        logger.warning("Feishu navigation failed: %s", e)
        return None

    final_url = page.url
    if "login" in final_url.lower() or "passport" in final_url.lower():
        page.remove_listener("response", _on_client_vars_response)
        logger.warning("Redirected to login — auth cookies may be invalid")
        return None

    for attempt in range(10):
        await page.wait_for_timeout(2000)
        raw = await page.evaluate(FEISHU_GET_DATA_JS)
        if raw:
            try:
                cv = json.loads(raw)
                initial_bmap = (cv.get("data") or {}).get("block_map") or {}
                if initial_bmap:
                    merged_blocks.update(initial_bmap)
                    logger.info("Feishu initial clientVars: %d blocks", len(initial_bmap))
                    break
            except Exception:
                pass

    for _ in range(8):
        prev_count = len(merged_blocks)
        await page.wait_for_timeout(2000)
        if len(merged_blocks) == prev_count:
            break
        logger.debug("Feishu blocks still arriving: %d → %d", prev_count, len(merged_blocks))

    page.remove_listener("response", _on_client_vars_response)

    if not merged_blocks:
        logger.warning("Feishu direct: no block data obtained")
        return None

    doc = _parse_block_map(merged_blocks)
    if not doc or len(doc.get("text", "")) < 30:
        logger.warning("Feishu direct: parsed document too short (%d blocks)", len(merged_blocks))
        return None

    logger.info("Feishu direct: extracted %d chars from %d blocks", len(doc["text"]), len(merged_blocks))
    return doc


async def _download_images_via_browser(
    page,
    markdown: str,
    job_id: str,
    article_index: int = 0,
) -> tuple[str, int, int]:
    """Download images directly through the authenticated browser session."""
    matches = _IMG_RE.findall(markdown)
    if not matches:
        return markdown, 0, 0

    img_dir = IMAGE_DIR / job_id
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = 0

    for alt_text, cdn_url in matches:
        token_match = re.search(r"/cover/([^/?]+)", cdn_url)
        if not token_match:
            continue
        token = token_match.group(1)

        try:
            b64_data = await page.evaluate(
                """(url) => {
                return new Promise(async (resolve) => {
                    try {
                        const resp = await fetch(url, {credentials: 'include'});
                        if (!resp.ok) { resolve(null); return; }
                        const blob = await resp.blob();
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result.split(',')[1]);
                        reader.readAsDataURL(blob);
                    } catch(e) { resolve(null); }
                });
            }""",
                cdn_url,
            )
            if not b64_data:
                continue

            from base64 import b64decode
            data = b64decode(b64_data)
            if len(data) < 500:
                continue

            ext = _detect_ext(data)
            filename = f"{token}.{ext}"
            (img_dir / filename).write_bytes(data)
            local_url = f"/api/omni/knowledge/harvester/images/{job_id}/{filename}"
            markdown = markdown.replace(cdn_url, local_url)
            saved += 1
            logger.info("Browser-downloaded image %s (%d bytes)", filename, len(data))
        except Exception as e:
            logger.debug("Browser image download failed for %s: %s", token, e)

    logger.info("Article [%d] browser images: %d/%d saved", article_index, saved, len(matches))
    return markdown, saved, len(matches)


async def crawl_feishu_doc(
    url: str,
    auth_state_path: str | None = None,
    job_id: str | None = None,
) -> dict:
    """Crawl a single Feishu/Lark document by URL — extract text + images."""
    if job_id is None:
        job_id = str(uuid4())

    job: dict = {
        "status": "starting",
        "progress": 0,
        "total": 1,
        "chapters": [],
        "current_article": None,
        "graph_name": "飞书文档",
        "total_articles": 1,
        "error": None,
    }
    _jobs[job_id] = job

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        job.update({"status": "failed", "error": "Playwright not installed"})
        return job

    try:
        job["status"] = "extracting_browser"
        job["current_article"] = {"index": 0, "title": "正在提取飞书文档...", "graph_path": url}

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)

        ctx_kwargs: dict = {}
        if auth_state_path and Path(auth_state_path).exists():
            ctx_kwargs["storage_state"] = auth_state_path
        ctx = await browser.new_context(**ctx_kwargs)

        cdn_url_data: dict[str, dict] = {}
        page = await ctx.new_page()

        async def _on_cdn_response(response):
            if "cdn_url" not in response.url or response.status != 200:
                return
            try:
                body = await response.json()
                for item in body.get("data") or []:
                    token = item.get("file_token", "")
                    if token and item.get("url"):
                        cdn_url_data[token] = {
                            "url": item["url"],
                            "secret": item.get("secret", ""),
                            "nonce": item.get("nonce", ""),
                        }
            except Exception:
                pass

        page.on("response", _on_cdn_response)

        doc = await _extract_feishu_direct(page, url, cdn_url_data)

        page.remove_listener("response", _on_cdn_response)

        if doc:
            md = doc["markdown"]
            img_saved = img_total = img_analyzed = 0

            if _IMG_RE.search(md):
                md, img_saved, img_total = await _download_images_via_browser(
                    page, md, job_id, 0,
                )

                if img_saved == 0:
                    logger.info("Browser download got 0 images, trying CDN decrypt fallback")
                    tokens_in_doc = set()
                    for _, u in _IMG_RE.findall(md):
                        tm = re.search(r"/cover/([^/?]+)", u)
                        if tm:
                            tokens_in_doc.add(tm.group(1))
                    decrypted = await _download_encrypted_images(cdn_url_data, tokens_in_doc, job_id)
                    md, img_saved, img_total = _save_captured_images(decrypted, md, job_id, 0)

                if img_saved > 0:
                    from app.config import settings as _cfg
                    md, img_analyzed = await _auto_analyze_and_merge(job_id, md, _cfg.ai_provider_hub_url)

            # Replace any remaining unresolved CDN image URLs with placeholders
            md = clean_image_markdown(md)

            job["chapters"].append({
                "index": 0,
                "title": doc["title"],
                "graph_path": doc["title"],
                "markdown": md,
                "text": doc["text"],
                "word_count": len(doc["text"]),
                "block_count": doc["block_count"],
                "source_url": url,
                "images": {"downloaded": img_saved, "total": img_total, "analyzed": img_analyzed},
            })
            logger.info("Feishu doc crawled: %s — %d chars, %d/%d images, %d analyzed",
                        doc["title"], len(doc["text"]), img_saved, img_total, img_analyzed)
        else:
            final_url = page.url
            is_login = "login" in final_url.lower() or "passport" in final_url.lower()
            job["chapters"].append({
                "index": 0,
                "title": "提取失败",
                "graph_path": url,
                "markdown": "",
                "text": "",
                "word_count": 0,
                "error": "needs_auth" if is_login else "extraction_failed",
            })

        await page.close()
        await browser.close()
        await pw.stop()

        job.update({"status": "done", "progress": 1, "current_article": None})

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception("Feishu doc crawl failed")
        job.update({"status": "failed", "error": f"{type(e).__name__}: {e}\n{tb}", "current_article": None})

    return job


def _parse_single_article_url(url: str) -> dict | None:
    """Detect a Yuntu single-article URL and extract its mapping_id + params.

    Single-article URLs look like:
      https://yuntu.oceanengine.com/support/content/142334?graphId=610&mappingType=2&...
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    mapping_type = qs.get("mappingType", [""])[0]
    if mapping_type != "2":
        return None
    path_parts = parsed.path.rstrip("/").split("/")
    if len(path_parts) < 2:
        return None
    mapping_id = path_parts[-1]
    if not mapping_id.isdigit():
        return None
    return {
        "mapping_id": mapping_id,
        "graph_id": qs.get("graphId", [""])[0],
        "page_id": qs.get("pageId", [""])[0],
        "space_id": qs.get("spaceId", [""])[0],
    }


async def crawl_articles(
    url: str,
    auth_state_path: str | None = None,
    max_pages: int | None = None,
    job_id: str | None = None,
    selected_articles: list[dict] | None = None,
) -> dict:
    if job_id is None:
        job_id = str(uuid4())

    job = {
        "status": "fetching_tree",
        "progress": 0,
        "total": 0,
        "chapters": [],
        "current_article": None,
        "graph_name": "",
        "total_articles": 0,
        "error": None,
    }
    _jobs[job_id] = job

    try:
        single = _parse_single_article_url(url)
        if single:
            gid, pid, sid = single["graph_id"], single["page_id"], single["space_id"]
            articles = [{
                "title": f"文章 {single['mapping_id']}",
                "mapping_id": single["mapping_id"],
                "graph_path": f"文章 {single['mapping_id']}",
                "target_id": single["mapping_id"],
            }]
            job["graph_name"] = "单篇文章"
            job["total_articles"] = 1
            job["total"] = 1
            logger.info("Single-article URL detected: mapping_id=%s", single["mapping_id"])
        elif selected_articles:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            gid = qs.get("graphId", [""])[0]
            pid = qs.get("pageId", [""])[0]
            sid = qs.get("spaceId", [""])[0]
            articles = selected_articles
            job["graph_name"] = "选定文章"
            job["total_articles"] = len(articles)
            job["total"] = len(articles)
            logger.info("Crawling %d selected articles", len(articles))
        else:
            tree = await fetch_nav_tree(url)
            articles = tree["articles"]
            if max_pages:
                articles = articles[:max_pages]
            job["graph_name"] = tree["graph_name"]
            job["total_articles"] = tree["total_articles"]
            job["total"] = len(articles)
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            gid = qs.get("graphId", [""])[0]
            pid = qs.get("pageId", [""])[0]
            sid = qs.get("spaceId", [""])[0]

        has_auth = bool(auth_state_path) and Path(auth_state_path).exists()

        # Phase 1: Try SSR API extraction (no browser needed, fast)
        job["status"] = "extracting_api"
        api_extracted: set[int] = set()
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
            for idx, article in enumerate(articles):
                title = article["title"]
                mid = article["mapping_id"]
                job["progress"] = idx
                job["current_article"] = {
                    "index": idx, "title": title, "graph_path": article["graph_path"],
                }

                ssr = await _fetch_article_ssr(client, mid, gid, pid, sid)
                if ssr:
                    content = ssr.get("content") or ""
                    content_type = ssr.get("contentType", "")

                    if content.strip() and content_type not in ("feishu_docx_new_import",):
                        content = clean_ssr_content(content)
                        if content.strip():
                            job["chapters"].append({
                                "index": idx,
                                "title": title,
                                "graph_path": article["graph_path"],
                                "markdown": content,
                                "text": content,
                                "word_count": len(content),
                                "block_count": 1,
                                "source_url": f"https://yuntu.oceanengine.com/support/content/{mid}",
                            })
                            api_extracted.add(idx)
                            logger.info("Harvester API [%d/%d] %s — %d chars", idx + 1, len(articles), title, len(content))
                            continue

                # Not extracted via API — mark as pending for browser or needs_auth
                job["chapters"].append({
                    "index": idx,
                    "title": title,
                    "graph_path": article["graph_path"],
                    "markdown": "",
                    "text": "",
                    "word_count": 0,
                    "error": "needs_auth" if not has_auth else "pending_browser",
                })
                logger.info("Harvester [%d/%d] %s — %s", idx + 1, len(articles), title,
                            "needs auth" if not has_auth else "queued for browser")

        # Phase 2: If auth is available and there are unextracted articles, use browser
        browser_queue = [ch for ch in job["chapters"] if ch.get("error") == "pending_browser"]
        if browser_queue and has_auth:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                job.update({"status": "done", "progress": len(articles), "current_article": None})
                return job

            job["status"] = "extracting_browser"
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(storage_state=auth_state_path)
            page = await ctx.new_page()

            # Dict collecting encrypted CDN info from /space/api/box/file/cdn_url/
            cdn_url_data: dict[str, dict] = {}

            async def _on_cdn_url_response(response):
                """Capture feishu cdn_url API responses (url + AES-GCM keys)."""
                if "cdn_url" not in response.url or response.status != 200:
                    return
                try:
                    body = await response.json()
                    for item in body.get("data") or []:
                        token = item.get("file_token", "")
                        if token and item.get("url"):
                            cdn_url_data[token] = {
                                "url": item["url"],
                                "secret": item.get("secret", ""),
                                "nonce": item.get("nonce", ""),
                            }
                except Exception:
                    pass

            page.on("response", _on_cdn_url_response)

            # Remove pending_browser chapters; they'll be re-extracted
            job["chapters"] = [ch for ch in job["chapters"] if ch.get("error") != "pending_browser"]

            for idx, article in enumerate(articles):
                if idx in api_extracted:
                    continue

                title = article["title"]
                mid = article["mapping_id"]
                job["progress"] = idx
                job["current_article"] = {
                    "index": idx, "title": title, "graph_path": article["graph_path"],
                }

                article_url = (
                    f"https://yuntu.oceanengine.com/support/content/{mid}"
                    f"?graphId={gid}&pageId={pid}&spaceId={sid}"
                )

                doc = None
                for attempt in range(2):
                    doc = await _extract_feishu_via_browser(
                        page, article_url, cdn_url_data,
                    )
                    if doc:
                        break
                    await page.wait_for_timeout(2000)

                if doc:
                    md = doc["markdown"]
                    img_saved = 0
                    img_total = 0

                    if _IMG_RE.search(md):
                        tokens_in_article = set()
                        for _, u in _IMG_RE.findall(md):
                            tm = re.search(r"/cover/([^/?]+)", u)
                            if tm:
                                tokens_in_article.add(tm.group(1))

                        decrypted = await _download_encrypted_images(
                            cdn_url_data, tokens_in_article, job_id,
                        )
                        md, img_saved, img_total = _save_captured_images(
                            decrypted, md, job_id, idx,
                        )

                        # Fallback: download remaining images via browser session
                        if _IMG_RE.search(md):
                            md, extra_saved, extra_total = await _download_images_via_browser(
                                page, md, job_id, idx,
                            )
                            img_saved += extra_saved

                    img_analyzed = 0
                    if img_saved > 0:
                        from app.config import settings as _cfg
                        md, img_analyzed = await _auto_analyze_and_merge(job_id, md, _cfg.ai_provider_hub_url)

                    # Replace any remaining unresolved CDN image URLs with placeholders
                    md = clean_image_markdown(md)

                    job["chapters"].append({
                        "index": idx,
                        "title": title,
                        "graph_path": article["graph_path"],
                        "markdown": md,
                        "text": doc["text"],
                        "word_count": len(doc["text"]),
                        "block_count": doc["block_count"],
                        "source_url": article_url,
                        "images": {"downloaded": img_saved, "total": img_total, "analyzed": img_analyzed},
                    })
                else:
                    job["chapters"].append({
                        "index": idx,
                        "title": title,
                        "graph_path": article["graph_path"],
                        "markdown": "",
                        "text": "",
                        "word_count": 0,
                        "error": "extraction_failed",
                    })

                logger.info(
                    "Harvester Browser [%d/%d] %s — %d chars, images %d/%d",
                    idx + 1, len(articles), title,
                    job["chapters"][-1]["word_count"],
                    job["chapters"][-1].get("images", {}).get("downloaded", 0),
                    job["chapters"][-1].get("images", {}).get("total", 0),
                )

            page.remove_listener("response", _on_cdn_url_response)
            await browser.close()
            await pw.stop()

        # Sort chapters by index for consistent order
        job["chapters"].sort(key=lambda c: c["index"])

        job.update({
            "status": "done",
            "progress": len(articles),
            "current_article": None,
        })

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception("Harvester crawl failed")
        job.update({"status": "failed", "error": f"{type(e).__name__}: {e}\n{tb}", "current_article": None})

    return job
