"""Strict shared schema for executable per-segment video prompt sources."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PROMPT_SOURCE_LANES = (
    "identity_product_anchor",
    "reference_instruction",
    "product_solution_action",
    "timeline",
    "scene_detail",
    "sound_detail",
    "decorative_detail",
    "negative",
)
PROMPT_SOURCE_ANCHORS = ("character", "product", "action", "result")
PROMPT_SOURCE_KEYS = frozenset((*PROMPT_SOURCE_LANES, "required_anchors"))


class PromptSourceSchemaError(ValueError):
    """Raised when a source cannot enter the formal prompt compiler."""

    def __init__(self, field: str, detail: str) -> None:
        super().__init__(detail)
        self.field = field


def validate_prompt_source_schema(source: object) -> dict[str, Any]:
    """Return a detached normalized source or raise on any schema drift.

    Formal prompt sources have exactly eight non-empty string lanes and one
    four-category anchor mapping. Decorative detail is intentionally mandatory:
    parser callers and direct compiler callers must obey the same contract.
    """

    if not isinstance(source, Mapping):
        raise PromptSourceSchemaError("prompt_source", "prompt_source must be a mapping")
    actual_keys = set(source)
    if actual_keys != PROMPT_SOURCE_KEYS:
        missing = sorted(PROMPT_SOURCE_KEYS - actual_keys)
        extra = sorted(actual_keys - PROMPT_SOURCE_KEYS)
        raise PromptSourceSchemaError(
            "prompt_source",
            f"prompt_source keys mismatch; missing={missing}, extra={extra}",
        )

    normalized: dict[str, Any] = {}
    for lane in PROMPT_SOURCE_LANES:
        value = source.get(lane)
        if not isinstance(value, str) or not value.strip():
            raise PromptSourceSchemaError(
                lane,
                f"prompt_source.{lane} must be a non-empty string",
            )
        normalized[lane] = value.strip()

    anchors = source.get("required_anchors")
    if not isinstance(anchors, Mapping) or set(anchors) != set(PROMPT_SOURCE_ANCHORS):
        raise PromptSourceSchemaError(
            "required_anchors",
            "required_anchors must contain exactly character/product/action/result",
        )
    normalized_anchors: dict[str, str] = {}
    for category in PROMPT_SOURCE_ANCHORS:
        value = anchors.get(category)
        if not isinstance(value, str) or not value.strip():
            raise PromptSourceSchemaError(
                f"required_anchors.{category}",
                f"required_anchors.{category} must be a non-empty string",
            )
        normalized_anchors[category] = value.strip()
    normalized["required_anchors"] = normalized_anchors
    return normalized


__all__ = [
    "PROMPT_SOURCE_ANCHORS",
    "PROMPT_SOURCE_KEYS",
    "PROMPT_SOURCE_LANES",
    "PromptSourceSchemaError",
    "validate_prompt_source_schema",
]
