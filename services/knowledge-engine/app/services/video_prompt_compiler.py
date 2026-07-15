"""Compile executable per-segment video prompts within model profile limits."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
import re
import unicodedata
from typing import Any

from app.services.video_intent_profiles import (
    PromptBudgetProfile,
    get_video_intent_profile,
)


@dataclass(frozen=True, slots=True)
class PromptBudget:
    min_chars: int
    recommended_chars: tuple[int, int]
    max_chars: int


_PRIORITY_FIELDS = (
    "identity_product_anchor",
    "reference_instruction",
    "product_solution_action",
    "timeline",
    "scene_detail",
    "sound_detail",
    "decorative_detail",
)
_LAYER_FIELDS = (
    ("identity_product_anchor", "reference_instruction"),
    (
        "product_solution_action",
        "timeline",
        "scene_detail",
        "sound_detail",
        "decorative_detail",
    ),
    ("negative",),
)
_REQUIRED_SOURCE_FIELDS = (
    "identity_product_anchor",
    "reference_instruction",
    "product_solution_action",
    "timeline",
    "scene_detail",
    "sound_detail",
    "negative",
)
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[。；！？!?;\n])")
_TIMESTAMP_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)秒")


def prompt_budget_for_duration(
    duration_seconds: int,
    profile: PromptBudgetProfile,
) -> PromptBudget:
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, int)
        or duration_seconds < 1
        or duration_seconds > profile.segment_max_seconds
    ):
        raise ValueError("video_segment_duration_invalid")
    recommended_low, recommended_high = profile.recommended_chars_per_second
    return PromptBudget(
        min_chars=ceil(duration_seconds * profile.min_chars_per_second),
        recommended_chars=(
            ceil(duration_seconds * recommended_low),
            ceil(duration_seconds * recommended_high),
        ),
        max_chars=ceil(duration_seconds * profile.max_chars_per_second),
    )


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _split_clauses(text: str) -> list[str]:
    return [clause for clause in _CLAUSE_SPLIT_RE.split(text) if clause]


def _clause_key(clause: str) -> str:
    normalized = unicodedata.normalize("NFKC", clause).casefold()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.strip("。；！？!?;,，")


def _render_prompt(lanes: dict[str, str]) -> str:
    layers = []
    for fields in _LAYER_FIELDS:
        layer = "\n".join(lanes[field] for field in fields if lanes.get(field))
        if layer:
            layers.append(layer)
    return "\n".join(layers)


def _compress_cross_priority_duplicates(
    lanes: dict[str, str],
    max_chars: int,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    compressed = dict(lanes)
    removals: list[dict[str, Any]] = []
    if len(_render_prompt(compressed)) <= max_chars:
        return compressed, removals

    for index in range(len(_PRIORITY_FIELDS) - 1, 0, -1):
        field = _PRIORITY_FIELDS[index]
        higher_keys = {
            key
            for higher_field in _PRIORITY_FIELDS[:index]
            for clause in _split_clauses(compressed.get(higher_field, ""))
            if (key := _clause_key(clause))
        }
        if not higher_keys:
            continue

        kept: list[str] = []
        removed_count = 0
        for clause in _split_clauses(compressed.get(field, "")):
            key = _clause_key(clause)
            if key and key in higher_keys:
                removed_count += 1
            else:
                kept.append(clause)
        if removed_count:
            compressed[field] = "".join(kept).strip()
            removals.append({"field": field, "removed_clauses": removed_count})
        if len(_render_prompt(compressed)) <= max_chars:
            break
    return compressed, removals


def _timestamp_failed_checks(timeline: str, duration_seconds: int) -> list[str]:
    matches = [
        (float(start), float(end))
        for start, end in _TIMESTAMP_RE.findall(timeline)
    ]
    if not matches:
        return ["timestamps_missing"]

    failed: list[str] = []
    if matches[0][0] != 0:
        failed.append("timestamp_start")
    if any(start != previous_end for (_, previous_end), (start, _) in zip(matches, matches[1:])):
        failed.append("timestamp_continuity")
    if matches[-1][1] != duration_seconds:
        failed.append("timestamp_end")
    if any(end <= start for start, end in matches):
        failed.append("timestamp_range")
    return failed


def compile_final_prompt_segment(
    source: dict[str, Any],
    *,
    duration_seconds: int,
    intent: str,
) -> dict[str, Any]:
    profile = get_video_intent_profile(intent)
    try:
        budget = prompt_budget_for_duration(duration_seconds, profile.prompt_budget)
    except ValueError:
        return {
            "ok": False,
            "error": "video_segment_duration_invalid",
            "failed_checks": ["duration"],
        }

    source_lanes = {
        field: _text(source.get(field))
        for field in (*_PRIORITY_FIELDS, "negative")
    }
    lanes, compressed = _compress_cross_priority_duplicates(
        source_lanes,
        budget.max_chars,
    )
    final_prompt = _render_prompt(lanes)
    char_count = len(final_prompt)

    failed_checks = _timestamp_failed_checks(
        final_prompt,
        duration_seconds,
    )
    failed_checks.extend(
        field for field in _REQUIRED_SOURCE_FIELDS if not source_lanes[field]
    )
    required_anchors = source.get("required_anchors")
    if not isinstance(required_anchors, list) or not required_anchors:
        failed_checks.append("required_anchors")
    else:
        for anchor in required_anchors:
            if not isinstance(anchor, str) or not anchor.strip():
                failed_checks.append("required_anchor_invalid")
            elif anchor not in final_prompt:
                failed_checks.append(f"required_anchor:{anchor}")

    result = {
        "final_prompt": final_prompt,
        "char_count": char_count,
        "budget": asdict(budget),
        "compression": compressed,
        "failed_checks": failed_checks,
    }
    if failed_checks or char_count < budget.min_chars:
        if char_count < budget.min_chars:
            result["failed_checks"].append("min_chars")
        return {
            "ok": False,
            "error": "prompt_detail_insufficient",
            **result,
        }
    if char_count > budget.max_chars:
        result["failed_checks"].append("capacity")
        return {
            "ok": False,
            "error": "prompt_capacity_exceeded",
            **result,
        }
    return {"ok": True, **result}
