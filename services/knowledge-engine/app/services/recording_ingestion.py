"""录音/转写文本的摘要式入库管道（kb_role == personal_log 触发）.

与默认 chunking 不同：录音转写是口语化叙述，按字数硬切容易把同一话题切散。
做法是先调 LLM 做章节聚类 + 主题摘要 + 关键引语提取，每个主题作为一个 chunk
（content=「## 标题 + 摘要 + 关键原文引语」，metadata 存原文片段锚点）。

调用约定：
- 输入：clean 后的整段转写文本
- 输出：list[ChunkData]，可直接喂给 ingestion 主管道做 embedding + DB 写入
- 失败兜底：把整段当作一个 chunk 返回，不抛异常
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings
from app.services.chunking import ChunkData

logger = logging.getLogger(__name__)

_RECORDING_SUMMARIZE_PROMPT = """以下是一段录音/转写文本，请按主题切分成若干章节，每个章节给出：
1. title: 简洁的主题标题（10 字以内）
2. summary: 围绕该主题的 2-4 句要点摘要
3. key_quotes: 2-3 条原文中的关键引语（务必从原文逐字摘录，不得改写或编造）
4. start_marker / end_marker: 该章节在原文中的起止句（10-30 字片段，便于锚点）

输出严格 JSON 数组，不要任何其他文字、不要 markdown 代码块包裹：
[
  {{"title":"...","summary":"...","key_quotes":["...","..."],"start_marker":"...","end_marker":"..."}},
  ...
]

如果文本只有一个主题，也返回单元素数组。

录音转写正文：
{text}"""

_MAX_INPUT_CHARS = 30000  # 单次 LLM 输入字符数上限，超过则分段处理
_MAX_EXCERPT_CHARS = 1500


async def summarize_and_chunk(
    text: str,
    *,
    title: str | None = None,
    model: str | None = None,
) -> list[ChunkData]:
    """对录音文本做"主题切分 + 摘要 + 引语提取"，返回 ChunkData 列表."""
    text = (text or "").strip()
    if not text:
        return []

    segments = _split_long_text(text, _MAX_INPUT_CHARS)
    items: list[dict] = []
    for seg_idx, seg in enumerate(segments):
        try:
            seg_items = await _call_summarizer(seg, model=model)
        except Exception:
            logger.warning(
                "recording summarizer failed seg=%d, fallback to single summary",
                seg_idx, exc_info=True,
            )
            seg_items = [_fallback_summary(seg, seg_idx)]
        for it in seg_items:
            it.setdefault("_seg_idx", seg_idx)
        items.extend(seg_items)

    chunks: list[ChunkData] = []
    for idx, item in enumerate(items):
        chunk_title = (item.get("title") or f"片段 {idx+1}").strip()[:80]
        summary = (item.get("summary") or "").strip()
        quotes_raw = item.get("key_quotes") or []
        if isinstance(quotes_raw, str):
            quotes_raw = [quotes_raw]
        quotes = [str(q).strip() for q in quotes_raw if str(q).strip()]

        body_lines = [f"## {chunk_title}"]
        if summary:
            body_lines.extend(["", summary])
        if quotes:
            body_lines.extend(["", "关键原文："])
            body_lines.extend([f"- {q}" for q in quotes])
        content = "\n".join(body_lines).strip()

        excerpt = _extract_excerpt(
            text, item.get("start_marker"), item.get("end_marker"),
        )

        chunks.append(ChunkData(
            content=content,
            chunk_index=idx,
            metadata={
                "chunk_type": "recording_summary",
                "section_title": chunk_title,
                "summary": summary,
                "key_quotes": quotes,
                "original_excerpt": excerpt,
                "seg_idx": item.get("_seg_idx", 0),
                "source_doc_title": title or "",
            },
        ))

    if not chunks:
        chunks = [ChunkData(
            content=text[:2000],
            chunk_index=0,
            metadata={"chunk_type": "recording_summary", "fallback": True},
        )]
    return chunks


def _split_long_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    segs: list[str] = []
    cursor = 0
    while cursor < len(text):
        chunk = text[cursor:cursor + limit]
        cut = max(chunk.rfind("\n"), chunk.rfind("。"))
        if cut < int(limit * 0.5):
            cut = limit
        segs.append(text[cursor:cursor + cut].strip())
        cursor += cut
    return [s for s in segs if s]


async def _call_summarizer(text: str, *, model: str | None) -> list[dict]:
    payload: dict = {
        "messages": [{
            "role": "user",
            "content": _RECORDING_SUMMARIZE_PROMPT.format(text=text),
        }],
        "temperature": 0.2,
        "max_tokens": 2500,
    }
    if model:
        payload["model"] = model

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{settings.ai_provider_hub_url}/api/v1/ai/chat",
            json=payload,
        )
        resp.raise_for_status()
        raw = (resp.json().get("content") or "").strip()
    return _parse_json_array(raw)


def _parse_json_array(raw: str) -> list[dict]:
    if not raw:
        raise ValueError("empty summarizer output")
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    s = cleaned.find("[")
    e = cleaned.rfind("]")
    if s < 0 or e <= s:
        raise ValueError("no JSON array in output")
    parsed = json.loads(cleaned[s:e+1])
    if not isinstance(parsed, list):
        raise ValueError("output is not a list")
    return [x for x in parsed if isinstance(x, dict)]


def _fallback_summary(text: str, seg_idx: int) -> dict:
    head = text[:120]
    tail = text[-120:] if len(text) > 240 else ""
    return {
        "title": f"段 {seg_idx + 1}",
        "summary": (head + ("…" + tail if tail else ""))[:300],
        "key_quotes": [],
        "start_marker": text[:30],
        "end_marker": text[-30:] if len(text) > 30 else text,
    }


def _extract_excerpt(
    text: str,
    start_marker: str | None,
    end_marker: str | None,
) -> str:
    if not start_marker:
        return ""
    s = text.find(start_marker)
    if s < 0:
        return start_marker
    if end_marker:
        e = text.find(end_marker, s)
        if e < 0:
            e = s + 800
        else:
            e = e + len(end_marker)
    else:
        e = s + 800
    return text[s:e][:_MAX_EXCERPT_CHARS]
