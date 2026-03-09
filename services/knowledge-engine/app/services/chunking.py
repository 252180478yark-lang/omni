from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChunkData:
    content: str
    chunk_index: int
    metadata: dict[str, object]


def split_text(text: str, chunk_size: int, overlap: int) -> list[ChunkData]:
    clean_text = text.strip()
    if not clean_text:
        return []
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)

    chunks: list[ChunkData] = []
    start = 0
    idx = 0
    step = max(1, chunk_size - overlap)
    text_len = len(clean_text)
    while start < text_len:
        end = min(text_len, start + chunk_size)
        # Prefer splitting by punctuation/newline to keep sentence boundaries.
        slice_text = clean_text[start:end]
        if end < text_len:
            pivot = max(slice_text.rfind("\n"), slice_text.rfind("。"), slice_text.rfind("."), slice_text.rfind("!"), slice_text.rfind("?"))
            if pivot > int(chunk_size * 0.6):
                end = start + pivot + 1
                slice_text = clean_text[start:end]
        chunks.append(ChunkData(content=slice_text.strip(), chunk_index=idx, metadata={"start": start, "end": end}))
        idx += 1
        start += step
    return [c for c in chunks if c.content]
