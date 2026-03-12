"""Document text extraction — PDF, DOCX, HTML, Markdown, plain text."""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".html", ".htm", ".srt"}


def detect_content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mapping = {
        "txt": "text",
        "md": "markdown",
        "pdf": "pdf",
        "docx": "docx",
        "html": "html",
        "htm": "html",
        "srt": "srt",
    }
    return mapping.get(ext, "text")


def extract_text(content: bytes, filename: str) -> str:
    """Extract plain text from file bytes based on filename extension."""
    content_type = detect_content_type(filename)
    extractors = {
        "text": _extract_plain,
        "markdown": _extract_plain,
        "pdf": _extract_pdf,
        "docx": _extract_docx,
        "html": _extract_html,
        "srt": _extract_srt,
    }
    extractor = extractors.get(content_type, _extract_plain)
    try:
        return extractor(content)
    except Exception:
        logger.exception("Failed to extract text from %s, falling back to plain", filename)
        return _extract_plain(content)


def _extract_plain(content: bytes) -> str:
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _extract_pdf(content: bytes) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=content, filetype="pdf")
    pages = []
    for page in doc:
        pages.append(page.get_text("text"))
    doc.close()
    return "\n\n".join(pages)


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    return "\n\n".join(para.text for para in doc.paragraphs if para.text.strip())


def _extract_html(content: bytes) -> str:
    try:
        from trafilatura import extract

        text = extract(content.decode("utf-8", errors="replace"))
        if text:
            return text
    except Exception:
        pass
    return _extract_plain(content)


def _extract_srt(content: bytes) -> str:
    import pysrt

    subs = pysrt.from_string(_extract_plain(content))
    return "\n".join(f"[{sub.start} --> {sub.end}] {sub.text}" for sub in subs)
