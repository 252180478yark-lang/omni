"""Chinese text segmentation using jieba for PostgreSQL full-text search.

The built-in PostgreSQL 'simple' text search config treats continuous CJK
characters as a single token, making fulltext search useless for Chinese.

This module segments Chinese text with jieba so that each word becomes a
separate token in the tsvector, enabling proper Chinese fulltext matching.
"""

from __future__ import annotations

import logging
import re

import jieba

logger = logging.getLogger(__name__)

# Detect CJK Unified Ideographs
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# Pre-load jieba dictionary at import time (takes ~1s, only once)
jieba.setLogLevel(logging.WARNING)
jieba.initialize()


def contains_chinese(text: str) -> bool:
    """Return True if text contains any Chinese characters."""
    return bool(_CJK_RE.search(text))


def segment_for_search(text: str) -> str:
    """Segment text for PostgreSQL tsvector storage.

    For Chinese text, uses jieba.cut_for_search (fine-grained mode) to split
    into words separated by spaces.  Non-Chinese text is returned as-is since
    the 'simple' config already handles space-delimited languages correctly.

    Example:
        "投放策略优化指南" → "投放 策略 优化 指南 投放策略 策略优化 优化指南"
    """
    if not text or not contains_chinese(text):
        return text

    words = jieba.cut_for_search(text)
    return " ".join(w.strip() for w in words if w.strip())


def segment_query(query: str) -> str:
    """Segment a search query for plainto_tsquery.

    Uses jieba.cut_for_search so that both short and long word forms
    are included, maximising recall against the segmented tsvector.
    """
    if not query or not contains_chinese(query):
        return query

    words = jieba.cut_for_search(query)
    return " ".join(w.strip() for w in words if w.strip())
