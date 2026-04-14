"""Knowledge Harvester — crawl help-center pages and extract structured content.

Uses Playwright for authenticated browser automation and extracts full document
content from Feishu iframe embeds via window.DATA.clientVars block parsing.
"""

from __future__ import annotations

import asyncio
import hashlib
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

# True = 只输出正文与表格单元格内文字；不输出图片/白板/音视频/附件等块，且爬取管线不下载图、不做 AI 图解读与短视频分析。
# 恢复完整能力时改为 False。
_HARVESTER_TEXT_AND_TABLES_ONLY = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}

# Ocean help-center SSR (yuntu vs support host — directory completeness differs).
_SSR_LOADER_QS = (
    "__loader=%28prefix%29%2Fcontent%2F%28id%24%29%2Fpage"
    "&__ssrDirect=true"
)

_SUPPORT_CONTENT = "https://support.oceanengine.com/support/content"
_YUNTU_CONTENT = "https://yuntu.oceanengine.com/support/content"

# Blocking images/fonts/svg breaks Feishu/Lark loaders; only skip heavy video.
_HARVESTER_ROUTE_ABORT_RE = re.compile(
    r"\.(mp4|webm|mov|m4v)(\?|$)", re.IGNORECASE,
)


def _looks_like_video_url(url: str) -> bool:
    """Heuristic: Douyin / TikTok / direct media / m3u8 / file-extension URLs."""
    if not url or not isinstance(url, str):
        return False
    if _HARVESTER_ROUTE_ABORT_RE.search(url):
        return True
    u = url.lower()
    if ".m3u8" in u:
        return True
    if re.search(r"\.(mp4|webm|mov|m4v)(\?|#|&|$)", u):
        return True
    if any(h in u for h in ("douyin.com", "iesdouyin.com", "tiktok.com", "youtu.be", "youtube.com")):
        return True
    if "tiktokcdn.com" in u or "tiktokv.com" in u:
        return True
    if "snssdk.com" in u and ("aweme" in u or "video" in u):
        return True
    if ("bytecdn" in u or "pstatp.com" in u) and any(k in u for k in ("video", "vod", "play", "aweme")):
        return True
    return False


def _ordered_video_urls_from_markdown(markdown: str, max_videos: int = 50) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    # Match both http(s):// and feishu:// video URLs
    for m in re.finditer(r"\[([^\]]*)\]\(((?:https?|feishu)://[^)\s]+)\)", markdown):
        url = m.group(2)
        if url in seen:
            continue
        # Accept feishu:// video links directly, or http(s) links that look like video
        is_feishu_video = url.startswith("feishu://") and any(
            k in url for k in ("media/", "file_token/")
        )
        if not is_feishu_video and not _looks_like_video_url(url):
            continue
        seen.add(url)
        ordered.append(url)
        if len(ordered) >= max_videos:
            break
    return ordered


_CHROMIUM_HEADLESS_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
)

# ═══ Job Store (in-memory, personal-use) ═══

_jobs: dict[str, dict] = {}
_login_sessions: dict[str, dict] = {}
_last_upload_job_id: str | None = None


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def request_cancel_harvest(job_id: str) -> dict | None:
    """Ask a running crawl to stop soon; finished jobs are unchanged.

    The worker checks ``cancel_requested`` between articles (API phase and browser phase).
    Partial ``chapters`` are kept for review / save.
    """
    job = _jobs.get(job_id)
    if not job:
        return None
    if job.get("status") in ("done", "failed"):
        return job
    job["cancel_requested"] = True
    _job_log(job, "已请求结束任务：将在当前篇完成后停止，并保留已采集章节…")
    return job


def get_last_upload_job_id() -> str | None:
    return _last_upload_job_id


def get_login_session(session_id: str) -> dict | None:
    return _login_sessions.get(session_id)


_ACTIVITY_LOG_MAX = 500


def _job_log(job: dict | None, message: str, snippet: str | None = None) -> None:
    """Append a human-readable line for the harvester UI (polled via GET /jobs/{id})."""
    if not job:
        return
    log = job.setdefault("activity_log", [])
    entry: dict = {"t": time.time(), "msg": message}
    if snippet:
        entry["snippet"] = snippet[:2000]
    log.append(entry)
    over = len(log) - _ACTIVITY_LOG_MAX
    if over > 0:
        del log[0:over]


_TEXT_PREVIEW_MAX = 4000


def _job_set_text_preview(job: dict | None, plain: str) -> None:
    """Latest extracted plain text snippet for live UI preview."""
    if not job:
        return
    s = (plain or "").strip().replace("\r\n", "\n")
    if not s:
        return
    job["text_preview"] = s[:_TEXT_PREVIEW_MAX] + ("…" if len(s) > _TEXT_PREVIEW_MAX else "")


def _job_publish_body_before_media(job: dict | None, markdown: str) -> None:
    """Push plain text to the UI as soon as block→markdown exists (before images/videos)."""
    if not job or not (markdown or "").strip():
        return
    plain = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown).strip()
    if not plain:
        return
    _job_set_text_preview(job, plain)
    _job_log(
        job,
        f"正文已提取（约 {len(plain)} 字），随后下载图片 / AI 解读…",
        snippet=plain[:900],
    )


def _job_touch(job: dict | None, detail: str, hint: float | None = None) -> None:
    """Refresh in-memory job for UI polling (subtitle + fractional progress within current article)."""
    if not job:
        return
    _job_log(job, detail)
    ca = job.get("current_article")
    if isinstance(ca, dict):
        ca["detail"] = detail
    if hint is not None:
        job["progress_hint"] = max(0.0, min(0.99, float(hint)))


# ═══ Browser Login ═══

_LOGIN_PROFILES: dict[str, dict] = {
    "oceanengine": {
        "session_keys": ("session", "sid_tt", "sid_guard", "uid_tt"),
        "cookie_domains": ("oceanengine", "bytedance", "toutiao"),
    },
    "feishu": {
        "session_keys": ("session", "sid", "session_list", "lark_oapi"),
        "cookie_domains": ("feishu", "larkoffice", "larksuite", "bytedance"),
    },
}


async def start_browser_login(
    target_url: str,
    auth_state_path: str,
    session_id: str | None = None,
    login_type: str = "oceanengine",
) -> dict:
    """Launch a visible browser for the user to log in, then capture cookies.

    The browser opens on the local desktop.  The function polls for session
    cookies and automatically saves them once the user has logged in.
    ``login_type`` selects which cookie names / domains to look for.
    """
    if session_id is None:
        session_id = str(uuid4())

    profile = _LOGIN_PROFILES.get(login_type, _LOGIN_PROFILES["oceanengine"])

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
                    if any(k in c["name"].lower() for k in profile["session_keys"])
                ]
                if session_cookies and "login" not in current_url.lower():
                    session["status"] = "saving"
                    target_cookies = [
                        c for c in cookies
                        if any(d in c.get("domain", "") for d in profile["cookie_domains"])
                    ]
                    if not target_cookies:
                        target_cookies = cookies

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
                    logger.info("Browser login [%s]: saved %d cookies to %s", login_type, len(pw_cookies), p)

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

# Collect Lark/Feishu block ids in DOM tree order (matches on-screen reading order when present).
BLOCK_ID_DOM_ORDER_JS = """(knownIds) => {
    if (!document.body) return [];
    const known = new Set(knownIds.map(String));
    const out = [];
    const seen = new Set();
    const attrs = ['data-record-id', 'data-block-id', 'data-blockid'];
    try {
        document.body.querySelectorAll('*').forEach((el) => {
            for (const a of attrs) {
                const v = el.getAttribute(a);
                if (v && known.has(v) && !seen.has(v)) {
                    out.push(v);
                    seen.add(v);
                    break;
                }
            }
        });
    } catch (e) {}
    return out;
}"""


def _dump_block_map(bmap: dict, job_id: str, label: str = "blocks") -> None:
    """Dump raw block_map to JSON file for debugging (written alongside images)."""
    try:
        dump_dir = IMAGE_DIR / job_id
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_path = dump_dir / f"_debug_{label}.json"
        dump_path.write_text(json.dumps(bmap, ensure_ascii=False, indent=1), encoding="utf-8")
        logger.info("Block dump: %d blocks written to %s", len(bmap), dump_path)
    except Exception as e:
        logger.debug("Block dump failed: %s", e)


def _extract_elements_text(elements: list) -> str:
    """Extract text from a Lark Docx elements list (text_run / mention / equation)."""
    if not isinstance(elements, list) or not elements:
        return ""
    parts: list[str] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        # text_run.content — most common
        tr = el.get("text_run") or {}
        if isinstance(tr, dict) and tr.get("content"):
            parts.append(str(tr["content"]))
            continue
        # mention elements
        for mkey in ("mention_user", "mention_doc", "mention"):
            m = el.get(mkey)
            if isinstance(m, dict):
                mt = m.get("text") or m.get("name") or ""
                if mt:
                    parts.append(str(mt))
                    break
        else:
            # equation
            eq = el.get("equation") or {}
            if isinstance(eq, dict) and eq.get("content"):
                parts.append(str(eq["content"]))
                continue
            # generic element fallback
            for k in ("content", "text", "value"):
                v = el.get(k)
                if isinstance(v, str) and v.strip():
                    parts.append(v)
                    break
    return "".join(parts)


def _get_text(bd: dict) -> str:
    """Extract plain text from a Feishu block data dict.

    Tries every known storage layout in priority order, then falls back to a
    deep recursive search through the entire block data dict.
    """
    def _seg_key(k: str) -> tuple[int, str]:
        return (int(k), "") if str(k).isdigit() else (10**9, str(k))

    def _dict_to_text(d: dict) -> str:
        ordered = sorted(d.items(), key=lambda kv: _seg_key(str(kv[0])))
        return "".join(str(v) for _, v in ordered if v)

    t = bd.get("text", {})
    if isinstance(t, dict):
        # ── Path 1: initialAttributedTexts.text (classic Feishu) ──
        iat = t.get("initialAttributedTexts", {})
        texts = iat.get("text", {})
        if texts and isinstance(texts, dict):
            result = _dict_to_text(texts)
            if result:
                return result
        if isinstance(texts, str) and texts:
            return texts

        # ── Path 2: initialAttributedTexts.aPool (attributed segments) ──
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

        # ── Path 3: text.elements[] (Lark Docx SPA element format) ──
        el_text = _extract_elements_text(t.get("elements", []))
        if el_text:
            return el_text

        # ── Path 4: text.text dict (Lark Docx SPA no-IAT wrapper) ──
        direct = t.get("text", {})
        if direct and isinstance(direct, dict):
            result = _dict_to_text(direct)
            if result:
                return result

        # ── Path 5: text is a plain string ──
        if isinstance(t, str) and t.strip():
            return t.strip()

    # If bd["text"] is a plain string
    if isinstance(t, str) and t.strip():
        return t.strip()

    # ── Path 6: elements[] at top level of block data ──
    el_text = _extract_elements_text(bd.get("elements", []))
    if el_text:
        return el_text

    # ── Path 7: snippet.text (code blocks) ──
    snippet = bd.get("snippet", {})
    if isinstance(snippet, dict):
        s_text = snippet.get("text", "")
        if s_text:
            return str(s_text)

    # ── Path 8: direct content/textContent fields ──
    for key in ("content", "textContent", "text_content"):
        val = bd.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # ── Path 9: body.text / body.content ──
    body = bd.get("body", {})
    if isinstance(body, dict):
        body_text = body.get("text") or body.get("content") or ""
        if isinstance(body_text, str) and body_text.strip():
            return body_text.strip()

    # ── Path 10: preview_text / display_text ──
    for key in ("preview_text", "display_text"):
        pv = bd.get(key)
        if isinstance(pv, str) and pv.strip():
            return pv.strip()

    # ── Path 11: Deep recursive search — last resort ──
    # Walk the entire block data looking for string values that might be text
    def _deep_find_text(obj, depth: int = 0) -> str:
        if depth > 6:
            return ""
        if isinstance(obj, str):
            s = obj.strip()
            # Filter out tokens, URLs, UUIDs and other non-text values
            if (len(s) > 2 and not s.startswith(("http", "feishu://", "data:"))
                    and "/" not in s[:20] and not all(c in "0123456789abcdef-" for c in s.lower())):
                return s
        if isinstance(obj, dict):
            # Prioritize known text keys
            for k in ("content", "text", "value", "insert", "display_text", "preview_text"):
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    s = v.strip()
                    if (len(s) > 2 and not s.startswith(("http", "feishu://", "data:"))
                            and "/" not in s[:20]):
                        return s
            # Then try elements list
            els = obj.get("elements") or obj.get("aPool") or []
            if isinstance(els, list) and els:
                result = _extract_elements_text(els) if any(isinstance(e, dict) and "text_run" in e for e in els) else ""
                if result:
                    return result
            # Recurse into nested dicts
            for k, v in obj.items():
                if k in ("children", "image", "media", "file", "property", "style",
                         "block_id", "parent_id", "type"):
                    continue
                found = _deep_find_text(v, depth + 1)
                if found:
                    return found
        if isinstance(obj, list):
            for item in obj:
                found = _deep_find_text(item, depth + 1)
                if found:
                    return found
        return ""

    deep = _deep_find_text(bd)
    if deep:
        return deep

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


def _merge_client_vars_sequence(acc: list[str], seq: list | None) -> None:
    """Update accumulated block_sequence from a /client_vars response.

    Feishu often returns a *full* ``block_sequence`` on later responses (after
    lazy-load / scroll).  Appending only unseen IDs keeps the *first* response's
    order and breaks visual document order.  Prefer the longest sequence seen,
    and when length ties, take the latest response (replace).
    """
    if not isinstance(seq, list) or not seq:
        return
    bids = [str(b) for b in seq if b is not None and str(b) != ""]
    if not bids:
        return
    if len(bids) >= len(acc):
        acc.clear()
        acc.extend(bids)


def _merge_dom_sequence_first(acc: list[str], dom_seq: list, n_blocks: int) -> None:
    """Prefer DOM order for blocks that appear in the rendered tree, then append the rest in API order."""
    if not dom_seq or n_blocks < 2:
        return
    dom_clean = [str(x) for x in dom_seq if x is not None and str(x)]
    if len(dom_clean) < 8 and len(dom_clean) < max(12, int(0.15 * n_blocks)):
        return
    dom_set = set(dom_clean)
    tail = [str(x) for x in acc if str(x) not in dom_set]
    merged = list(dict.fromkeys(dom_clean))
    for x in tail:
        if x not in merged:
            merged.append(x)
    acc.clear()
    acc.extend(merged)


async def _refresh_sequence_from_window_data(context, acc: list[str]) -> None:
    """Re-read window.DATA.clientVars.block_sequence after scroll (authoritative when present)."""
    try:
        raw = await context.evaluate(FEISHU_GET_DATA_JS)
        if not raw:
            return
        cv = json.loads(raw)
        d0 = cv.get("data") or {}
        _merge_client_vars_sequence(acc, d0.get("block_sequence"))
    except Exception:
        pass


async def _apply_dom_block_order(context, acc: list[str], bmap: dict) -> None:
    """Reorder acc using block ids as they appear in the live DOM."""
    if not bmap or len(bmap) < 2:
        return
    try:
        known = [str(k) for k in bmap.keys() if k and not str(k).startswith("__")]
        dom_seq = await context.evaluate(BLOCK_ID_DOM_ORDER_JS, known)
        if isinstance(dom_seq, list):
            _merge_dom_sequence_first(acc, dom_seq, len(bmap))
    except Exception:
        pass


def _seq_pos_from_sequence(sequence: list | None) -> dict[str, int] | None:
    """Map block_id → position from API block_sequence (document visual order)."""
    if not sequence:
        return None
    pos: dict[str, int] = {}
    for i, bid in enumerate(sequence):
        s = str(bid)
        if s not in pos:
            pos[s] = i
    return pos or None


def _order_sibling_ids(raw: list | None, seq_pos: dict[str, int] | None) -> list:
    """Reorder sibling block IDs to match block_sequence; unknown ids keep stable tail order."""
    ids = list(raw or [])
    if not seq_pos or len(ids) < 2:
        return ids
    return sorted(ids, key=lambda c: seq_pos.get(str(c), 10**9))


def _cell_to_text(
    bmap: dict,
    cell_children: list,
    seq_pos: dict[str, int] | None = None,
) -> str:
    """Render table cell children as compact multi-line text for table cells.

    Unlike _blocks_to_md which outputs one-item-per-line, this joins
    nested content with <br> to preserve structure inside markdown tables.
    """
    parts: list[str] = []
    for cid in _order_sibling_ids(cell_children, seq_pos):
        block = bmap.get(cid, {})
        bd = block.get("data", {})
        btype = bd.get("type", "unknown")
        text = _get_text(bd)
        children = _order_sibling_ids(bd.get("children", []) or [], seq_pos)

        if btype == "text":
            if text.strip():
                parts.append(text.strip())
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype.startswith("heading"):
            if text.strip():
                parts.append(f"**{text.strip()}**")
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype in ("ordered", "bullet"):
            if children:
                for i, sub_id in enumerate(children, 1):
                    sb = bmap.get(sub_id, {}).get("data", {})
                    st = _get_text(sb)
                    prefix = f"{i}." if btype == "ordered" else "•"
                    if st.strip():
                        parts.append(f"{prefix} {st.strip()}")
                    sub_ch = _order_sibling_ids(sb.get("children", []) or [], seq_pos)
                    if sub_ch:
                        nested = _cell_to_text(bmap, sub_ch, seq_pos)
                        if nested:
                            parts.append(f"  {nested}")
            elif text.strip():
                prefix = "1." if btype == "ordered" else "•"
                parts.append(f"{prefix} {text.strip()}")
        elif btype == "image":
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                img = _get_image_info(bd)
                if img:
                    parts.append(f"![{img['name']}]({img['cdn_url']})")
            # _HARVESTER_TEXT_AND_TABLES_ONLY：表格内不插入图片 Markdown
        elif btype in ("callout", "quote_container"):
            if text.strip():
                parts.append(text.strip())
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype == "todo":
            mark = "✓" if bd.get("checked") else "☐"
            if text.strip():
                parts.append(f"{mark} {text.strip()}")
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype == "code_block":
            if text.strip():
                parts.append(f"`{text.strip()}`")
            if children:
                for sub_id in _order_sibling_ids(children, seq_pos):
                    ct = _get_text(bmap.get(sub_id, {}).get("data", {}))
                    if ct.strip():
                        parts.append(f"`{ct.strip()}`")
        elif btype == "embed":
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                embed_url = bd.get("url", "") or bd.get("embedUrl", "")
                if embed_url and _looks_like_video_url(embed_url):
                    parts.append(f"[视频]({embed_url})")
                elif embed_url:
                    parts.append(f"[嵌入]({embed_url})")
            elif text.strip():
                parts.append(text.strip())
        elif btype in ("media", "lark_media", "video", "lark_video", "audio", "lark_audio"):
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                minfo = bd.get("media") or bd.get("file") or bd.get("video") or {}
                if isinstance(minfo, dict):
                    fname = minfo.get("name") or text or "媒体文件"
                    furl = (minfo.get("url") or minfo.get("tmp_url")
                            or minfo.get("file_url") or minfo.get("download_url") or "")
                    token = minfo.get("file_token") or minfo.get("token") or ""
                    if furl:
                        parts.append(f"[视频: {fname}]({furl})")
                    elif token:
                        parts.append(f"[视频: {fname}](feishu://media/{token})")
                    elif fname and fname != "媒体文件":
                        parts.append(f"[视频: {fname}]")
                elif text.strip():
                    parts.append(f"[视频: {text}]")
            elif text.strip():
                parts.append(text.strip())
        elif btype == "file":
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                import html as _html
                finfo = bd.get("file", {})
                if isinstance(finfo, dict):
                    mime = str(finfo.get("mimeType", "") or finfo.get("type", "") or "")
                    fname_raw = finfo.get("name", "") or text
                    fname = _html.unescape(fname_raw) if fname_raw else ""
                    token = str(finfo.get("token", "") or "")
                    furl = finfo.get("url") or finfo.get("downloadUrl") or finfo.get("link", "")
                    if not furl and "video" in mime.lower() and fname and "/" in fname and _looks_like_video_url(fname):
                        furl = fname if fname.startswith(("http://", "https://")) else "https://" + fname
                    if "video" in mime.lower() and furl:
                        parts.append(f"[视频]({furl})")
                    elif "video" in mime.lower() and token:
                        parts.append(f"[视频: {fname}](feishu://file_token/{token})")
                    elif "video" in mime.lower():
                        parts.append(f"[视频文件: {fname}]")
                    elif furl:
                        parts.append(f"[文件]({furl})")
                    elif fname:
                        parts.append(f"[文件: {fname}]")
                else:
                    parts.append(f"[文件: {text}]")
            elif text.strip():
                parts.append(text.strip())
        elif btype in ("toggle_list", "toggle_heading", "toggle_heading1",
                        "toggle_heading2", "toggle_heading3", "toggle_heading4"):
            if text.strip():
                parts.append(f"**{text.strip()}**")
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype in ("equation", "math_equation", "math_block"):
            eq = bd.get("equation", "") or bd.get("formula", "") or text
            if eq.strip():
                parts.append(f"${eq.strip()}$")
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype in ("divider", "horizontal_rule", "thematic_break"):
            parts.append("---")
        elif btype in ("quote", "quote_container"):
            if text.strip():
                parts.append(text.strip())
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype in ("synced_block", "synced_source", "grid", "grid_column",
                        "column_list", "column", "gallery", "image_group",
                        "view", "view_block", "wiki_catalog", "catalog"):
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
            elif text.strip():
                parts.append(text.strip())
        elif btype in ("bookmark", "link_preview", "url_preview"):
            link = bd.get("link", {}) or bd.get("url", "")
            url = link.get("url", "") if isinstance(link, dict) else str(link) if link else ""
            if url:
                parts.append(f"[{text.strip() or url}]({url})")
            elif text.strip():
                parts.append(text.strip())
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype in ("task", "task_list"):
            mark = "✓" if bd.get("done") or bd.get("checked") else "☐"
            if text.strip():
                parts.append(f"{mark} {text.strip()}")
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        elif btype in ("mention", "mention_doc", "mention_user", "reminder",
                        "chat_card", "jira", "jira_issue", "okr", "okr_block"):
            if text.strip():
                parts.append(text.strip())
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
        else:
            # Catch-all: always extract text AND children
            if text.strip():
                parts.append(text.strip())
            if children:
                nested = _cell_to_text(bmap, children, seq_pos)
                if nested:
                    parts.append(nested)
    return " <br> ".join(parts)


def _blocks_to_md(
    bmap: dict,
    block_ids: list,
    indent: str = "",
    seq_pos: dict[str, int] | None = None,
) -> list[str]:
    """Recursively convert Feishu block IDs into Markdown lines."""
    lines: list[str] = []
    for bid in _order_sibling_ids(block_ids, seq_pos):
        block = bmap.get(bid, {})
        bd = block.get("data", {})
        btype = bd.get("type", "unknown")
        text = _get_text(bd)
        children = _order_sibling_ids(bd.get("children", []) or [], seq_pos)

        if btype == "page":
            lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype.startswith("heading"):
            level = int(btype[-1]) if btype[-1].isdigit() else 1
            if text.strip():
                lines.append(f"{'#' * level} {text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype == "text":
            if text.strip():
                lines.append(f"{indent}{text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("ordered", "bullet"):
            if children:
                for i, cid in enumerate(children, 1):
                    cb = bmap.get(cid, {}).get("data", {})
                    ct = _get_text(cb)
                    sub = _order_sibling_ids(cb.get("children", []) or [], seq_pos)
                    prefix = f"{i}. " if btype == "ordered" else "- "
                    lines.append(f"{indent}{prefix}{ct}" if ct.strip() else f"{indent}{prefix}...")
                    if sub:
                        lines.extend(_blocks_to_md(bmap, sub, indent + "   ", seq_pos))
            elif text.strip():
                # Block itself is a list item (no children, text on self)
                prefix = "1. " if btype == "ordered" else "- "
                lines.append(f"{indent}{prefix}{text}")

        elif btype == "todo":
            mark = "x" if bd.get("checked") else " "
            lines.append(f"{indent}- [{mark}] {text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent + "   ", seq_pos))

        elif btype == "toggle_list":
            if text.strip():
                lines.append(f"{indent}<details><summary>{text}</summary>")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))
            if text.strip():
                lines.append(f"{indent}</details>")

        elif btype == "image":
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                img = _get_image_info(bd)
                if img:
                    lines.append(f"{indent}![{img['name']}]({img['cdn_url']})")

        elif btype == "whiteboard":
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                token = bd.get("token", "")
                if token:
                    lines.append(f"{indent}[画板: {token}]")

        elif btype == "table":
            prop = bd.get("property", {}) or {}
            rows_id = (bd.get("rows_id") or prop.get("rows_id")
                       or prop.get("row_ids") or bd.get("row_ids") or [])
            cols_id = (bd.get("columns_id") or prop.get("columns_id")
                       or prop.get("column_ids") or bd.get("column_ids") or [])
            cell_set = (bd.get("cell_set") or prop.get("cell_set")
                        or prop.get("cells") or bd.get("cells") or {})
            # Fallback: derive rows/cols from children if structured as table_row blocks
            if not rows_id and children:
                first_child = bmap.get(children[0], {}).get("data", {})
                if first_child.get("type") in ("table_row", "row"):
                    rows_id = children
                    # Derive columns from first row's children
                    first_row_ch = first_child.get("children", [])
                    if first_row_ch and not cols_id:
                        cols_id = [f"_col_{i}" for i in range(len(first_row_ch))]
            if not rows_id or not cols_id:
                if children:
                    lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))
            else:
                if seq_pos and len(rows_id) > 1:
                    rows_id = sorted(rows_id, key=lambda r: seq_pos.get(str(r), 10**9))
                for ri, row_id in enumerate(rows_id):
                    row_cells = []
                    for col_id in cols_id:
                        cell_info = (
                            cell_set.get(row_id + col_id)
                            or cell_set.get(f"{row_id}_{col_id}")
                            or cell_set.get(f"{row_id}:{col_id}")
                            or {}
                        )
                        cell_bid = cell_info.get("block_id", "")
                        if cell_bid:
                            cell_bd = bmap.get(cell_bid, {}).get("data", {})
                            cell_ch = cell_bd.get("children", [])
                            cell_text = _cell_to_text(bmap, cell_ch, seq_pos)
                            cell_text = cell_text.replace("|", "\\|")
                            row_cells.append(cell_text if cell_text.strip() else " ")
                        else:
                            row_cells.append(" ")
                    lines.append("| " + " | ".join(row_cells) + " |")
                    if ri == 0:
                        lines.append("|" + "|".join(" --- " for _ in cols_id) + "|")

        elif btype == "table_cell":
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("table_row",):
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("callout", "quote_container"):
            if text.strip():
                lines.append(f"{indent}> {text}")
            for sl in _blocks_to_md(bmap, children, indent, seq_pos):
                lines.append(f"{indent}> {sl}")

        elif btype == "code_block":
            lang = bd.get("language", "")
            lines.append(f"{indent}```{lang}")
            if text.strip():
                lines.append(text)
            if children:
                for cid in _order_sibling_ids(children, seq_pos):
                    ct = _get_text(bmap.get(cid, {}).get("data", {}))
                    if ct:
                        lines.append(ct)
            lines.append(f"{indent}```")

        elif btype in ("grid", "grid_column", "column_list", "column"):
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("synced_block", "synced_source"):
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype == "bookmark":
            link = bd.get("link", {})
            url = link.get("url", "") if isinstance(link, dict) else str(link) if link else ""
            if url:
                lines.append(f"{indent}[{text or url}]({url})")
            elif text.strip():
                lines.append(f"{indent}{text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype == "embed":
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                embed_url = bd.get("url", "") or bd.get("embedUrl", "")
                if embed_url and _looks_like_video_url(embed_url):
                    lines.append(f"{indent}[视频]({embed_url})")
                elif embed_url:
                    lines.append(f"{indent}[嵌入内容]({embed_url})")
                elif text.strip():
                    lines.append(f"{indent}{text}")
            elif text.strip():
                lines.append(f"{indent}{text}")

        elif btype in ("media", "lark_media", "video", "lark_video", "audio", "lark_audio"):
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                minfo = bd.get("media") or bd.get("file") or bd.get("video") or {}
                if isinstance(minfo, dict):
                    fname = minfo.get("name") or text or "媒体文件"
                    furl = (minfo.get("url") or minfo.get("tmp_url")
                            or minfo.get("file_url") or minfo.get("download_url") or "")
                    token = minfo.get("file_token") or minfo.get("token") or ""
                    if furl:
                        lines.append(f"{indent}[视频: {fname}]({furl})")
                    elif token:
                        lines.append(f"{indent}[视频: {fname}](feishu://media/{token})")
                    elif fname and fname != "媒体文件":
                        lines.append(f"{indent}[视频: {fname}]")
                elif text.strip():
                    lines.append(f"{indent}[视频: {text}]")
            elif text.strip():
                lines.append(f"{indent}{text}")

        elif btype == "file":
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                import html as _html
                finfo = bd.get("file", {})
                if isinstance(finfo, dict):
                    mime = str(finfo.get("mimeType", "") or finfo.get("type", "") or "")
                    fname_raw = finfo.get("name", "") or text
                    fname = _html.unescape(fname_raw) if fname_raw else ""
                    token = str(finfo.get("token", "") or "")
                    furl = finfo.get("url") or finfo.get("downloadUrl") or finfo.get("link", "")
                    if not furl and "video" in mime.lower() and fname and "/" in fname and _looks_like_video_url(fname):
                        furl = fname if fname.startswith(("http://", "https://")) else "https://" + fname
                    if "video" in mime.lower() and furl:
                        lines.append(f"{indent}[视频]({furl})")
                    elif "video" in mime.lower() and token:
                        lines.append(f"{indent}[视频: {fname}](feishu://file_token/{token})")
                    elif "video" in mime.lower():
                        lines.append(f"{indent}[视频文件: {fname}]")
                    elif furl:
                        lines.append(f"{indent}[文件]({furl})")
                    else:
                        lines.append(f"{indent}[文件: {fname or text}]")
                else:
                    lines.append(f"{indent}[文件: {text}]")
            elif text.strip():
                lines.append(f"{indent}{text}")

        elif btype in ("divider", "horizontal_rule", "thematic_break"):
            lines.append("---")

        elif btype in ("toggle_heading", "toggle_heading1", "toggle_heading2",
                        "toggle_heading3", "toggle_heading4"):
            # Collapsible heading — render as heading + nested children in <details>
            level = 1
            for ch in btype:
                if ch.isdigit():
                    level = int(ch)
                    break
            if text.strip():
                lines.append(f"{'#' * level} {text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("equation", "math_equation", "math_block"):
            eq = bd.get("equation", "") or bd.get("formula", "") or text
            if eq.strip():
                lines.append(f"{indent}$$\n{eq}\n$$")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype == "quote":
            if text.strip():
                lines.append(f"{indent}> {text}")
            if children:
                for sl in _blocks_to_md(bmap, children, indent, seq_pos):
                    lines.append(f"{indent}> {sl}")

        elif btype in ("gallery", "image_group"):
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                if children:
                    lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))
                elif text.strip():
                    lines.append(f"{indent}{text}")
            elif children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("chat_card", "chat_group"):
            if text.strip():
                lines.append(f"{indent}[聊天卡片: {text}]")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("mention", "mention_doc", "mention_user"):
            if text.strip():
                lines.append(f"{indent}{text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype == "reminder":
            if text.strip():
                lines.append(f"{indent}[提醒: {text}]")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("task", "task_list"):
            mark = "x" if bd.get("done") or bd.get("checked") else " "
            if text.strip():
                lines.append(f"{indent}- [{mark}] {text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent + "   ", seq_pos))

        elif btype in ("link_preview", "url_preview"):
            link_url = bd.get("url", "") or bd.get("link", "")
            if isinstance(link_url, dict):
                link_url = link_url.get("url", "")
            label = text.strip() or link_url
            if link_url:
                lines.append(f"{indent}[{label}]({link_url})")
            elif label:
                lines.append(f"{indent}{label}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("jira", "jira_issue"):
            jira_key = bd.get("key", "") or bd.get("issueKey", "") or text
            if jira_key.strip():
                lines.append(f"{indent}[JIRA: {jira_key}]")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("okr", "okr_block"):
            if text.strip():
                lines.append(f"{indent}[OKR: {text}]")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("wiki_catalog", "catalog"):
            if text.strip():
                lines.append(f"{indent}{text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("board", "whiteboard_block"):
            if not _HARVESTER_TEXT_AND_TABLES_ONLY:
                token = bd.get("token", "")
                if token:
                    lines.append(f"{indent}[画板: {token}]")
                elif text.strip():
                    lines.append(f"{indent}[画板: {text}]")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("view", "view_block"):
            # Feishu "view" blocks are container blocks (e.g. table views)
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))
            elif text.strip():
                lines.append(f"{indent}{text}")

        elif btype in ("iframe", "bitable", "mindnote", "sheet", "diagram", "slides"):
            token = bd.get("token", "") or bd.get("file_token", "")
            if not token:
                # Try extracting from embedded URL
                embed_url = bd.get("url", "") or bd.get("embedUrl", "") or bd.get("src", "")
                if embed_url:
                    tm = re.search(r"/(base|sheets|mindnotes|board|slides|diagram)/([A-Za-z0-9_-]{10,})", embed_url)
                    if tm:
                        token = tm.group(2)
            if _HARVESTER_TEXT_AND_TABLES_ONLY:
                if children:
                    lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))
            else:
                if token:
                    lines.append(f"{indent}[{btype}: {token}]")
                elif text.strip():
                    lines.append(f"{indent}[{btype}: {text}]")
                elif children:
                    lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        elif btype in ("undefined", "unsupported"):
            # Always try to extract whatever content exists
            if text.strip():
                lines.append(f"{indent}{text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

        else:
            # Catch-all: always output text AND recurse into children
            if text.strip():
                lines.append(f"{indent}{text}")
            if children:
                lines.extend(_blocks_to_md(bmap, children, indent, seq_pos))

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

    seq_raw = d.get("block_sequence") or []
    seq_pos = _seq_pos_from_sequence(seq_raw if isinstance(seq_raw, list) else None)
    md_lines = _blocks_to_md(bmap, [page_bid], "", seq_pos)

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


def _parse_block_map(bmap: dict, sequence: list[str] | None = None) -> dict | None:
    """Parse a raw block_map dict (from paginated client_vars responses).

    ``sequence`` is the ordered list of block IDs from the ``block_sequence``
    field in the Lark Docx SPA API response.  When the root ``page`` block is
    absent from the map (as is the case for paginated Lark Docx SPA responses),
    the sequence — or a synthetic root derived from external parent_ids — is
    used to drive rendering.
    """
    page_bid = None
    page_title = ""
    for bid, block in bmap.items():
        bd = block.get("data", {})
        if bd.get("type") == "page":
            page_bid = bid
            page_title = _get_text(bd)
            break

    if not page_bid:
        # No explicit page root.  Reconstruct ordered children from block_sequence
        # or from the most-common external parent_id.
        root_children: list[str] = []
        if sequence:
            # Use API-provided sequence (only include IDs that exist in the map)
            root_children = [bid for bid in sequence if bid in bmap]

        # Also find blocks whose parent_id is not in the map (orphaned
        # subtrees).  These often contain content from paginated API
        # responses where the parent wasn't captured.
        all_ids = set(bmap.keys())
        _STRUCTURAL = {"heading1", "heading2", "heading3", "heading4",
                       "heading5", "page", "grid", "table", "callout",
                       "ordered", "bullet", "text", "image"}

        ext_parents: dict[str, list[str]] = {}
        for bid, block in bmap.items():
            pid = (block.get("data") or {}).get("parent_id", "")
            if pid and pid not in all_ids:
                ext_parents.setdefault(pid, []).append(bid)

        if not root_children and not ext_parents:
            return None

        if not root_children:
            # No sequence — pick the most structurally diverse parent group.
            def _structural_score(pid: str) -> tuple[int, int]:
                kids = ext_parents[pid]
                types_seen: set[str] = set()
                for cid in kids:
                    bt = (bmap.get(cid, {}).get("data") or {}).get("type", "")
                    if bt in _STRUCTURAL:
                        types_seen.add(bt)
                return (len(types_seen), len(kids))

            root_parent = max(ext_parents, key=_structural_score)
            root_children = ext_parents[root_parent]
        else:
            # Sequence provided but may be incomplete.  Append orphan groups
            # that contribute structurally diverse blocks not already covered.
            root_set = set(root_children)
            for pid, kids in ext_parents.items():
                uncovered = [k for k in kids if k not in root_set]
                if not uncovered:
                    continue
                # Only append groups with structural block types
                types_seen: set[str] = set()
                for cid in uncovered:
                    bt = (bmap.get(cid, {}).get("data") or {}).get("type", "")
                    if bt in _STRUCTURAL:
                        types_seen.add(bt)
                if len(types_seen) >= 2:
                    root_children.extend(uncovered)
                    root_set.update(uncovered)

        if not root_children:
            return None

        syn_pid = "__synthetic_page__"
        bmap = dict(bmap)
        bmap[syn_pid] = {"data": {"type": "page", "children": root_children, "text": {}}}
        page_bid = syn_pid

    seq_pos = _seq_pos_from_sequence(sequence)
    md_lines = _blocks_to_md(bmap, [page_bid], "", seq_pos)
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

def _parse_ocean_qs(url: str) -> dict[str, str]:
    qs = parse_qs(urlparse(url).query)
    return {
        "graph_id": (qs.get("graphId") or [""])[0],
        "page_id": (qs.get("pageId") or [""])[0],
        "space_id": (qs.get("spaceId") or [""])[0],
    }


def _ocean_nav_tree_url_candidates(seed_url: str) -> list[str]:
    """Return ordered SSR /content/root URLs to try (support host has full trees for help links without graphId)."""
    parsed = urlparse(seed_url)
    q = _parse_ocean_qs(seed_url)
    pid, sid, gid = q["page_id"], q["space_id"], q["graph_id"]
    if not pid or not sid:
        return []

    base_q = f"{_SSR_LOADER_QS}&mappingType=1&pageId={pid}&spaceId={sid}"
    if gid:
        base_q += f"&graphId={gid}"

    support_root = f"{_SUPPORT_CONTENT}/root?{base_q}"
    yuntu_root = f"{_YUNTU_CONTENT}/root?{base_q}"

    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if "support.oceanengine.com" in host or "/help/" in path:
        return [support_root, yuntu_root]
    if "yuntu.oceanengine.com" in host:
        return [yuntu_root, support_root]
    return [support_root, yuntu_root]


def _count_tree_leaves(nodes: list) -> int:
    nleaf = 0

    def walk(ns: list) -> None:
        nonlocal nleaf
        for n in ns or []:
            if n.get("mappingType") == 2 and n.get("mappingId"):
                nleaf += 1
            walk(n.get("subTreeNodes") or n.get("children") or [])

    walk(nodes)
    return nleaf


def _load_json_response(text: str) -> dict:
    text = text.strip()
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
        return json.loads(text[:end])
    return json.loads(text)


def _serialize_nav_tree_node(n: dict, path: str = "") -> dict | None:
    """Nested nodes for frontend tree UI (folders = mappingType 1, articles = 2)."""
    name = n.get("mappingName", "") or "未命名"
    mtype = n.get("mappingType")
    mid = n.get("mappingId")
    cur_path = f"{path}/{name}" if path else name
    raw_children = n.get("subTreeNodes") or n.get("children") or []
    child_nodes: list[dict] = []
    for ch in raw_children:
        sn = _serialize_nav_tree_node(ch, cur_path)
        if sn:
            child_nodes.append(sn)

    if mtype == 2 and mid:
        return {
            "title": name,
            "mapping_type": 2,
            "mapping_id": mid,
            "graph_path": cur_path,
            "target_id": n.get("targetId") or mid,
            "children": [],
        }
    if mtype == 1 or raw_children:
        return {
            "title": name,
            "mapping_type": int(mtype) if mtype is not None else 1,
            "mapping_id": mid,
            "graph_path": cur_path,
            "children": child_nodes,
        }
    return None


async def fetch_nav_tree(url: str) -> dict:
    candidates = _ocean_nav_tree_url_candidates(url)
    if not candidates:
        raise ValueError("无法解析目录：请在 URL 中保留 pageId 与 spaceId 查询参数（巨量帮助中心链接通常自带）。")

    best: dict | None = None
    best_leaves = -1
    last_err: Exception | None = None

    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=HEADERS) as client:
        for api_url in candidates:
            try:
                resp = await client.get(api_url)
                resp.raise_for_status()
                data = _load_json_response(resp.text)
                nodes = data.get("nodes") or []
                nleaf = _count_tree_leaves(nodes)
                if nleaf > best_leaves:
                    best = data
                    best_leaves = nleaf
            except Exception as e:
                last_err = e
                logger.warning("nav tree fetch failed for %s: %s", api_url[:120], e)

    if not best:
        raise last_err or RuntimeError("获取目录树失败")

    graph = best.get("graph") or {}
    graphs = best.get("graphs") or []
    if not graph.get("graphId") and graphs:
        g0 = graphs[0]
        if isinstance(g0, dict) and g0.get("graphId"):
            graph = {**graph, "graphId": g0["graphId"], "graphName": g0.get("graphName", graph.get("graphName", ""))}

    nodes = best.get("nodes", [])
    articles: list[dict] = []

    def walk_flat(node_list: list, path: str = "") -> None:
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
            walk_flat(children, current_path)

    walk_flat(nodes)

    tree_nodes = []
    for root in nodes:
        sn = _serialize_nav_tree_node(root, "")
        if sn:
            tree_nodes.append(sn)

    gid_val = graph.get("graphId", "")
    if gid_val is not None and not isinstance(gid_val, str):
        gid_val = str(gid_val)

    return {
        "graph_name": graph.get("graphName", ""),
        "graph_id": gid_val,
        "articles": articles,
        "total_articles": len(articles),
        "tree_nodes": tree_nodes,
    }


# ═══ Crawl Pipeline ═══

async def _fetch_article_ssr(
    client: httpx.AsyncClient,
    mapping_id: int | str,
    gid: str,
    pid: str,
    sid: str,
    seed_url: str = "",
) -> dict | None:
    """Fetch article metadata via SSR API (works without auth).

    Returns the full contentData dict which may include feishuDocxToken
    for feishu_docx_new_import articles.
    Tries support.oceanengine.com first for help-center links — same payload keys as yuntu.
    """
    q_core = f"{_SSR_LOADER_QS}&mappingType=2&pageId={pid}&spaceId={sid}"
    if gid:
        q_core += f"&graphId={gid}"

    u_sup = f"{_SUPPORT_CONTENT}/{mapping_id}?{q_core}"
    u_yun = f"{_YUNTU_CONTENT}/{mapping_id}?{q_core}"

    host = (urlparse(seed_url).hostname or "").lower()
    path = urlparse(seed_url).path or ""
    if "support.oceanengine.com" in host or "/help/" in path:
        try_urls = [u_sup, u_yun]
    elif "yuntu.oceanengine.com" in host:
        try_urls = [u_yun, u_sup]
    else:
        try_urls = [u_sup, u_yun]

    for api_url in try_urls:
        try:
            resp = await client.get(api_url)
            if resp.status_code == 200:
                data = json.loads(resp.text)
                cd = data.get("contentData")
                if cd:
                    return cd
        except Exception:
            pass
    return None


async def _scroll_jssdk_container(page) -> None:
    """Scroll the JSSDK document container to trigger virtual-scroll page loads.

    Feishu JSSDK renders documents inside an inner scrollable div, not window.
    We try common selector patterns first; fall back to window if none found.
    Scrolls to top first, then sweeps the full document height.
    """
    try:
        await page.evaluate("""async () => {
            const sleep = (ms) => new Promise(r => setTimeout(r, ms));
            const SELECTORS = [
                '[class*="doc-content"]',
                '[class*="lark-doc"]',
                '[class*="docx-container"]',
                '[class*="render-unit-outer"]',
                '[class*="layout-body"]',
                '[class*="page-content"]',
                '[class*="scrollable"]',
                'article',
                'main',
            ];
            let el = null;
            for (const sel of SELECTORS) {
                const found = document.querySelector(sel);
                if (found && found.scrollHeight > found.clientHeight + 200) {
                    el = found;
                    break;
                }
            }
            if (!el) el = document.scrollingElement || document.documentElement;
            // Scroll to top first to trigger loading of initial blocks
            el.scrollTo(0, 0);
            window.scrollTo(0, 0);
            await sleep(500);
            const h = Math.max(el.scrollHeight, 50000);
            const step = Math.max(400, Math.floor((el.clientHeight || window.innerHeight || 800) * 0.7));
            for (let y = 0; y < h; y += step) {
                el.scrollTo(0, y);
                window.scrollTo(0, y);
                await sleep(180);
            }
            el.scrollTo(0, h);
            window.scrollTo(0, h);
            await sleep(500);
        }""")
    except Exception:
        pass


async def _extract_feishu_via_browser(
    page,
    article_url: str,
    cdn_url_data: dict[str, dict],
    timeout_ms: int = 30000,
) -> dict | None:
    """Navigate to article page and extract Feishu docx content.

    Supports two embedding modes:
      1. Feishu iframe (larkoffice/feishu/larksuite domain)
      2. Feishu JSSDK inline rendering (feishu_docx_new_import) — no iframe,
         content fetched via /docx/pages/client_vars API intercepted here.

    ``cdn_url_data`` is populated by a response handler in the caller that
    intercepts /space/api/box/file/cdn_url/ responses with encrypted CDN URLs.
    """
    jssdk_blocks: dict = {}
    jssdk_sequence: list[str] = []  # ordered block IDs from block_sequence field

    async def _on_client_vars(response):
        if "/docx/pages/client_vars" not in response.url or response.status != 200:
            return
        try:
            body = await response.json()
            d = body.get("data") or {}
            bmap = d.get("block_map") or {}
            jssdk_blocks.update(bmap)
            _merge_client_vars_sequence(jssdk_sequence, d.get("block_sequence"))
            logger.debug("JSSDK client_vars captured: %d blocks (total %d, seq %d)",
                         len(bmap), len(jssdk_blocks), len(jssdk_sequence))
        except Exception:
            pass

    page.on("response", _on_client_vars)

    logger.info("Browser navigating to: %s", article_url)
    try:
        await page.goto(article_url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        page.remove_listener("response", _on_client_vars)
        logger.warning("Navigation failed: %s", e)
        return None

    await page.wait_for_timeout(2000)
    await _scroll_page_for_lazy_media(page)
    final_url = page.url
    logger.info("Page URL after navigation: %s", final_url)

    def _is_login_page() -> bool:
        if "login" in final_url.lower() or "passport" in final_url.lower():
            return True
        for frame in page.frames:
            if "login" in frame.url.lower() or "passport" in frame.url.lower():
                return True
        return False

    if _is_login_page():
        page.remove_listener("response", _on_client_vars)
        logger.warning("Redirected to login page — auth cookies expired or invalid (frame URLs: %s)",
                        [f.url[:100] for f in page.frames])
        return {"_error": "auth_expired"}

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
        if jssdk_blocks:
            logger.info("JSSDK blocks detected (%d blocks), skipping iframe wait", len(jssdk_blocks))
            break
        await page.wait_for_timeout(2000)
        elapsed += 2000

    if not target_frame and not jssdk_blocks:
        logger.warning("No Feishu iframe found after %dms, waiting for JSSDK...", timeout_ms)
        for _ in range(5):
            await page.wait_for_timeout(2000)
            if jssdk_blocks:
                logger.info("JSSDK blocks arrived late: %d blocks", len(jssdk_blocks))
                break

    if not target_frame and not jssdk_blocks:
        # Debug: dump page state to understand what the JSSDK rendered
        try:
            page_debug = await page.evaluate("""() => {
                const info = {};
                info.frameCount = window.frames.length;
                info.frameUrls = Array.from(document.querySelectorAll('iframe')).map(f => f.src || f.dataset.src || '(no src)').slice(0, 5);
                info.bodyTextLen = document.body ? document.body.innerText.length : 0;
                info.bodySnippet = document.body ? document.body.innerText.slice(0, 500) : '';
                // Look for common Feishu/doc content containers
                const selectors = [
                    '[class*="lark"]', '[class*="feishu"]', '[class*="docx"]',
                    '[class*="doc-content"]', '[class*="article"]', '[class*="rich-text"]',
                    '[class*="ql-editor"]', '[class*="ProseMirror"]', '[class*="content-wrapper"]',
                    '[data-zone]', '[data-block-id]',
                ];
                info.containers = {};
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) {
                        info.containers[sel] = {
                            count: els.length,
                            textLen: Array.from(els).reduce((s, e) => s + e.innerText.length, 0),
                            sample: els[0].innerText.slice(0, 200),
                        };
                    }
                }
                return JSON.stringify(info);
            }""")
            logger.info("JSSDK page debug: %s", page_debug)
        except Exception as e:
            logger.warning("JSSDK page debug failed: %s", e)

        # Fallback: try to extract rendered content directly from DOM
        try:
            dom_content = await page.evaluate("""() => {
                // Try common article/content containers
                const candidates = [
                    ...document.querySelectorAll('[class*="article-content"], [class*="doc-content"], [class*="rich-text"], [class*="content-wrapper"]'),
                    ...document.querySelectorAll('[class*="lark-doc"], [class*="feishu"], [class*="docx-container"]'),
                    ...document.querySelectorAll('[data-zone="content"], [data-zone="article"]'),
                    ...document.querySelectorAll('article, .article, .content, main .content'),
                ];
                for (const el of candidates) {
                    const text = el.innerText.trim();
                    if (text.length > 100) return text;
                }
                // Last resort: get main content area
                const main = document.querySelector('main') || document.querySelector('[role="main"]');
                if (main && main.innerText.trim().length > 100) return main.innerText.trim();
                return null;
            }""")
            if dom_content and len(dom_content) > 100:
                logger.info("JSSDK DOM fallback: extracted %d chars from page DOM", len(dom_content))
                page.remove_listener("response", _on_client_vars)
                return {
                    "markdown": dom_content,
                    "text": dom_content,
                    "blocks": [],
                }
        except Exception as e:
            logger.warning("JSSDK DOM fallback failed: %s", e)

        page.remove_listener("response", _on_client_vars)
        logger.warning("No Feishu iframe or JSSDK content found")
        return None

    # --- JSSDK path: content captured via intercepted client_vars responses ---
    if not target_frame and jssdk_blocks:
        # Feishu JSSDK uses virtual scroll: blocks load on demand as the user scrolls.
        # One scroll pass is insufficient for long articles — iterate until stable.
        for _scroll_round in range(8):
            prev_count = len(jssdk_blocks)
            await _scroll_jssdk_container(page)
            # Wait up to 12 s for new blocks triggered by this scroll pass.
            for _ in range(6):
                await page.wait_for_timeout(2000)
                if len(jssdk_blocks) > prev_count:
                    break
            if len(jssdk_blocks) == prev_count:
                break
            logger.debug("JSSDK scroll round %d: %d → %d blocks",
                         _scroll_round + 1, prev_count, len(jssdk_blocks))

        page.remove_listener("response", _on_client_vars)

        await _refresh_sequence_from_window_data(page, jssdk_sequence)
        await _apply_dom_block_order(page, jssdk_sequence, jssdk_blocks)

        # Log block type distribution for JSSDK diagnostics
        jssdk_type_counts: dict[str, int] = {}
        for _bid, _blk in jssdk_blocks.items():
            _bt = (_blk.get("data") or {}).get("type", "unknown")
            jssdk_type_counts[_bt] = jssdk_type_counts.get(_bt, 0) + 1
        logger.info("JSSDK block types: %s", jssdk_type_counts)
        _dump_block_map(jssdk_blocks, "_debug_latest", "jssdk_blocks")

        doc = _parse_block_map(jssdk_blocks, sequence=jssdk_sequence or None)
        if doc and len(doc.get("text", "")) > 30:
            logger.info("JSSDK extracted %d chars from %d blocks", len(doc["text"]), len(jssdk_blocks))
            return doc

        logger.warning("JSSDK block parsing yielded insufficient text (%d blocks)", len(jssdk_blocks))
        return doc

    # --- iframe path ---
    # IMPORTANT: do NOT remove the response listener yet.
    # Scrolling the iframe will trigger more /docx/pages/client_vars requests which
    # must still be captured.  Listener is removed once we are done scrolling.

    if target_frame:
        is_lark_docx_spa = any(k in target_frame.url for k in ("/docx/", "/wiki/"))

        if is_lark_docx_spa:
            # New Lark Docx SPA (bytedance.larkoffice.com/docx/…).
            # Content is served via paginated /docx/pages/client_vars API, captured in
            # jssdk_blocks by the response interceptor.  The initial page content may
            # also be in window.DATA.clientVars (not via API) — extract that first.
            # Strategy: extract initial clientVars, scroll to trigger lazy pages, merge.

            # --- Phase -1: extract initial clientVars from iframe window.DATA ---
            try:
                initial_cv = await target_frame.evaluate("""() => {
                    try {
                        if (window.DATA && window.DATA.clientVars) {
                            const cv = window.DATA.clientVars;
                            const d = (typeof cv === 'string') ? JSON.parse(cv) : cv;
                            const data = d.data || d;
                            const bmap = data.block_map || {};
                            const seq = data.block_sequence || [];
                            if (Object.keys(bmap).length > 0) {
                                return JSON.stringify({block_map: bmap, block_sequence: seq});
                            }
                        }
                    } catch(e) {}
                    return null;
                }""")
                if initial_cv:
                    import json as _json
                    _cv_data = _json.loads(initial_cv)
                    _initial_bmap = _cv_data.get("block_map", {})
                    _initial_seq = _cv_data.get("block_sequence", [])
                    if _initial_bmap:
                        # Merge initial blocks (these take priority — they're the document start)
                        pre_count = len(jssdk_blocks)
                        for k, v in _initial_bmap.items():
                            if k not in jssdk_blocks:
                                jssdk_blocks[k] = v
                        _merge_client_vars_sequence(jssdk_sequence, _initial_seq)
                        logger.info("iframe initial clientVars: %d new blocks (total %d → %d)",
                                    len(jssdk_blocks) - pre_count, pre_count, len(jssdk_blocks))
            except Exception as e:
                logger.debug("iframe initial clientVars extraction failed: %s", e)

            # --- Phase 0: scroll to top and wait for initial blocks ---
            try:
                await target_frame.evaluate("""async () => {
                    const sleep = ms => new Promise(r => setTimeout(r, ms));
                    const SELS = [
                        '[class*="doc-content"]','[class*="render-unit"]',
                        '[class*="layout-body"]','[class*="page-body"]',
                        '[class*="lark-doc"]','[class*="docx"]',
                        '[class*="scroll"]','main','article',
                    ];
                    let el = null;
                    for (const s of SELS) {
                        const f = document.querySelector(s);
                        if (f && f.scrollHeight > f.clientHeight + 200) { el = f; break; }
                    }
                    if (!el) el = document.scrollingElement || document.documentElement;
                    el.scrollTo(0, 0);
                    window.scrollTo(0, 0);
                    await sleep(800);
                }""")
            except Exception:
                pass
            await page.wait_for_timeout(3000)
            logger.info("iframe Lark Docx SPA: scrolled to top, %d blocks so far", len(jssdk_blocks))

            # --- Phase 1: scroll top-to-bottom in rounds ---
            _no_new_rounds = 0
            for _scroll_round in range(20):
                prev_count = len(jssdk_blocks)
                try:
                    await target_frame.evaluate("""async () => {
                        const sleep = ms => new Promise(r => setTimeout(r, ms));
                        const SELS = [
                            '[class*="doc-content"]','[class*="render-unit"]',
                            '[class*="layout-body"]','[class*="page-body"]',
                            '[class*="lark-doc"]','[class*="docx"]',
                            '[class*="scroll"]','main','article',
                        ];
                        let el = null;
                        for (const s of SELS) {
                            const f = document.querySelector(s);
                            if (f && f.scrollHeight > f.clientHeight + 200) { el = f; break; }
                        }
                        if (!el) el = document.scrollingElement || document.documentElement;
                        // Use live scrollHeight each round (grows as content loads)
                        const h = Math.max(el.scrollHeight, 50000);
                        const step = Math.max(400, Math.floor((el.clientHeight || window.innerHeight || 800) * 0.7));
                        for (let y = 0; y < h; y += step) {
                            el.scrollTo(0, y);
                            window.scrollTo(0, y);
                            await sleep(120);
                        }
                        el.scrollTo(0, h);
                        window.scrollTo(0, h);
                        await sleep(500);
                        // Scroll back to top to trigger any remaining lazy-loaded blocks
                        el.scrollTo(0, 0);
                        window.scrollTo(0, 0);
                        await sleep(300);
                    }""")
                except Exception as e:
                    logger.debug("iframe Lark Docx scroll error (round %d): %s", _scroll_round + 1, e)
                for _ in range(6):
                    await page.wait_for_timeout(2000)
                    if len(jssdk_blocks) > prev_count:
                        break
                if len(jssdk_blocks) == prev_count:
                    _no_new_rounds += 1
                    if _no_new_rounds >= 2:
                        break
                else:
                    _no_new_rounds = 0
                logger.info("iframe Lark Docx SPA scroll round %d: %d → %d blocks",
                            _scroll_round + 1, prev_count, len(jssdk_blocks))

            page.remove_listener("response", _on_client_vars)

            if jssdk_blocks:
                await _apply_dom_block_order(target_frame, jssdk_sequence, jssdk_blocks)
                # Dump raw block data for debugging
                _dump_block_map(jssdk_blocks, "_debug_latest", "iframe_lark_docx_spa")

                doc = _parse_block_map(jssdk_blocks, sequence=jssdk_sequence or None)
                if doc and len(doc.get("text", "")) > 30:
                    logger.info("iframe Lark Docx SPA: %d chars from %d blocks",
                                len(doc["text"]), len(jssdk_blocks))
                    # Try to collect CDN image keys from the iframe
                    img_tokens: set[str] = set()
                    for _, u in _IMG_RE.findall(doc.get("markdown", "")):
                        tm = re.search(r"/cover/([^/?]+)", u)
                        if tm:
                            img_tokens.add(tm.group(1))
                    missing = img_tokens - set(cdn_url_data.keys())
                    if missing:
                        try:
                            batch_result = await target_frame.evaluate(
                                """(tokens) => new Promise(async resolve => {
                                    try {
                                        const r = await fetch('/space/api/box/file/cdn_url/', {
                                            method:'POST',
                                            headers:{'Content-Type':'application/json'},
                                            body: JSON.stringify({file_tokens:tokens, type:'image'}),
                                            credentials:'include'
                                        });
                                        resolve(JSON.stringify(await r.json()));
                                    } catch(e) { resolve(JSON.stringify({error:e.message})); }
                                })""",
                                list(missing),
                            )
                            if batch_result:
                                for item in (json.loads(batch_result).get("data") or []):
                                    t = item.get("file_token", "")
                                    if t and item.get("url"):
                                        cdn_url_data[t] = {
                                            "url": item["url"],
                                            "secret": item.get("secret", ""),
                                            "nonce": item.get("nonce", ""),
                                        }
                        except Exception as e:
                            logger.debug("iframe CDN batch fetch error: %s", e)
                        logger.info("CDN keys: %d/%d collected", len(img_tokens & set(cdn_url_data.keys())), len(img_tokens))

                    # --- DOM supplement: scroll-and-capture to get virtual-scroll content ---
                    # Feishu uses virtual scrolling — only the viewport slice is in the DOM.
                    # We scroll top-to-bottom, collecting text from each viewport position.
                    try:
                        dom_text = await target_frame.evaluate("""async () => {
                            const sleep = ms => new Promise(r => setTimeout(r, ms));
                            const SELS = [
                                '[class*="doc-content"]','[class*="render-unit"]',
                                '[class*="layout-body"]','[class*="lark-doc"]',
                                '[class*="docx"]','[class*="scroll"]','main','article',
                            ];
                            let el = null;
                            for (const s of SELS) {
                                const f = document.querySelector(s);
                                if (f && f.scrollHeight > f.clientHeight + 200) { el = f; break; }
                            }
                            if (!el) el = document.scrollingElement || document.documentElement;

                            const seen = new Set();
                            const ordered = [];
                            const step = Math.max(300, Math.floor((el.clientHeight || 600) * 0.5));
                            const h = Math.max(el.scrollHeight, 50000);

                            // Scroll from top to bottom, collecting visible block text
                            el.scrollTo(0, 0);
                            await sleep(600);
                            for (let y = 0; y <= h; y += step) {
                                el.scrollTo(0, y);
                                await sleep(80);
                                // Collect text from block elements
                                const blocks = el.querySelectorAll('[data-block-id]');
                                for (const b of blocks) {
                                    const bid = b.getAttribute('data-block-id');
                                    if (bid && !seen.has(bid)) {
                                        seen.add(bid);
                                        const txt = b.innerText.trim();
                                        if (txt) ordered.push(txt);
                                    }
                                }
                            }
                            return ordered.join('\\n');
                        }""")
                        if dom_text and len(dom_text) > len(doc.get("text", "")) + 200:
                            block_text = doc.get("text", "")
                            block_lower = block_text.lower()
                            dom_lines = dom_text.strip().split("\n")
                            missing_lines: list[str] = []
                            for line in dom_lines:
                                stripped = line.strip()
                                if not stripped or len(stripped) < 4:
                                    continue
                                if stripped.lower() not in block_lower:
                                    missing_lines.append(stripped)
                            if len(missing_lines) > 5:
                                dom_supplement = "\n\n".join(missing_lines)
                                doc["markdown"] = dom_supplement + "\n\n---\n\n" + doc["markdown"]
                                doc["text"] = dom_supplement + "\n\n" + doc["text"]
                                logger.info("iframe DOM supplement: added %d lines (%d chars) from DOM",
                                            len(missing_lines), len(dom_supplement))
                            else:
                                logger.info("iframe DOM supplement: no significant new content (DOM %d chars, blocks %d chars)",
                                            len(dom_text), len(block_text))
                        else:
                            logger.info("iframe DOM supplement: DOM text (%d chars) not larger than block text (%d chars)",
                                        len(dom_text) if dom_text else 0, len(doc.get("text", "")))
                    except Exception as e:
                        logger.warning("iframe DOM supplement extraction failed: %s", e)

                    return doc

            logger.warning("iframe Lark Docx SPA: no usable blocks (%d captured)", len(jssdk_blocks))
            return None

        # --- Older Feishu iframe that uses window.DATA.clientVars ---
        page.remove_listener("response", _on_client_vars)
        try:
            await target_frame.evaluate("""async () => {
                const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
                const el = document.scrollingElement || document.documentElement;
                const h = Math.max(el.scrollHeight || 0, 8000);
                const step = Math.max(380, Math.floor((el.clientHeight || window.innerHeight || 600) * 0.82));
                for (let y = 0; y < h; y += step) {
                    el.scrollTo(0, y);
                    await sleep(100);
                }
                el.scrollTo(0, h);
                await sleep(350);
            }""")
        except Exception:
            pass

        for attempt in range(10):
            try:
                raw = await target_frame.evaluate(FEISHU_GET_DATA_JS)
                if raw:
                    doc = parse_feishu_document(raw)
                    if doc and len(doc.get("text", "")) > 30:
                        logger.info("Extracted %d chars from iframe (attempt %d)", len(doc["text"]), attempt + 1)

                        img_tokens_old: set[str] = set()
                        for _, u in _IMG_RE.findall(doc.get("markdown", "")):
                            tm = re.search(r"/cover/([^/?]+)", u)
                            if tm:
                                img_tokens_old.add(tm.group(1))

                        missing_old = img_tokens_old - set(cdn_url_data.keys())
                        if missing_old:
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

                            still_missing = list(img_tokens_old - set(cdn_url_data.keys()))
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

                            logger.info("CDN keys collected: %d/%d image tokens",
                                        len(img_tokens_old & set(cdn_url_data.keys())), len(img_tokens_old))
                        else:
                            await page.wait_for_timeout(2000)

                        return doc
                    logger.debug("Data found but too short (attempt %d)", attempt + 1)
            except Exception as e:
                logger.debug("Frame evaluate error (attempt %d): %s", attempt + 1, e)
            await page.wait_for_timeout(2000)

        # Fallback: window.DATA failed — use whatever blocks the interceptor captured
        if jssdk_blocks:
            await _apply_dom_block_order(target_frame, jssdk_sequence, jssdk_blocks)
            doc = _parse_block_map(jssdk_blocks, sequence=jssdk_sequence or None)
            if doc and len(doc.get("text", "")) > 30:
                logger.info("iframe window.DATA failed; jssdk_blocks fallback: %d chars", len(doc["text"]))
                return doc

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
    """Download images from feishucdn.com — handles both encrypted (AES-GCM) and
    unencrypted (cipher_type=0) images.

    cdn_url_data maps token -> {url, secret, nonce, cipher_type, ...}.
    Returns token -> raw image bytes for successfully downloaded images.
    """
    from base64 import b64decode

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        AESGCM = None  # type: ignore[assignment]
        logger.warning("cryptography package not available; only unencrypted images can be downloaded")

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
            cipher_type = str(info.get("cipher_type", "1"))

            if not url:
                continue

            try:
                if cipher_type == "0" or not (secret and nonce_b64):
                    # Unencrypted image — download raw bytes directly
                    resp = await client.get(url)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        result[token] = resp.content
                        continue
                    # Fallback: try the /download/preview/ URL pattern
                    preview_url = url.replace("/download/all/", "/download/preview/")
                    if preview_url != url:
                        resp2 = await client.get(preview_url)
                        if resp2.status_code == 200 and len(resp2.content) > 100:
                            result[token] = resp2.content
                            continue
                else:
                    # Encrypted image — AES-GCM decrypt
                    if AESGCM is None:
                        continue
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    key = b64decode(secret)
                    nonce = b64decode(nonce_b64)
                    decrypted = AESGCM(key).decrypt(nonce, resp.content, None)
                    if len(decrypted) > 100:
                        result[token] = decrypted
            except Exception:
                logger.debug("Failed to download/decrypt image %s", token, exc_info=True)

    logger.info("CDN image download: %d/%d images for job %s", len(result), len(available), job_id)
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


# ── Embedded content screenshot (画板 / 思维导图 / 幻灯片 / 多维表格) ────────

# Matches placeholders like [画板: TOKEN], [mindnote: TOKEN], [bitable: TOKEN], etc.
_EMBEDDED_PLACEHOLDER_RE = re.compile(
    r"\[(画板|whiteboard|mindnote|bitable|sheet|diagram|slides|iframe):\s*([A-Za-z0-9_-]{10,})\]"
)

# Feishu URL patterns for each embedded type
_EMBEDDED_URL_TEMPLATES: dict[str, str] = {
    "画板": "https://bytedance.larkoffice.com/board/{token}",
    "whiteboard": "https://bytedance.larkoffice.com/board/{token}",
    "mindnote": "https://bytedance.larkoffice.com/mindnotes/{token}",
    "bitable": "https://bytedance.larkoffice.com/base/{token}",
    "sheet": "https://bytedance.larkoffice.com/sheets/{token}",
    "diagram": "https://bytedance.larkoffice.com/diagram/{token}",
    "slides": "https://bytedance.larkoffice.com/slides/{token}",
    "iframe": "",  # generic — cannot construct URL from token alone
}


async def _screenshot_embedded_content(
    ctx,
    markdown: str,
    job_id: str,
    job: dict | None = None,
) -> tuple[str, int]:
    """Screenshot embedded Feishu content (画板, 思维导图, PPT, etc.).

    For each `[画板: TOKEN]` / `[mindnote: TOKEN]` / etc. placeholder:
    1. Open the Feishu URL in a new browser context (prefer Feishu auth for direct access)
    2. Wait for content to render
    3. Take a full-page screenshot and save as image
    4. Replace the placeholder with a markdown image reference
    Returns (updated_markdown, screenshot_count).
    """
    matches = list(_EMBEDDED_PLACEHOLDER_RE.finditer(markdown))
    if not matches:
        return markdown, 0

    img_dir = IMAGE_DIR / job_id
    img_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    # Use Feishu auth if available (画板 etc. are Feishu docs, need direct Feishu cookies)
    from app.config import settings
    feishu_auth = Path(settings.feishu_auth_state)
    embed_ctx = ctx  # fallback to caller's context
    own_ctx = False
    if feishu_auth.exists():
        try:
            embed_ctx = await ctx.browser.new_context(storage_state=str(feishu_auth))
            own_ctx = True
            logger.info("Embedded screenshots: using Feishu auth for direct access")
        except Exception as e:
            logger.warning("Failed to create Feishu auth context: %s, falling back", e)

    try:
        for m in matches:
            etype = m.group(1)
            token = m.group(2)
            url_template = _EMBEDDED_URL_TEMPLATES.get(etype, "")
            if not url_template:
                logger.info("No URL template for embedded type '%s', skip token %s", etype, token)
                continue

            embed_url = url_template.format(token=token)
            fname = f"_embed_{etype}_{token}.png"
            fpath = img_dir / fname

            if fpath.exists() and fpath.stat().st_size > 5000:
                logger.info("Embedded screenshot already exists: %s", fname)
                local_url = f"/api/omni/knowledge/harvester/images/{job_id}/{fname}"
                markdown = markdown.replace(m.group(0), f"![{etype}]({local_url})", 1)
                count += 1
                continue

            try:
                if job:
                    _job_touch(job, f"截图嵌入内容: {etype} {token[:12]}…", None)

                page = await embed_ctx.new_page()
                await page.set_viewport_size({"width": 1920, "height": 1080})

                try:
                    await page.goto(embed_url, wait_until="networkidle", timeout=30000)
                except Exception:
                    # networkidle may timeout on heavy pages — try domcontentloaded
                    try:
                        await page.goto(embed_url, wait_until="domcontentloaded", timeout=20000)
                    except Exception as nav_err:
                        logger.warning("Cannot navigate to %s: %s", embed_url, nav_err)
                        await page.close()
                        continue

                # Wait extra for rendering (Feishu canvas/board needs time)
                await asyncio.sleep(5)

                # Try to dismiss any permission/login popups
                for sel in [
                    'button:has-text("我知道了")',
                    'button:has-text("关闭")',
                    'button:has-text("确定")',
                    '[class*="close-btn"]',
                    '[class*="modal"] button',
                ]:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=500):
                            await btn.click()
                            await asyncio.sleep(0.5)
                    except Exception:
                        pass

                await asyncio.sleep(2)

                # Take screenshot
                await page.screenshot(path=str(fpath), full_page=True, type="png")
                await page.close()

                if fpath.exists() and fpath.stat().st_size > 5000:
                    local_url = f"/api/omni/knowledge/harvester/images/{job_id}/{fname}"
                    markdown = markdown.replace(m.group(0), f"![{etype}]({local_url})", 1)
                    count += 1
                    logger.info("Embedded screenshot saved: %s (%d bytes)", fname, fpath.stat().st_size)
                else:
                    logger.warning("Embedded screenshot too small or empty: %s", fname)
                    if fpath.exists():
                        fpath.unlink()

            except Exception as e:
                logger.warning("Failed to screenshot embedded %s %s: %s", etype, token, e)
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception:
                    pass
    finally:
        if own_ctx:
            try:
                await embed_ctx.close()
            except Exception:
                pass

    if count:
        logger.info("Embedded screenshots: %d/%d captured for job %s", count, len(matches), job_id)
    return markdown, count


async def _auto_analyze_and_merge(
    job_id: str,
    markdown: str,
    ai_hub_url: str,
    job: dict | None = None,
) -> tuple[str, int]:
    """Analyze all saved local images in markdown via LLM and merge descriptions.

    Deduplicates by filename: if the same image file appears multiple times in
    the markdown, only the first occurrence is sent to the AI — subsequent
    occurrences reuse the cached description.
    """
    import base64

    matches = list(_LOCAL_IMG_RE.finditer(markdown))
    if not matches:
        return markdown, 0

    img_dir = IMAGE_DIR / job_id
    analyzed = 0
    # Deduplicate: track filename -> description so identical images aren't re-analyzed
    seen_descriptions: dict[str, str | None] = {}
    # Count unique images for progress display
    unique_filenames = list(dict.fromkeys(
        m.group(2).rsplit("/", 1)[-1] for m in matches
    ))
    n_unique = len(unique_filenames)
    n_img = len(matches)
    if n_unique < n_img:
        logger.info("Image dedup: %d occurrences -> %d unique images", n_img, n_unique)

    async with httpx.AsyncClient(timeout=120.0) as client:
        unique_idx = 0
        for i, match in enumerate(matches):
            alt, url = match.group(1), match.group(2)
            filename = url.rsplit("/", 1)[-1]

            # Check if we already analyzed this image (dedup)
            if filename in seen_descriptions:
                desc = seen_descriptions[filename]
                if desc:
                    original = match.group(0)
                    replacement = f"{original}\n\n> **[图片内容]** {desc}\n"
                    markdown = markdown.replace(original, replacement, 1)
                    analyzed += 1
                    logger.debug("Image dedup: reused description for %s", filename)
                continue

            unique_idx += 1
            _job_touch(
                job,
                f"图片 AI 解读 {unique_idx}/{n_unique}",
                0.18 + 0.62 * (unique_idx / max(n_unique, 1)),
            )
            filepath = img_dir / filename
            if not filepath.exists():
                seen_descriptions[filename] = None
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
                    seen_descriptions[filename] = desc
                    if desc:
                        original = match.group(0)
                        replacement = f"{original}\n\n> **[图片内容]** {desc}\n"
                        markdown = markdown.replace(original, replacement, 1)
                        analyzed += 1
                        logger.info("Auto-analyzed image %s: %d chars", filename, len(desc))
                    else:
                        logger.warning("Image %s: AI response rejected (mock/invalid): %.100s", filename, raw_desc)
                else:
                    seen_descriptions[filename] = None
            except Exception as e:
                seen_descriptions[filename] = None
                logger.warning("Auto image analysis failed for %s: %s", filename, e)

    return markdown, analyzed


def _harvester_cookie_header(auth_state_path: str | None) -> str | None:
    if not auth_state_path or not Path(auth_state_path).exists():
        return None
    try:
        state = json.loads(Path(auth_state_path).read_text(encoding="utf-8"))
        cookies = state.get("cookies") or []
        parts: list[str] = []
        for c in cookies:
            if not isinstance(c, dict):
                continue
            domain = str(c.get("domain", "")).lower()
            if "oceanengine" not in domain and "bytedance" not in domain and "toutiao" not in domain:
                continue
            name, value = c.get("name"), c.get("value")
            if name and value is not None:
                parts.append(f"{name}={value}")
        return "; ".join(parts) if parts else None
    except Exception:
        return None


def _video_summary_from_report(report: dict | None) -> str:
    if not report or not isinstance(report, dict):
        return ""
    s = report.get("summary")
    if isinstance(s, str) and s.strip():
        return s.strip()[:4000]
    ai = report.get("ai_insights")
    if isinstance(ai, dict):
        hook = ai.get("hook_analysis") or ai.get("narrative_arc")
        if isinstance(hook, str) and hook.strip():
            return hook.strip()[:4000]
    return ""


async def _poll_video_job_done(
    client: httpx.AsyncClient,
    video_base: str,
    video_id: str,
    timeout_sec: float = 900.0,
    interval_sec: float = 3.0,
) -> dict | None:
    import time as _time

    deadline = _time.monotonic() + timeout_sec
    detail_url = f"{video_base.rstrip('/')}/api/v1/video-analysis/videos/{video_id}"
    while _time.monotonic() < deadline:
        try:
            resp = await client.get(detail_url, timeout=60.0)
            if resp.status_code != 200:
                await asyncio.sleep(interval_sec)
                continue
            body = resp.json()
            video = body.get("video") or {}
            status = str(video.get("status", "")).lower()
            if status in ("done", "failed"):
                return body
        except Exception:
            pass
        await asyncio.sleep(interval_sec)
    return None


async def _download_feishu_video_via_browser(page, token: str) -> bytes | None:
    """Download a Feishu-hosted video file via the authenticated browser session.

    Finds the Feishu iframe (larkoffice/feishu domain) and executes the fetch
    there so credentials and CORS work correctly.  Falls back to the main page
    if no iframe is found.
    """
    download_url = (
        f"https://internal-api-drive-stream.larkoffice.com/space/api/box/stream/"
        f"download/all/{token}/?mount_point=doc_media"
    )

    _FETCH_JS = """(url) => {
        return new Promise(async (resolve) => {
            try {
                const resp = await fetch(url, {credentials: 'include', mode: 'cors'});
                if (!resp.ok) { resolve('ERR:' + resp.status); return; }
                const blob = await resp.blob();
                if (blob.size < 2048) { resolve('ERR:too_small:' + blob.size); return; }
                const reader = new FileReader();
                reader.onloadend = () => resolve(reader.result.split(',')[1]);
                reader.readAsDataURL(blob);
            } catch(e) { resolve('ERR:' + e.message); }
        });
    }"""

    # Try the Feishu iframe first (correct domain for CORS/cookies)
    feishu_frame = None
    for frame in page.frames:
        if any(k in frame.url for k in ("larkoffice", "feishu", "larksuite")):
            feishu_frame = frame
            break

    targets = [feishu_frame, page] if feishu_frame else [page]
    for target in targets:
        target_name = "iframe" if target is feishu_frame else "page"
        try:
            result = await target.evaluate(_FETCH_JS, download_url)
            if not result or (isinstance(result, str) and result.startswith("ERR:")):
                logger.debug("Feishu video %s download via %s: %s", token, target_name, result)
                continue
            from base64 import b64decode
            data = b64decode(result)
            if len(data) > 2048:
                logger.info("Feishu video downloaded via %s: token=%s, %d bytes", target_name, token, len(data))
                return data
        except Exception as e:
            logger.debug("Feishu video %s download failed via %s: %s", token, target_name, e)

    logger.warning("Feishu video download failed for token %s (tried iframe + page)", token)
    return None


async def _auto_analyze_videos_in_markdown(
    markdown: str,
    video_svc_url: str,
    auth_state_path: str | None = None,
    max_videos: int = 15,
    job: dict | None = None,
    browser_page=None,
) -> tuple[str, int]:
    """Download video URLs referenced in markdown, run 短视频分析服务, insert summaries after each link.

    Supports both HTTP(S) video URLs (downloaded via httpx) and feishu:// URLs
    (downloaded via the authenticated browser session when ``browser_page`` is provided).
    """
    if not markdown or not video_svc_url:
        return markdown, 0

    seen = _ordered_video_urls_from_markdown(markdown, max_videos=max_videos)
    if not seen:
        return markdown, 0

    cookie_header = _harvester_cookie_header(auth_state_path)
    analyzed = 0
    base = video_svc_url.rstrip("/")
    n_vid = len(seen)

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True, headers=HEADERS) as dl_client:
        for vi, video_url in enumerate(seen):
            _job_touch(
                job,
                f"短视频分析 {vi + 1}/{n_vid}（下载与排队）",
                0.82 + 0.15 * (vi / max(n_vid, 1)),
            )
            try:
                video_data: bytes | None = None

                # Handle feishu:// URLs via browser download
                if video_url.startswith("feishu://"):
                    if not browser_page:
                        logger.warning("Feishu video URL requires browser page: %s", video_url[:80])
                        continue
                    # Extract token from feishu://media/{token} or feishu://file_token/{token}
                    token = video_url.split("/")[-1]
                    video_data = await _download_feishu_video_via_browser(browser_page, token)
                    if not video_data:
                        logger.warning("Feishu video download failed: %s", video_url[:80])
                        continue
                else:
                    # Standard HTTP(S) download
                    req_headers = dict(HEADERS)
                    if cookie_header:
                        req_headers["Cookie"] = cookie_header
                    r = await dl_client.get(video_url, headers=req_headers)
                    if r.status_code != 200 or len(r.content) < 2048:
                        logger.warning("Video download failed or too small: %s status=%s len=%s",
                                       video_url[:80], r.status_code, len(r.content) if r.content else 0)
                        continue
                    video_data = r.content

                ext = ".mp4"
                low = video_url.lower()
                if ".webm" in low:
                    ext = ".webm"
                elif ".mov" in low:
                    ext = ".mov"
                elif ".m4v" in low:
                    ext = ".m4v"

                import tempfile

                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(video_data)
                    tmp_path = Path(tmp.name)

                try:
                    async with httpx.AsyncClient(timeout=120.0) as va_client:
                        with tmp_path.open("rb") as f:
                            up = await va_client.post(
                                f"{base}/api/v1/video-analysis/videos",
                                files={"file": (f"harvest_{uuid4().hex[:10]}{ext}", f, "video/mp4")},
                                timeout=120.0,
                            )
                        if up.status_code != 200:
                            logger.warning("Video analysis upload failed %s: %s", up.status_code, up.text[:200])
                            continue
                        up_body = up.json()
                        vid = up_body.get("id") or up_body.get("task_id")
                        if not vid:
                            continue
                        detail = await _poll_video_job_done(va_client, base, str(vid))
                        if not detail:
                            logger.warning("Video analysis timeout for %s", video_url[:80])
                            continue
                        video = detail.get("video") or {}
                        if str(video.get("status", "")).lower() == "failed":
                            logger.warning("Video analysis failed for %s: %s", vid, video.get("last_error"))
                            continue
                        summary = _video_summary_from_report(detail.get("report"))
                        if not summary:
                            summary = "（短视频分析已完成，但未返回摘要文本；可在短视频分析页面查看完整报告。）"
                        needle = f"]({video_url})"
                        if needle in markdown:
                            insert = f"{needle}\n\n> **视频解读**: {summary}\n"
                            markdown = markdown.replace(needle, insert, 1)
                            analyzed += 1
                            logger.info("Video analyzed and merged: %s", video_url[:80])
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning("Video pipeline error for %s: %s", video_url[:80], e)

    return markdown, analyzed


async def _scroll_page_for_lazy_media(page) -> None:
    """Scroll the main window to trigger lazy-loaded images / long tables."""
    try:
        await page.evaluate("""async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const h = Math.max(
                document.scrollingElement ? document.scrollingElement.scrollHeight : 0,
                document.body ? document.body.scrollHeight : 0,
                8000
            );
            const step = Math.max(480, Math.floor(window.innerHeight * 0.85));
            for (let y = 0; y < h; y += step) {
                window.scrollTo(0, y);
                await sleep(160);
            }
            window.scrollTo(0, h);
            await sleep(450);
            window.scrollTo(0, 0);
        }""")
    except Exception:
        pass


def _is_feishu_url(url: str) -> bool:
    return any(d in url for d in ("larkoffice.com/docx/", "feishu.cn/docx/", "larksuite.com/docx/",
                                   "larkoffice.com/wiki/", "feishu.cn/wiki/", "larksuite.com/wiki/"))


def _lark_embed_urls(token: str, content_type: str) -> list[str]:
    """Ordered Lark URLs for SSR feishuDocxToken. Wiki-root articles need /wiki/; tenant host matters."""
    ct = (content_type or "").lower()
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        if u not in seen:
            seen.add(u)
            urls.append(u)

    if "wiki" in ct:
        add(f"https://bytedance.larkoffice.com/wiki/{token}")
        add(f"https://larkoffice.com/wiki/{token}")
    add(f"https://bytedance.larkoffice.com/docx/{token}")
    add(f"https://larkoffice.com/docx/{token}")
    return urls


async def _extract_feishu_direct(
    page,
    url: str,
    cdn_url_data: dict[str, dict],
    timeout_ms: int = 30000,
) -> dict | None:
    """Navigate to a Feishu/Lark doc URL and extract content via client_vars API."""
    merged_blocks: dict = {}
    merged_sequence: list[str] = []  # ordered block IDs from block_sequence

    api_urls_seen: list[str] = []

    async def _on_client_vars_response(response):
        if "/docx/pages/client_vars" not in response.url or response.status != 200:
            return
        try:
            body = await response.json()
            d = body.get("data") or {}
            bmap = d.get("block_map") or {}
            merged_blocks.update(bmap)
            _merge_client_vars_sequence(merged_sequence, d.get("block_sequence"))
        except Exception:
            pass

    async def _on_any_api_response(response):
        u = response.url
        if any(k in u for k in ("client_vars", "block", "docx", "document", "render", "content")):
            api_urls_seen.append(f"[{response.status}] {u[:200]}")

    page.on("response", _on_client_vars_response)
    page.on("response", _on_any_api_response)

    logger.info("Feishu direct: navigating to %s", url)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        page.remove_listener("response", _on_client_vars_response)
        page.remove_listener("response", _on_any_api_response)
        logger.warning("Feishu navigation failed: %s", e)
        return None

    final_url = page.url
    logger.info("Feishu direct: final URL = %s", final_url)
    if "login" in final_url.lower() or "passport" in final_url.lower():
        page.remove_listener("response", _on_client_vars_response)
        page.remove_listener("response", _on_any_api_response)
        logger.warning("Redirected to login — auth cookies may be invalid")
        return None

    await _scroll_page_for_lazy_media(page)

    for attempt in range(10):
        await page.wait_for_timeout(2000)
        raw = await page.evaluate(FEISHU_GET_DATA_JS)
        if raw:
            try:
                cv = json.loads(raw)
                d0 = cv.get("data") or {}
                initial_bmap = d0.get("block_map") or {}
                if initial_bmap:
                    merged_blocks.update(initial_bmap)
                    _merge_client_vars_sequence(merged_sequence, d0.get("block_sequence"))
                    logger.info("Feishu initial clientVars: %d blocks", len(initial_bmap))
                    break
            except Exception:
                pass
        if attempt == 2:
            # Debug: check what's available on the page
            debug_info = await page.evaluate("""() => {
                const info = {};
                info.hasDATA = typeof window.DATA !== 'undefined';
                info.dataKeys = info.hasDATA ? Object.keys(window.DATA).slice(0, 10) : [];
                info.hasClientVars = info.hasDATA && !!window.DATA.clientVars;
                info.hasSSRData = typeof window.__SSR_DATA__ !== 'undefined';
                info.hasNextData = typeof window.__NEXT_DATA__ !== 'undefined';
                info.docTitle = document.title || '';
                info.bodyLen = document.body ? document.body.innerText.length : 0;
                info.bodySnippet = document.body ? document.body.innerText.slice(0, 300) : '';
                return JSON.stringify(info);
            }""")
            logger.info("Feishu direct debug (attempt %d): %s", attempt, debug_info)

    for _scroll_round in range(8):
        prev_count = len(merged_blocks)
        await _scroll_jssdk_container(page)
        for _ in range(6):
            await page.wait_for_timeout(2000)
            if len(merged_blocks) > prev_count:
                break
        if len(merged_blocks) == prev_count:
            break
        logger.debug("Feishu blocks still arriving: %d → %d", prev_count, len(merged_blocks))

    page.remove_listener("response", _on_client_vars_response)
    page.remove_listener("response", _on_any_api_response)

    await _refresh_sequence_from_window_data(page, merged_sequence)
    await _apply_dom_block_order(page, merged_sequence, merged_blocks)

    if api_urls_seen:
        logger.info("Feishu direct: intercepted %d API calls:", len(api_urls_seen))
        for u in api_urls_seen[:15]:
            logger.info("  → %s", u)

    if not merged_blocks:
        logger.warning("Feishu direct: no block data obtained")
        return None

    # Log block type distribution for diagnostics
    type_counts: dict[str, int] = {}
    for _bid, _blk in merged_blocks.items():
        _bt = (_blk.get("data") or {}).get("type", "unknown")
        type_counts[_bt] = type_counts.get(_bt, 0) + 1
    logger.info("Feishu direct: block types: %s", type_counts)
    _dump_block_map(merged_blocks, "_debug_latest", "feishu_direct")

    doc = _parse_block_map(merged_blocks, sequence=merged_sequence or None)
    if not doc or len(doc.get("text", "")) < 30:
        logger.warning(
            "Feishu direct: block parsing yielded only %d text chars from %d blocks",
            len(doc.get("text", "") if doc else ""), len(merged_blocks),
        )
        if not doc:
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
    downloaded_tokens: set[str] = set()  # dedup: skip tokens already downloaded

    for alt_text, cdn_url in matches:
        token_match = re.search(r"/cover/([^/?]+)", cdn_url)
        token = token_match.group(1) if token_match else hashlib.sha256(
            cdn_url.encode("utf-8", errors="ignore")
        ).hexdigest()[:20]

        # Dedup: if we already downloaded this token, just rewrite the URL
        if token in downloaded_tokens:
            existing = list(img_dir.glob(f"{token}.*"))
            if existing:
                local_url = f"/api/omni/knowledge/harvester/images/{job_id}/{existing[0].name}"
                markdown = markdown.replace(cdn_url, local_url)
                saved += 1
            continue
        downloaded_tokens.add(token)

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
        "progress_hint": 0.0,
        "total": 1,
        "chapters": [],
        "current_article": None,
        "graph_name": "飞书文档",
        "total_articles": 1,
        "error": None,
        "activity_log": [],
        "text_preview": "",
        "cancel_requested": False,
    }
    _jobs[job_id] = job
    _job_log(job, "飞书文档任务已创建", snippet=url)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        job.update({"status": "failed", "error": "Playwright not installed"})
        return job

    try:
        job["status"] = "extracting_browser"
        job["current_article"] = {"index": 0, "title": "正在提取飞书文档...", "graph_path": url}
        _job_log(job, "正在启动无头浏览器并打开文档…")

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=list(_CHROMIUM_HEADLESS_ARGS),
        )

        ctx_kwargs: dict = {}
        if auth_state_path and Path(auth_state_path).exists():
            ctx_kwargs["storage_state"] = auth_state_path
        ctx = await browser.new_context(**ctx_kwargs)

        cdn_url_data: dict[str, dict] = {}
        page = await ctx.new_page()

        async def _block_heavy(route):
            if _HARVESTER_ROUTE_ABORT_RE.search(route.request.url):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _block_heavy)

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

        _job_touch(job, "拉取飞书正文与块数据…", 0.05)
        doc = await _extract_feishu_direct(page, url, cdn_url_data)

        page.remove_listener("response", _on_cdn_response)

        if doc:
            md = doc["markdown"]
            _job_publish_body_before_media(job, md)
            img_saved = img_total = img_analyzed = vid_analyzed = 0

            if _HARVESTER_TEXT_AND_TABLES_ONLY:
                _job_touch(job, "仅正文+表格模式：跳过图片下载 / AI 图解读 / 短视频分析", 0.55)
                md = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", md)
            else:
                if _IMG_RE.search(md):
                    md, img_saved, img_total = await _download_images_via_browser(
                        page, md, job_id, 0,
                    )

                    # Always try CDN decrypt fallback for any remaining unresolved images
                    remaining_tokens = set()
                    for _, u in _IMG_RE.findall(md):
                        tm = re.search(r"/cover/([^/?]+)", u)
                        if tm:
                            remaining_tokens.add(tm.group(1))
                    if remaining_tokens:
                        logger.info("Browser download left %d unresolved images, trying CDN decrypt fallback", len(remaining_tokens))
                        decrypted = await _download_encrypted_images(cdn_url_data, remaining_tokens, job_id)
                        md, extra_saved, _ = _save_captured_images(decrypted, md, job_id, 0)
                        img_saved += extra_saved

                    if img_saved > 0:
                        from app.config import settings as _cfg
                        _job_touch(job, f"准备 AI 解读 {img_saved} 张图片…", 0.2)
                        md, img_analyzed = await _auto_analyze_and_merge(
                            job_id, md, _cfg.ai_provider_hub_url, job=job,
                        )

                md = clean_image_markdown(md)

                # Screenshot embedded content (画板, 思维导图, PPT, etc.)
                if _EMBEDDED_PLACEHOLDER_RE.search(md):
                    _job_touch(job, "截图嵌入内容(画板/思维导图/PPT)…", 0.7)
                    md, embed_count = await _screenshot_embedded_content(ctx, md, job_id, job=job)
                    if embed_count > 0:
                        _job_touch(job, f"AI 解读 {embed_count} 个嵌入截图…", 0.75)
                        from app.config import settings as _cfg
                        md, extra_analyzed = await _auto_analyze_and_merge(
                            job_id, md, _cfg.ai_provider_hub_url, job=job,
                        )
                        img_analyzed += extra_analyzed
                        img_saved += embed_count

                from app.config import settings as _cfg
                _job_touch(job, "检查视频链接…", 0.85)
                md, vid_analyzed = await _auto_analyze_videos_in_markdown(
                    md, _cfg.video_analysis_service_url, auth_state_path,
                    job=job, browser_page=page,
                )
            plain = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", md)

            job["chapters"].append({
                "index": 0,
                "title": doc["title"],
                "graph_path": doc["title"],
                "markdown": md,
                "text": plain,
                "word_count": len(plain),
                "block_count": doc["block_count"],
                "source_url": url,
                "images": {"downloaded": img_saved, "total": img_total, "analyzed": img_analyzed},
                "videos": {"analyzed": vid_analyzed},
            })
            logger.info("Feishu doc crawled: %s — %d chars, %d/%d images, %d analyzed, %d videos",
                        doc["title"], len(plain), img_saved, img_total, img_analyzed, vid_analyzed)
            _job_log(
                job,
                f"飞书采集完成：《{doc['title']}》— {len(plain)} 字，图 {img_saved}/{img_total}，"
                f"图解读 {img_analyzed}，视频解读 {vid_analyzed}",
                snippet=plain[:500],
            )
            _job_set_text_preview(job, plain)
        else:
            final_url = page.url
            is_login = "login" in final_url.lower() or "passport" in final_url.lower()
            _job_log(
                job,
                "飞书正文提取失败（可能需登录或页面结构变化）",
                snippet=final_url,
            )
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

        job.update({"status": "done", "progress": 1, "progress_hint": 0.0, "current_article": None})
        _job_log(job, "飞书文档任务完成")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception("Feishu doc crawl failed")
        job.update({
            "status": "failed",
            "error": f"{type(e).__name__}: {e}\n{tb}",
            "current_article": None,
            "progress_hint": 0.0,
        })
        _job_log(job, f"飞书任务异常：{type(e).__name__}: {e}")

    return job


def _parse_single_article_url(url: str) -> dict | None:
    """Detect a single-article URL and extract mapping_id + graph query params.

    Supported shapes:
      https://yuntu.oceanengine.com/support/content/142334?graphId=...&mappingType=2&...
      https://support.oceanengine.com/help/content/206669?graphId=...&mappingType=2&...
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


# SSR may return JSON string "null" instead of real HTML/markdown — do not ingest as text.
_FEISHU_BROWSER_CONTENT_TYPES = (
    "feishu_docx_new_import",
    "feishu_docx_light_import_wiki_root",
)


def _ssr_raw_content_is_placeholder(raw: object) -> bool:
    if raw is None:
        return True
    s = str(raw).strip()
    if not s:
        return True
    return s.lower() in ("null", "none", "undefined")


def _article_browse_url(seed_url: str, mid: str, gid: str, pid: str, sid: str) -> str:
    """Open the same article on the host the user started from (support vs yuntu)."""
    host = (urlparse(seed_url).hostname or "").lower()
    gid_q = f"graphId={gid}&" if gid else ""
    if host.endswith("support.oceanengine.com"):
        return (
            f"https://support.oceanengine.com/help/content/{mid}"
            f"?{gid_q}pageId={pid}&spaceId={sid}&mappingType=2"
        )
    yq = f"{gid_q}pageId={pid}&spaceId={sid}" if gid else f"pageId={pid}&spaceId={sid}"
    return f"https://yuntu.oceanengine.com/support/content/{mid}?{yq}"


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
        "progress_hint": 0.0,
        "total": 0,
        "chapters": [],
        "current_article": None,
        "graph_name": "",
        "total_articles": 0,
        "error": None,
        "activity_log": [],
        "text_preview": "",
        "cancel_requested": False,
    }
    _jobs[job_id] = job
    _job_log(job, "任务已创建，正在解析 URL / 获取目录…")

    try:
        articles: list[dict] = []
        gid, pid, sid = "", "", ""
        tree_cache: dict | None = None

        single = _parse_single_article_url(url)
        if single and not selected_articles and single.get("page_id") and single.get("space_id"):
            try:
                tree_cache = await fetch_nav_tree(url)
                if (tree_cache.get("total_articles") or 0) > 1:
                    articles = list(tree_cache["articles"])
                    if max_pages:
                        articles = articles[:max_pages]
                    job["graph_name"] = tree_cache.get("graph_name") or "帮助中心"
                    job["total_articles"] = tree_cache["total_articles"]
                    job["total"] = len(articles)
                    gid = single["graph_id"] or str(tree_cache.get("graph_id") or "")
                    pid, sid = single["page_id"], single["space_id"]
                    single = None
                    logger.info(
                        "单篇链接已展开为整站目录：共 %d 篇文章（将按「爬取全部」处理）",
                        len(articles),
                    )
            except Exception as exc:
                logger.info("目录展开跳过，按单篇处理: %s", exc)

        if not articles and selected_articles:
            # selected_articles takes priority over single-article URL parsing
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
        elif not articles and single:
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
        elif not articles:
            tree = tree_cache if tree_cache is not None else await fetch_nav_tree(url)
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
        _job_log(
            job,
            f"目录就绪：{job.get('graph_name') or '帮助中心'}，共 {len(articles)} 篇"
            + ("（已登录 Cookie）" if has_auth else "（未配置 Cookie，部分页可能失败）"),
        )

        # Phase 1: Try SSR API extraction (no browser needed, fast)
        job["status"] = "extracting_api"
        _job_log(job, "阶段 1/2：SSR/API 拉取正文（无需浏览器）…")
        api_extracted: set[int] = set()
        feishu_doc_specs: dict[int, tuple[str, str]] = {}
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HEADERS) as client:
            for idx, article in enumerate(articles):
                if job.get("cancel_requested"):
                    _job_log(job, "已在 API 阶段停止采集（用户结束任务）")
                    break
                title = article["title"]
                mid = article["mapping_id"]
                job["progress"] = idx
                job["current_article"] = {
                    "index": idx, "title": title, "graph_path": article["graph_path"],
                }

                _job_log(
                    job,
                    f"API [{idx + 1}/{len(articles)}] 《{title}》",
                    snippet=f"mapping_id={mid}",
                )
                ssr = await _fetch_article_ssr(client, mid, gid, pid, sid, seed_url=url)
                if ssr:
                    raw_content = ssr.get("content")
                    content = "" if raw_content is None else str(raw_content)
                    content_type = ssr.get("contentType", "")

                    api_title = ssr.get("name")
                    if isinstance(api_title, str) and api_title.strip():
                        article["title"] = api_title.strip()
                        title = article["title"]

                    can_use_ssr_text = (
                        content.strip()
                        and not _ssr_raw_content_is_placeholder(raw_content)
                        and content_type not in _FEISHU_BROWSER_CONTENT_TYPES
                    )
                    if can_use_ssr_text:
                        content = clean_ssr_content(content)
                        if content.strip():
                            src = _article_browse_url(url, mid, gid, pid, sid)
                            job["chapters"].append({
                                "index": idx,
                                "title": title,
                                "graph_path": article["graph_path"],
                                "markdown": content,
                                "text": content,
                                "word_count": len(content),
                                "block_count": 1,
                                "source_url": src,
                            })
                            api_extracted.add(idx)
                            logger.info("Harvester API [%d/%d] %s — %d chars", idx + 1, len(articles), title, len(content))
                            _job_log(
                                job,
                                f"API 成功 [{idx + 1}/{len(articles)}] 《{title}》— {len(content)} 字",
                                snippet=content[:500],
                            )
                            _job_set_text_preview(job, content)
                            continue

                is_jssdk = bool(
                    ssr
                    and ssr.get("contentType") in _FEISHU_BROWSER_CONTENT_TYPES
                    and (
                        ssr.get("contentType") == "feishu_docx_new_import"
                        or bool(ssr.get("feishuDocxToken"))
                    )
                )
                needs_browser = has_auth or is_jssdk

                if is_jssdk and ssr:
                    docx_token = ssr.get("feishuDocxToken", "")
                    if docx_token:
                        feishu_doc_specs[idx] = (docx_token, str(ssr.get("contentType") or ""))
                        logger.info("Harvester [%d/%d] %s — feishuDocxToken=%s", idx + 1, len(articles), title, docx_token)

                job["chapters"].append({
                    "index": idx,
                    "title": title,
                    "graph_path": article["graph_path"],
                    "markdown": "",
                    "text": "",
                    "word_count": 0,
                    "error": "pending_browser" if needs_browser else "needs_auth",
                })
                logger.info("Harvester [%d/%d] %s — %s%s", idx + 1, len(articles), title,
                            "queued for browser" if needs_browser else "needs auth",
                            " (JSSDK)" if is_jssdk else "")
                if needs_browser:
                    _job_log(
                        job,
                        f"排队浏览器 [{idx + 1}/{len(articles)}] 《{title}》"
                        + ("（飞书 JSSDK）" if is_jssdk else ""),
                    )
                else:
                    _job_log(job, f"跳过 [{idx + 1}/{len(articles)}] 《{title}》— 需要登录 Cookie")

        # Phase 2: Browser extraction for pending articles (auth or JSSDK)
        browser_queue = [ch for ch in job["chapters"] if ch.get("error") == "pending_browser"]
        if browser_queue and not job.get("cancel_requested"):
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                job.update({"status": "done", "progress": len(articles), "current_article": None})
                return job

            job["status"] = "extracting_browser"
            _job_log(job, f"阶段 2/2：浏览器提取，共 {len(browser_queue)} 篇…")
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(
                headless=True,
                args=list(_CHROMIUM_HEADLESS_ARGS),
            )
            ctx_kwargs: dict = {}
            if has_auth:
                ctx_kwargs["storage_state"] = auth_state_path
            ctx = await browser.new_context(**ctx_kwargs)

            # Inject feishu cookies so direct larkoffice.com extraction works
            from app.config import settings as _cfg
            _feishu_path = Path(_cfg.feishu_auth_state)
            if _feishu_path.exists():
                try:
                    _feishu_state = json.loads(_feishu_path.read_text())
                    _feishu_cookies = _feishu_state.get("cookies", [])
                    if _feishu_cookies:
                        await ctx.add_cookies(_feishu_cookies)
                        logger.info("Loaded %d feishu cookies into browser context", len(_feishu_cookies))
                except Exception:
                    logger.warning("Failed to load feishu cookies", exc_info=True)

            page = await ctx.new_page()

            async def _block_heavy(route):
                if _HARVESTER_ROUTE_ABORT_RE.search(route.request.url):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", _block_heavy)

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
                if job.get("cancel_requested"):
                    _job_log(job, "已在浏览器阶段停止采集（用户结束任务）")
                    break
                if idx in api_extracted:
                    continue

                title = article["title"]
                mid = article["mapping_id"]
                job["progress"] = idx
                job["progress_hint"] = 0.0
                job["current_article"] = {
                    "index": idx, "title": title, "graph_path": article["graph_path"],
                }

                article_url = _article_browse_url(url, mid, gid, pid, sid)
                _job_log(
                    job,
                    f"浏览器 [{idx + 1}/{len(articles)}] 《{title}》",
                    snippet=article_url,
                )

                doc = None
                auth_expired = False

                # Primary path: feishuDocxToken from SSR — try tenant + wiki/docx URL order.
                if idx in feishu_doc_specs:
                    docx_token, feishu_ct = feishu_doc_specs[idx]
                    for feishu_url in _lark_embed_urls(docx_token, feishu_ct):
                        logger.info("Harvester [%d/%d] %s — direct Feishu extraction: %s",
                                    idx + 1, len(articles), title, feishu_url)
                        _job_touch(job, "直连飞书 Doc 拉取正文…", 0.04)
                        doc = await _extract_feishu_direct(page, feishu_url, cdn_url_data)
                        if doc:
                            break

                # Fallback: standard yuntu page JSSDK extraction
                if not doc:
                    _job_touch(job, "帮助中心页面 + iframe 提取正文…", 0.08)
                    for attempt in range(2):
                        doc = await _extract_feishu_via_browser(
                            page, article_url, cdn_url_data,
                        )
                        if isinstance(doc, dict) and doc.get("_error") == "auth_expired":
                            auth_expired = True
                            doc = None
                            break
                        if doc:
                            break
                        await page.wait_for_timeout(2000)

                if auth_expired:
                    job["chapters"].append({
                        "index": idx,
                        "title": title,
                        "graph_path": article["graph_path"],
                        "markdown": "",
                        "text": "",
                        "word_count": 0,
                        "error": "auth_expired",
                    })
                    logger.warning("Harvester Browser [%d/%d] %s — auth expired, need re-login", idx + 1, len(articles), title)
                    _job_log(job, f"认证失效 [{idx + 1}/{len(articles)}] 《{title}》— 请重新浏览器登录")
                    continue

                # --- Full-page DOM supplement: capture text outside the iframe ---
                # The help center page may render part of the document OUTSIDE the
                # Feishu iframe (e.g. server-rendered or via a different JS loader).
                if doc:
                    try:
                        full_page_text = await page.evaluate("""async () => {
                            const sleep = ms => new Promise(r => setTimeout(r, ms));
                            // Scroll the outer page from top to bottom to load lazy content
                            const el = document.scrollingElement || document.documentElement;
                            el.scrollTo(0, 0);
                            await sleep(500);
                            const h = Math.max(el.scrollHeight, 30000);
                            const step = Math.max(600, Math.floor(window.innerHeight * 0.7));
                            for (let y = 0; y <= h; y += step) {
                                el.scrollTo(0, y);
                                await sleep(80);
                            }
                            el.scrollTo(0, 0);
                            await sleep(300);
                            // Get text from the content area (skip nav/footer)
                            const content = document.querySelector('[class*="article"]')
                                || document.querySelector('[class*="content-detail"]')
                                || document.querySelector('[class*="detail"]')
                                || document.querySelector('main')
                                || document.body;
                            return content ? content.innerText : '';
                        }""")
                        if full_page_text:
                            block_text = doc.get("text", "") or doc.get("markdown", "")
                            block_lower = block_text.lower()
                            page_lines = full_page_text.strip().split("\n")
                            missing_lines: list[str] = []
                            for line in page_lines:
                                stripped = line.strip()
                                if not stripped or len(stripped) < 6:
                                    continue
                                if stripped.lower() not in block_lower:
                                    missing_lines.append(stripped)
                            if len(missing_lines) > 10:
                                supplement = "\n\n".join(missing_lines)
                                doc["markdown"] = supplement + "\n\n---\n\n" + doc["markdown"]
                                doc["text"] = supplement + "\n\n" + doc.get("text", "")
                                logger.info("Full-page DOM supplement: added %d lines (%d chars)",
                                            len(missing_lines), len(supplement))
                            else:
                                logger.info("Full-page DOM supplement: page text %d chars, no significant new content",
                                            len(full_page_text))
                    except Exception as e:
                        logger.debug("Full-page DOM supplement failed: %s", e)

                if doc:
                    md = doc["markdown"]
                    _job_publish_body_before_media(job, md)
                    img_saved = 0
                    img_total = 0
                    img_analyzed = 0
                    vid_analyzed = 0

                    if _HARVESTER_TEXT_AND_TABLES_ONLY:
                        _job_touch(job, "仅正文+表格模式：跳过图片下载 / AI 图解读 / 短视频分析", 0.55)
                        md = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", md)
                    else:
                        if _IMG_RE.search(md):
                            _job_touch(job, "下载并解密图片…", 0.12)
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

                            if _IMG_RE.search(md):
                                _job_touch(job, "浏览器会话补拉剩余图片…", 0.14)
                                md, extra_saved, extra_total = await _download_images_via_browser(
                                    page, md, job_id, idx,
                                )
                                img_saved += extra_saved

                        if img_saved > 0:
                            from app.config import settings as _cfg
                            _job_touch(job, f"准备 AI 解读 {img_saved} 张图片…", 0.16)
                            md, img_analyzed = await _auto_analyze_and_merge(
                                job_id, md, _cfg.ai_provider_hub_url, job=job,
                            )
                        else:
                            _job_touch(job, "无本地图片，跳过图解读", 0.75)

                        md = clean_image_markdown(md)

                        # Screenshot embedded content (画板, 思维导图, PPT, etc.)
                        if _EMBEDDED_PLACEHOLDER_RE.search(md):
                            _job_touch(job, "截图嵌入内容(画板/思维导图/PPT)…", 0.7)
                            md, embed_count = await _screenshot_embedded_content(ctx, md, job_id, job=job)
                            if embed_count > 0:
                                _job_touch(job, f"AI 解读 {embed_count} 个嵌入截图…", 0.75)
                                from app.config import settings as _cfg
                                md, extra_analyzed = await _auto_analyze_and_merge(
                                    job_id, md, _cfg.ai_provider_hub_url, job=job,
                                )
                                img_analyzed += extra_analyzed
                                img_saved += embed_count

                        from app.config import settings as _cfg
                        _job_touch(job, "检查正文中的视频链接…", 0.8)
                        md, vid_analyzed = await _auto_analyze_videos_in_markdown(
                            md,
                            _cfg.video_analysis_service_url,
                            auth_state_path if has_auth else None,
                            job=job,
                            browser_page=page,
                        )
                    plain = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", md)

                    doc_title = (doc.get("title") or "").strip()
                    if doc_title:
                        title = doc_title

                    job["chapters"].append({
                        "index": idx,
                        "title": title,
                        "graph_path": article["graph_path"],
                        "markdown": md,
                        "text": plain,
                        "word_count": len(plain),
                        "block_count": doc["block_count"],
                        "source_url": article_url,
                        "images": {"downloaded": img_saved, "total": img_total, "analyzed": img_analyzed},
                        "videos": {"analyzed": vid_analyzed},
                    })
                    _job_log(
                        job,
                        f"完成 [{idx + 1}/{len(articles)}] 《{title}》— {len(plain)} 字，图 {img_saved}/{img_total}，"
                        f"图解读 {img_analyzed}，视频解读 {vid_analyzed}",
                        snippet=plain[:500],
                    )
                    _job_set_text_preview(job, plain)
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
                    _job_log(job, f"失败 [{idx + 1}/{len(articles)}] 《{title}》— 未能提取正文")

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

        # Drop queued-but-never-fetched placeholders if user cancelled mid-flight
        if job.get("cancel_requested"):
            job["chapters"] = [
                ch for ch in job["chapters"]
                if ch.get("error") != "pending_browser"
            ]

        # Sort chapters by index for consistent order
        job["chapters"].sort(key=lambda c: c["index"])

        job.update({
            "status": "done",
            "progress": len(articles),
            "progress_hint": 0.0,
            "current_article": None,
        })
        user_stopped = bool(job.pop("cancel_requested", False))
        if user_stopped:
            _job_log(
                job,
                f"任务已结束（用户停止），保留 {len(job['chapters'])} 条章节，可去审核页勾选入库",
            )
        else:
            _job_log(job, "全部采集完成")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception("Harvester crawl failed")
        job.update({
            "status": "failed",
            "error": f"{type(e).__name__}: {e}\n{tb}",
            "current_article": None,
            "progress_hint": 0.0,
        })
        _job_log(job, f"任务异常终止：{type(e).__name__}: {e}")

    return job


# ═══ Local extraction upload ═══

async def ingest_extracted_page(
    url: str,
    title: str,
    markdown: str,
    images: list[dict],
    block_map: dict | None = None,
) -> dict:
    """Process content uploaded by the local browser_extract.py script.

    Saves images, rewrites img URLs to local references, runs LLM analysis,
    and stores the result as a job visible in the frontend.
    """
    import base64

    job_id = str(uuid4())
    img_dir = IMAGE_DIR / job_id
    img_dir.mkdir(parents=True, exist_ok=True)

    img_saved = 0
    img_analyzed = 0
    vid_analyzed = 0
    img_map: dict[str, str] = {}

    if _HARVESTER_TEXT_AND_TABLES_ONLY:
        markdown = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown)
    else:
        for i, img in enumerate(images):
            data_b64 = img.get("data_b64", "")
            if not data_b64:
                continue
            try:
                data = base64.b64decode(data_b64)
            except Exception:
                continue
            if len(data) < 500:
                continue

            src = img.get("src", "")
            ext = "png"
            for try_ext in ("jpg", "jpeg", "png", "gif", "webp"):
                if try_ext in src.lower():
                    ext = try_ext
                    break

            filename = f"img_{i:03d}.{ext}"
            (img_dir / filename).write_bytes(data)
            img_map[src] = filename
            img_saved += 1

        for orig_src, local_name in img_map.items():
            local_url = f"/api/omni/knowledge/harvester/images/{job_id}/{local_name}"
            escaped = re.escape(orig_src)
            pat = re.compile(r"!\[([^\]]*)\]\(" + escaped + r"\)")
            m = pat.search(markdown)
            if m:
                alt = m.group(1)
                markdown = pat.sub(f"![{alt}]({local_url})", markdown)
            else:
                markdown += f"\n\n![image]({local_url})"

        if img_saved > 0:
            from app.config import settings as _cfg
            markdown, img_analyzed = await _auto_analyze_and_merge(
                job_id, markdown, _cfg.ai_provider_hub_url,
            )
            markdown = clean_image_markdown(markdown)

        from app.config import settings as _cfg
        markdown, vid_analyzed = await _auto_analyze_videos_in_markdown(
            markdown, _cfg.video_analysis_service_url, None,
        )

    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown)

    job = {
        "status": "done",
        "progress": 1,
        "total": 1,
        "chapters": [{
            "index": 0,
            "title": title,
            "graph_path": title,
            "markdown": markdown,
            "text": text,
            "word_count": len(text),
            "block_count": 1,
            "source_url": url,
            "images": {
                "downloaded": img_saved,
                "total": len(images),
                "analyzed": img_analyzed,
            },
            "videos": {"analyzed": vid_analyzed},
        }],
        "current_article": None,
        "graph_name": "本机提取",
        "total_articles": 1,
        "error": None,
    }
    _jobs[job_id] = job

    global _last_upload_job_id
    _last_upload_job_id = job_id

    logger.info(
        "ingest_extracted_page: job=%s title=%s chars=%d images=%d/%d analyzed=%d videos=%d",
        job_id, title, len(text), img_saved, len(images), img_analyzed, vid_analyzed,
    )

    return {
        "job_id": job_id,
        "word_count": len(text),
        "images_saved": img_saved,
        "images_analyzed": img_analyzed,
        "videos_analyzed": vid_analyzed,
    }
