"""Content cleaner for knowledge base ingestion.

Sanitises raw harvester/upload content before chunking and embedding.
Removes base64 data URIs, garbled text, unresolved CDN URLs, HTML artifacts,
and other noise that degrades retrieval quality.
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ── Base64 / binary noise ────────────────────────────────────────────────

_BASE64_DATA_URI = re.compile(
    r"['\"]?data:[a-zA-Z]+/[a-zA-Z0-9+._-]+;base64,"
    r"[A-Za-z0-9+/=\s]{50,}['\"]?",
    re.DOTALL,
)

_LONG_BASE64_BLOB = re.compile(
    r"(?<![A-Za-z0-9/])"
    r"[A-Za-z0-9+/]{200,}={0,3}"
    r"(?![A-Za-z0-9/])",
)

# ── Unresolved image CDN URLs ────────────────────────────────────────────

_UNRESOLVED_CDN_IMG = re.compile(
    r"!\[([^\]]*)\]\((https://internal-api-drive-stream[^)]+)\)"
)

# ── Mock / failed AI analysis responses ──────────────────────────────────

_MOCK_AI_RESPONSE = re.compile(
    r">\s*\*\*\[图片内容\]\*\*\s*\[?(?:anthropic-mock|mock|error|failed)"
    r"[^\n]*(?:\n[^\n]*){0,5}",
    re.IGNORECASE,
)

_RAW_PROMPT_LEAK = re.compile(
    r"\[?\{['\"]type['\"]:\s*['\"]text['\"],\s*['\"]text['\"]:\s*['\"]"
    r"请用中文详细描述这张图片[^}]*\}[^\]]*\]?",
)

# ── HTML fragments ───────────────────────────────────────────────────────

_HTML_BLOCK_TAGS = re.compile(
    r"<(?:script|style|noscript|svg|canvas)[^>]*>.*?</(?:script|style|noscript|svg|canvas)>",
    re.DOTALL | re.IGNORECASE,
)

_HTML_INLINE_TAGS = re.compile(r"</?(?:div|span|p|br|img|a|b|i|u|em|strong|font|center|section|article|header|footer|nav|main|aside|figure|figcaption|video|source|iframe|object|embed|param|link|meta|head|html|body)[^>]*>", re.IGNORECASE)

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

_HTML_ATTR_STYLE = re.compile(r'\s+(?:style|class|id|data-\w+)="[^"]*"', re.IGNORECASE)

# ── Garbled / encoding artifacts ─────────────────────────────────────────

_GARBLED_CJK = re.compile(
    r"(?:[\u3400-\u4DBF\uE000-\uF8FF]){5,}"
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]+")

# ── Whitespace normalisation ─────────────────────────────────────────────

_EXCESSIVE_NEWLINES = re.compile(r"\n{4,}")
_EXCESSIVE_SPACES = re.compile(r"[^\S\n]{4,}")

# ── JSON / JavaScript fragments ──────────────────────────────────────────

_JS_OBJECT_DUMP = re.compile(
    r"\{['\"](?:type|content|role|model)['\"]:[^}]{100,}\}",
)


def clean_for_ingestion(text: str, *, preserve_tables: bool = True) -> str:
    """Main cleaning entry-point for the ingestion pipeline.

    Runs all cleaning passes in order.  When *preserve_tables* is True
    (default), markdown tables are shielded during HTML stripping.
    """
    if not text or not text.strip():
        return ""

    original_len = len(text)

    text = _strip_base64(text)
    text = _strip_mock_responses(text)
    text = _clean_image_references(text)
    text = _strip_html(text, preserve_tables=preserve_tables)
    text = _strip_garbled(text)
    text = _strip_js_fragments(text)
    text = _normalise_whitespace(text)

    cleaned_len = len(text)
    if original_len > 0 and cleaned_len < original_len:
        removed_pct = (1 - cleaned_len / original_len) * 100
        if removed_pct > 5:
            logger.info(
                "Content cleaner: %d → %d chars (removed %.1f%%)",
                original_len, cleaned_len, removed_pct,
            )

    return text.strip()


def clean_ssr_content(content: str) -> str:
    """Clean raw SSR API content (may be HTML or semi-structured text)."""
    if not content or not content.strip():
        return ""

    if _looks_like_html(content):
        content = _html_to_text(content)

    return clean_for_ingestion(content)


def clean_image_markdown(markdown: str) -> str:
    """Turn unresolved Feishu stream image URLs into markdown links (keeps URL for tables/RAG).

    Replacing with plain ``[图片]`` drops the link entirely and makes table cells look empty;
    keeping ``[alt](url)`` preserves the source for re-fetch with auth or display.
    """
    def _replace_cdn_img(m: re.Match) -> str:
        alt = m.group(1).strip()
        url = m.group(2).strip()
        label = alt if alt and alt not in ("image", "image.png", "img") else "图片"
        return f"[{label}]({url})"

    return _UNRESOLVED_CDN_IMG.sub(_replace_cdn_img, markdown)


def validate_image_description(description: str) -> str | None:
    """Return the description only if it looks like valid LLM output."""
    if not description or len(description.strip()) < 10:
        return None
    bad_signals = (
        "anthropic-mock", "[mock]", "error", "ai_hub_",
        "data:image/", "base64,", "{'type':", '{"type":',
        "请用中文详细描述这张图片",
    )
    lower = description.lower()
    for signal in bad_signals:
        if signal.lower() in lower:
            return None
    return description.strip()


# ═══ Internal passes ═══


def _strip_base64(text: str) -> str:
    text = _BASE64_DATA_URI.sub("[base64图片数据已移除]", text)
    text = _LONG_BASE64_BLOB.sub("", text)
    return text


def _strip_mock_responses(text: str) -> str:
    text = _MOCK_AI_RESPONSE.sub("", text)
    text = _RAW_PROMPT_LEAK.sub("", text)
    return text


def _clean_image_references(text: str) -> str:
    return clean_image_markdown(text)


def _strip_html(text: str, *, preserve_tables: bool = True) -> str:
    table_placeholders: list[tuple[str, str]] = []
    if preserve_tables:
        table_re = re.compile(r"(?:^|\n)(\|[^\n]+\|(?:\n\|[^\n]+\|)*)", re.MULTILINE)
        for i, m in enumerate(table_re.finditer(text)):
            placeholder = f"\n__TABLE_PLACEHOLDER_{i}__\n"
            table_placeholders.append((placeholder, m.group(0)))
            text = text.replace(m.group(0), placeholder, 1)

    text = _HTML_COMMENT.sub("", text)
    text = _HTML_BLOCK_TAGS.sub("", text)
    text = _HTML_INLINE_TAGS.sub("", text)
    text = _HTML_ATTR_STYLE.sub("", text)

    for placeholder, original in table_placeholders:
        text = text.replace(placeholder, original)

    return text


def _strip_garbled(text: str) -> str:
    text = _CONTROL_CHARS.sub("", text)

    def _check_garbled(m: re.Match) -> str:
        segment = m.group(0)
        if len(segment) > 10:
            return ""
        return segment

    text = _GARBLED_CJK.sub(_check_garbled, text)
    return text


def _strip_js_fragments(text: str) -> str:
    return _JS_OBJECT_DUMP.sub("", text)


def _normalise_whitespace(text: str) -> str:
    text = _EXCESSIVE_NEWLINES.sub("\n\n\n", text)
    text = _EXCESSIVE_SPACES.sub(" ", text)
    lines = text.split("\n")
    cleaned_lines = [line.rstrip() for line in lines]
    return "\n".join(cleaned_lines)


def _looks_like_html(text: str) -> bool:
    """Heuristic: does this text look like raw HTML?"""
    text_start = text[:2000].strip()
    if text_start.startswith(("<!DOCTYPE", "<html", "<HTML", "<!doctype")):
        return True
    tag_count = len(re.findall(r"<[a-zA-Z][^>]{0,100}>", text_start))
    return tag_count > 5


def _html_to_text(html: str) -> str:
    """Best-effort HTML → readable text conversion without heavy deps."""
    try:
        import trafilatura
        result = trafilatura.extract(
            html,
            include_tables=True,
            include_links=True,
            include_images=True,
            output_format="txt",
        )
        if result and len(result.strip()) > 50:
            return result
    except Exception:
        pass

    text = _HTML_BLOCK_TAGS.sub("", html)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p[^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:h[1-6])[^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:li)[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:td|th)[^>]*>", " | ", text, flags=re.IGNORECASE)
    text = _HTML_INLINE_TAGS.sub("", text)
    text = _HTML_COMMENT.sub("", text)

    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"&\w+;", "", text)

    return text
