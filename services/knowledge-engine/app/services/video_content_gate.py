"""Pure content gates and immutable video content-contract builders."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from math import isfinite
from typing import Any


_CONTRACT_VERSION = "2026-07-15.v1"

_PLANTING_SCORE_FIELDS = (
    "portrait_scene_alignment_score",
    "pain_specificity_score",
    "product_solution_fit_score",
)
_PLANTING_REQUIRED_TRUE_FIELDS = (
    "product_action_visible",
    "solution_result_visible",
    "justification_grounded",
    "belief_shift_present",
)
_PLANTING_REQUIRED_FALSE_FIELDS = (
    "hard_cta_present",
    "price_promotion_present",
    "fabricated_qualification_present",
    "fake_testimonial_present",
)
_SOFT_AD_SCORE_THRESHOLDS = (
    ("human_watch_gate_score", 80),
    ("golden_3s_gate_score", 70),
    ("douyin_native_feel_score", 75),
    ("structure_fit_score", 70),
)
_TRIANGLE_EDGES = ("audience_content", "product_content")
_VALID_RELEVANCE_MODULES = {"M1", "M2"}
_VALID_JUSTIFICATION_MODULES = {f"M{index}" for index in range(3, 10)}


def _is_finite_number(value: object) -> bool:
    return not isinstance(value, bool) and (
        isinstance(value, int) or (isinstance(value, float) and isfinite(value))
    )


def _validated_threshold(value: object, name: str) -> int | float:
    if not _is_finite_number(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def _mapping_or_empty(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _triangle_values(triangle: object) -> tuple[object, Mapping[str, Any]]:
    triangle_mapping = _mapping_or_empty(triangle)
    if "overall_score_100" in triangle_mapping:
        overall = triangle_mapping["overall_score_100"]
    else:
        overall = triangle_mapping.get("overall_100")

    if "edges_100" in triangle_mapping:
        edges = triangle_mapping["edges_100"]
    else:
        edges = triangle_mapping.get("edge_scores_100")
    return overall, _mapping_or_empty(edges)


def _triangle_failures(triangle: object, floor: int | float) -> list[str]:
    overall, edges = _triangle_values(triangle)
    failed: list[str] = []
    if not _is_finite_number(overall) or overall < floor:
        failed.append("script_vector_overall")
    for edge in _TRIANGLE_EDGES:
        value = edges.get(edge)
        if not _is_finite_number(value) or value < floor:
            failed.append(edge)
    return failed


def _stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def evaluate_planting_content_gate(
    metrics: object,
    triangle: object,
    score_floor: int | float = 80,
    triangle_floor: int | float = 70,
) -> dict[str, Any]:
    """Evaluate the fail-closed planting content gate without side effects."""

    score_floor = _validated_threshold(score_floor, "score_floor")
    triangle_floor = _validated_threshold(triangle_floor, "triangle_floor")
    metric_values = _mapping_or_empty(metrics)
    failed: list[str] = []

    for field in _PLANTING_SCORE_FIELDS:
        value = metric_values.get(field)
        if not _is_finite_number(value) or value < score_floor:
            failed.append(field)
    for field in _PLANTING_REQUIRED_TRUE_FIELDS:
        if metric_values.get(field) is not True:
            failed.append(field)
    for field in _PLANTING_REQUIRED_FALSE_FIELDS:
        if metric_values.get(field) is not False:
            failed.append(field)
    failed.extend(_triangle_failures(triangle, triangle_floor))
    failed = _stable_unique(failed)

    return {
        "pass": not failed,
        "failed_checks": failed,
        "gate_version": "planting_v1",
        "thresholds": {
            "score_floor": score_floor,
            "triangle_floor": triangle_floor,
        },
    }


def evaluate_soft_ad_content_gate(
    metrics: object,
    triangle: object,
) -> dict[str, Any]:
    """Evaluate the soft-ad gate independently of planting pain fields."""

    metric_values = _mapping_or_empty(metrics)
    failed: list[str] = []
    for field, floor in _SOFT_AD_SCORE_THRESHOLDS:
        value = metric_values.get(field)
        if not _is_finite_number(value) or value < floor:
            failed.append(field)
    failed.extend(_triangle_failures(triangle, 70))
    failed = _stable_unique(failed)

    return {
        "pass": not failed,
        "failed_checks": failed,
        "gate_version": "soft_ad_v1",
        "thresholds": {
            **dict(_SOFT_AD_SCORE_THRESHOLDS),
            "triangle_floor": 70,
        },
    }


def _profile_field(profile: object, field: str, *aliases: str) -> str:
    names = (field, *aliases)
    if isinstance(profile, Mapping):
        for name in names:
            if name in profile:
                value = profile[name]
                break
        else:
            value = None
    else:
        value = None
        for name in names:
            if hasattr(profile, name):
                value = getattr(profile, name)
                break
    if not isinstance(value, str) or not value:
        raise ValueError(f"profile missing valid {field}")
    return value


def _profile_envelope(profile: object, north_star_metric: str) -> dict[str, str]:
    return {
        "kind": _profile_field(profile, "kind"),
        "intent": _profile_field(profile, "intent"),
        "profile_version": _profile_field(profile, "version", "profile_version"),
        "north_star_metric": north_star_metric,
    }


def _validated_bridge(bridge: object) -> tuple[dict[str, Any], dict[str, str]]:
    if not isinstance(bridge, Mapping) or not bridge:
        raise ValueError("bridge must be a non-empty mapping")

    relevance = bridge.get("relevance_module")
    justification = bridge.get("justification_module")
    if (
        relevance not in _VALID_RELEVANCE_MODULES
        or justification not in _VALID_JUSTIFICATION_MODULES
    ):
        raise ValueError("bridge modules are missing or invalid")

    return deepcopy(dict(bridge)), {
        "relevance_module": relevance,
        "justification_module": justification,
    }


def build_content_contract(
    profile: object,
    bridge: object,
    metrics: object,
    triangle: object,
    prompt_blocks: object,
    upstream_fact_hash: object,
) -> dict[str, Any]:
    """Build a detached planting contract from already-produced artifacts."""

    bridge_copy, method = _validated_bridge(bridge)
    return {
        "version": _CONTRACT_VERSION,
        **_profile_envelope(profile, "a3_ratio"),
        "pain_solution_bridge": bridge_copy,
        "method": method,
        "content_gate": evaluate_planting_content_gate(metrics, triangle),
        "script_vector_gate": deepcopy(triangle),
        "prompt_blocks": deepcopy(prompt_blocks),
        "upstream_fact_hash": deepcopy(upstream_fact_hash),
    }


def build_soft_ad_content_contract(
    profile: object,
    metrics: object,
    triangle: object,
    prompt_blocks: object,
    upstream_fact_hash: object = None,
) -> dict[str, Any]:
    """Build a detached soft-ad contract without a planting pain bridge."""

    return {
        "version": _CONTRACT_VERSION,
        **_profile_envelope(profile, "completion_rate"),
        "content_gate": evaluate_soft_ad_content_gate(metrics, triangle),
        "script_vector_gate": deepcopy(triangle),
        "prompt_blocks": deepcopy(prompt_blocks),
        "upstream_fact_hash": deepcopy(upstream_fact_hash),
    }


__all__ = [
    "build_content_contract",
    "build_soft_ad_content_contract",
    "evaluate_planting_content_gate",
    "evaluate_soft_ad_content_gate",
]
