"""Multi-strategy text chunking for RAG pipeline."""

from __future__ import annotations

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


@dataclass(slots=True)
class ChunkData:
    content: str
    chunk_index: int
    metadata: dict[str, object] = field(default_factory=dict)


def split_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
    strategy: str | ChunkStrategy = ChunkStrategy.RECURSIVE,
) -> list[ChunkData]:
    """Split text into chunks using the specified strategy."""
    clean_text = text.strip()
    if not clean_text:
        return []

    size = chunk_size or settings.chunk_size
    lap = overlap or settings.chunk_overlap
    strategy = ChunkStrategy(strategy) if isinstance(strategy, str) else strategy

    splitter = _build_splitter(strategy, size, lap)
    docs = splitter.create_documents([clean_text])

    chunks: list[ChunkData] = []
    for idx, doc in enumerate(docs):
        if doc.page_content.strip():
            chunks.append(ChunkData(
                content=doc.page_content.strip(),
                chunk_index=idx,
                metadata={"strategy": strategy.value, **doc.metadata},
            ))
    return chunks


def auto_detect_strategy(text: str, filename: str = "") -> ChunkStrategy:
    """Detect the best chunking strategy based on content and filename."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "md" or text.startswith("#") or "\n## " in text:
        return ChunkStrategy.MARKDOWN
    return ChunkStrategy.RECURSIVE


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
