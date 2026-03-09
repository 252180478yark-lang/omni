from __future__ import annotations

from dataclasses import dataclass


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


def extract_entities_and_relations(text: str) -> tuple[list[EntityData], list[RelationData]]:
    # Heuristic extraction for local runtime; can be replaced by LLM extractor later.
    words = [w.strip(".,!?()[]{}\"'") for w in text.split()]
    entities: list[EntityData] = []
    seen: set[str] = set()
    for word in words:
        if len(word) >= 3 and word[0].isupper() and word.lower() not in seen:
            seen.add(word.lower())
            entities.append(EntityData(name=word, entity_type="concept", description=f"Entity from text: {word}"))

    relations: list[RelationData] = []
    for idx in range(1, len(entities)):
        relations.append(
            RelationData(
                source=entities[idx - 1].name,
                target=entities[idx].name,
                relation_type="related_to",
                weight=1.0,
            )
        )
    return entities, relations
