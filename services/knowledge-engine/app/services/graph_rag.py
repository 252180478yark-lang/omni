"""GraphRAG — LLM-powered entity / relation extraction with heuristic fallback.

Calls ai-provider-hub to extract structured entities and relations from text
chunks, then persists them to the knowledge.entities / knowledge.relations
tables with document_id linkage for retrieval-time graph traversal.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """\
你是一个知识图谱构建专家。请从以下文本中提取**实体**和**关系**。

要求：
1. 实体类型从以下选取：person, organization, product, technology, concept, location, event, metric
2. 关系应描述两个实体之间的语义联系
3. 只提取文本中**明确提及**的实体和关系，不要推测
4. 实体名称保持原文用词，不要翻译或改写
5. 每个实体的 description 用一句话概括其在文本中的角色

请严格返回如下 JSON（不要输出任何其他内容）：
```json
{
  "entities": [
    {"name": "实体名", "type": "person|organization|product|technology|concept|location|event|metric", "description": "一句话描述"}
  ],
  "relations": [
    {"source": "源实体名", "target": "目标实体名", "type": "关系类型", "weight": 0.0-1.0}
  ]
}
```

文本：
{text}
"""


@dataclass(slots=True)
class EntityData:
    name: str
    entity_type: str
    description: str


@dataclass(slots=True)
class RelationData:
    source: str
    target: str
    relation_type: str
    weight: float = 1.0


async def extract_entities_and_relations_llm(
    text: str,
    *,
    model: str | None = None,
    provider: str | None = None,
) -> tuple[list[EntityData], list[RelationData]]:
    """Extract entities & relations via LLM through ai-provider-hub.

    Falls back to heuristic extraction on any failure so ingestion is never
    blocked by graph extraction errors.
    """
    truncated = text[:4000] if len(text) > 4000 else text
    prompt = EXTRACT_PROMPT.replace("{text}", truncated)

    try:
        payload: dict = {
            "messages": [
                {"role": "system", "content": "你是知识图谱构建专家，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4000,
        }
        if model:
            payload["model"] = model
        if provider:
            payload["provider"] = provider

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{settings.ai_provider_hub_url}/api/v1/ai/chat",
                json=payload,
            )
            resp.raise_for_status()
            raw_content = resp.json().get("content", "")

        parsed = _parse_llm_json(raw_content)
        entities = [
            EntityData(
                name=e["name"].strip(),
                entity_type=e.get("type", "concept"),
                description=e.get("description", ""),
            )
            for e in parsed.get("entities", [])
            if e.get("name")
        ]
        relations = [
            RelationData(
                source=r["source"].strip(),
                target=r["target"].strip(),
                relation_type=r.get("type", "related_to"),
                weight=float(r.get("weight", 1.0)),
            )
            for r in parsed.get("relations", [])
            if r.get("source") and r.get("target")
        ]
        logger.info("LLM extraction: %d entities, %d relations", len(entities), len(relations))
        return entities, relations

    except Exception:
        logger.warning("LLM entity extraction failed, falling back to heuristic", exc_info=True)
        return extract_entities_and_relations_heuristic(text)


_CJK_RANGE = re.compile(r"[\u4e00-\u9fff]{2,8}")
_LATIN_ENTITY = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}\b")
_ZH_STOPWORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 "
    "这 他 她 它 们 那 里 为 什么 怎么 如何 可以 但是 如果 因为 所以 然后 或者 以及 "
    "通过 进行 使用 已经 正在 需要 应该 其中 之后 之前 关于 对于".split()
)


def extract_entities_and_relations_heuristic(
    text: str,
) -> tuple[list[EntityData], list[RelationData]]:
    """Lightweight heuristic fallback — CJK n-grams and capitalized Latin words."""
    entities: list[EntityData] = []
    seen: set[str] = set()

    for m in _LATIN_ENTITY.finditer(text):
        word = m.group()
        if word.lower() not in seen:
            seen.add(word.lower())
            entities.append(EntityData(name=word, entity_type="concept", description=""))

    for m in _CJK_RANGE.finditer(text):
        phrase = m.group()
        if phrase not in seen and phrase not in _ZH_STOPWORDS:
            seen.add(phrase)
            entities.append(EntityData(name=phrase, entity_type="concept", description=""))

    entities = entities[:50]

    relations: list[RelationData] = []
    for idx in range(1, len(entities)):
        relations.append(
            RelationData(
                source=entities[idx - 1].name,
                target=entities[idx].name,
                relation_type="related_to",
                weight=0.5,
            )
        )
    return entities, relations


# keep the old name as an alias so existing imports don't break
extract_entities_and_relations = extract_entities_and_relations_heuristic


def _parse_llm_json(raw: str) -> dict:
    """Best-effort parse of LLM output that may contain markdown fences."""
    cleaned = raw.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            pass
    return {"entities": [], "relations": []}
