"""Multi-strategy text chunking for RAG pipeline.

Supports: recursive, markdown, sentence, and semantic (paragraph-aware).
Contextual chunk headers prepend document title + section path to each chunk
so embeddings capture hierarchical context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from langchain_text_splitters import (
    MarkdownTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config import settings


class ChunkStrategy(str, Enum):
    RECURSIVE = "recursive"
    MARKDOWN = "markdown"
    SENTENCE = "sentence"
    SEMANTIC = "semantic"


@dataclass(slots=True)
class ChunkData:
    content: str
    chunk_index: int
    metadata: dict[str, object] = field(default_factory=dict)


_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def _extract_section_path(text: str, position: int) -> str:
    """Find the closest heading hierarchy above `position` in the text."""
    headings: list[tuple[int, int, str]] = []
    for m in _HEADING_RE.finditer(text):
        if m.start() <= position:
            level = len(m.group(1))
            headings.append((m.start(), level, m.group(2).strip()))

    if not headings:
        return ""

    stack: list[str] = []
    current_level = 0
    for _, level, title in headings:
        while len(stack) >= level:
            stack.pop()
        stack.append(title)
        current_level = level

    return " > ".join(stack)


def add_contextual_headers(
    chunks: list[ChunkData],
    title: str,
    source_text: str,
) -> list[ChunkData]:
    """Prepend document title and section path to each chunk's content."""
    if not settings.chunk_contextual_headers:
        return chunks

    char_positions: list[int] = []
    search_start = 0
    for chunk in chunks:
        snippet = chunk.content[:80]
        pos = source_text.find(snippet, search_start)
        if pos == -1:
            pos = search_start
        char_positions.append(pos)
        search_start = pos

    for chunk, pos in zip(chunks, char_positions):
        section = _extract_section_path(source_text, pos)
        header_parts = [f"文档: {title}"]
        if section:
            header_parts.append(f"章节: {section}")
        header = " | ".join(header_parts)
        chunk.content = f"[{header}]\n{chunk.content}"
        chunk.metadata["contextual_header"] = header

    return chunks


_TABLE_BLOCK_RE = re.compile(
    r"(?:^|\n)(\|[^\n]+\|(?:\n\|[^\n]+\|)*)",
    re.MULTILINE,
)


def split_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
    strategy: str | ChunkStrategy = ChunkStrategy.RECURSIVE,
) -> list[ChunkData]:
    """Split text into chunks using the specified strategy.

    Tables are protected: if a markdown table fits within chunk_size it will
    never be split across two chunks.
    """
    clean_text = text.strip()
    if not clean_text:
        return []

    size = chunk_size or settings.chunk_size
    lap = overlap or settings.chunk_overlap
    strategy = ChunkStrategy(strategy) if isinstance(strategy, str) else strategy

    if strategy == ChunkStrategy.SEMANTIC:
        return _semantic_split(clean_text, size, lap)

    protected, clean_text = _protect_tables(clean_text, size)

    splitter = _build_splitter(strategy, size, lap)
    docs = splitter.create_documents([clean_text])

    chunks: list[ChunkData] = []
    for idx, doc in enumerate(docs):
        content = _restore_tables(doc.page_content, protected)
        if content.strip():
            chunks.append(ChunkData(
                content=content.strip(),
                chunk_index=idx,
                metadata={"strategy": strategy.value, **doc.metadata},
            ))
    return chunks


def auto_detect_strategy(text: str, filename: str = "") -> ChunkStrategy:
    """Detect the best chunking strategy based on content and filename."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "md" or text.startswith("#") or "\n## " in text:
        return ChunkStrategy.MARKDOWN
    heading_count = len(_HEADING_RE.findall(text))
    if heading_count >= 3:
        return ChunkStrategy.MARKDOWN
    if len(text) > 3000:
        return ChunkStrategy.SEMANTIC
    return ChunkStrategy.RECURSIVE


def _semantic_split(text: str, chunk_size: int, overlap: int) -> list[ChunkData]:
    """Paragraph-aware semantic chunking.

    Groups consecutive paragraphs into chunks, respecting natural boundaries
    (double newlines, heading changes) rather than splitting mid-sentence.
    """
    paragraphs = re.split(r"\n{2,}", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[ChunkData] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        is_heading = para.startswith("#")

        if is_heading and current:
            chunks.append(ChunkData(
                content="\n\n".join(current),
                chunk_index=len(chunks),
                metadata={"strategy": "semantic"},
            ))
            current = [para]
            current_len = para_len
        elif current_len + para_len + 2 > chunk_size and current:
            chunks.append(ChunkData(
                content="\n\n".join(current),
                chunk_index=len(chunks),
                metadata={"strategy": "semantic"},
            ))
            overlap_paras = []
            overlap_len = 0
            for p in reversed(current):
                if overlap_len + len(p) > overlap:
                    break
                overlap_paras.insert(0, p)
                overlap_len += len(p)
            current = overlap_paras + [para]
            current_len = overlap_len + para_len
        else:
            current.append(para)
            current_len += para_len + 2

    if current:
        chunks.append(ChunkData(
            content="\n\n".join(current),
            chunk_index=len(chunks),
            metadata={"strategy": "semantic"},
        ))

    return chunks


def _protect_tables(text: str, chunk_size: int) -> tuple[dict[str, str], str]:
    """Replace markdown tables with single-line placeholders so splitters
    won't break them across chunks.  Returns (placeholder_map, modified_text).
    Tables larger than *chunk_size* are left in-place (they will be split).
    """
    placeholders: dict[str, str] = {}
    for i, m in enumerate(_TABLE_BLOCK_RE.finditer(text)):
        table = m.group(1)
        if len(table) > chunk_size:
            continue
        key = f"__TBL_{i}__"
        placeholders[key] = table
        text = text.replace(table, key, 1)
    return placeholders, text


def _restore_tables(text: str, placeholders: dict[str, str]) -> str:
    for key, table in placeholders.items():
        text = text.replace(key, table)
    return text


def _build_splitter(strategy: ChunkStrategy, chunk_size: int, overlap: int):
    if strategy == ChunkStrategy.MARKDOWN:
        return MarkdownTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    if strategy == ChunkStrategy.SENTENCE:
        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            separators=["\n\n", "。", ".", "！", "!", "？", "?", "\n", " "],
        )
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
    )
