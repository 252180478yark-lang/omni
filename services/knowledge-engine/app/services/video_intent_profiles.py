"""Versioned configuration for the shared AI short-video intent kernel."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_PROFILE_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "video_intent_profiles.yaml"
)

_REQUIRED_PROFILE_FIELDS = (
    "kind",
    "intent",
    "method",
    "bridge_extractor",
    "content_gate",
    "prompt_profile",
    "metric_policy",
    "north_star",
    "diagnostic_metrics",
    "vector_threshold_100",
    "key_vector_dimensions",
    "prompt_budget",
    "evaluation_policy",
    "iteration_candidates",
    "global_iteration_order",
)

_REQUIRED_PROMPT_BUDGET_FIELDS = (
    "segment_max_seconds",
    "min_chars_per_second",
    "recommended_chars_per_second",
    "max_chars_per_second",
)

_REQUIRED_EVALUATION_POLICY_FIELDS = (
    "play_3s_floor",
    "completion_floor",
    "a3_floor",
    "cpm_ceiling",
    "min_impressions",
    "min_a3_eligible_users",
    "max_exposure_ratio",
    "rate_scale",
    "currency",
)


@dataclass(frozen=True, slots=True)
class PromptBudgetProfile:
    segment_max_seconds: int
    min_chars_per_second: int
    recommended_chars_per_second: tuple[int, int]
    max_chars_per_second: int


@dataclass(frozen=True, slots=True)
class VideoIntentProfile:
    version: str
    intent: str
    kind: str
    method: str
    bridge_extractor: str | None
    content_gate: str
    prompt_profile: str
    metric_policy: str
    north_star: str
    diagnostic_metrics: tuple[str, ...]
    vector_threshold_100: int
    key_vector_dimensions: tuple[str, ...]
    prompt_budget: PromptBudgetProfile
    evaluation_policy: dict[str, Any]
    iteration_candidates: dict[str, tuple[str, ...]]
    global_iteration_order: tuple[str, ...]


def _invalid(reason: str) -> ValueError:
    return ValueError(f"video_intent_profiles_invalid:{reason}")


def _required_fields(
    raw: dict[str, Any],
    required: tuple[str, ...],
    location: str,
) -> None:
    missing = tuple(field for field in required if field not in raw)
    if missing:
        raise _invalid(f"{location}:missing:{','.join(missing)}")


def _string_tuple(value: object, location: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise _invalid(location)
    return tuple(value)


def _positive_int(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(location)
    return value


def _parse_prompt_budget(raw: object, intent: str) -> PromptBudgetProfile:
    location = f"{intent}:prompt_budget"
    if not isinstance(raw, dict):
        raise _invalid(location)
    _required_fields(raw, _REQUIRED_PROMPT_BUDGET_FIELDS, location)

    segment_max = _positive_int(
        raw["segment_max_seconds"], f"{location}:segment_max_seconds"
    )
    minimum = _positive_int(
        raw["min_chars_per_second"], f"{location}:min_chars_per_second"
    )
    maximum = _positive_int(
        raw["max_chars_per_second"], f"{location}:max_chars_per_second"
    )
    recommended = raw["recommended_chars_per_second"]
    if (
        not isinstance(recommended, (list, tuple))
        or len(recommended) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in recommended)
    ):
        raise _invalid(f"{location}:recommended_chars_per_second")
    recommended_range = (recommended[0], recommended[1])
    if not minimum <= recommended_range[0] <= recommended_range[1] <= maximum:
        raise _invalid(f"{location}:recommended_chars_per_second:order")

    return PromptBudgetProfile(
        segment_max_seconds=segment_max,
        min_chars_per_second=minimum,
        recommended_chars_per_second=recommended_range,
        max_chars_per_second=maximum,
    )


def _parse_profile(
    name: str,
    raw: object,
    version: str,
) -> VideoIntentProfile:
    if not isinstance(raw, dict):
        raise _invalid(f"{name}:profile")
    _required_fields(raw, _REQUIRED_PROFILE_FIELDS, name)

    string_fields = (
        "kind",
        "intent",
        "method",
        "content_gate",
        "prompt_profile",
        "metric_policy",
        "north_star",
    )
    for field in string_fields:
        if not isinstance(raw[field], str) or not raw[field]:
            raise _invalid(f"{name}:{field}")
    if raw["intent"] != name:
        raise _invalid(f"{name}:intent_mismatch")
    bridge_extractor = raw["bridge_extractor"]
    if bridge_extractor is not None and (
        not isinstance(bridge_extractor, str) or not bridge_extractor
    ):
        raise _invalid(f"{name}:bridge_extractor")

    evaluation_policy = raw["evaluation_policy"]
    if not isinstance(evaluation_policy, dict):
        raise _invalid(f"{name}:evaluation_policy")
    _required_fields(
        evaluation_policy,
        _REQUIRED_EVALUATION_POLICY_FIELDS,
        f"{name}:evaluation_policy",
    )

    iteration_candidates = raw["iteration_candidates"]
    if not isinstance(iteration_candidates, dict) or not iteration_candidates:
        raise _invalid(f"{name}:iteration_candidates")
    parsed_candidates: dict[str, tuple[str, ...]] = {}
    for metric, candidates in iteration_candidates.items():
        if not isinstance(metric, str) or not metric:
            raise _invalid(f"{name}:iteration_candidates:metric")
        parsed_candidates[metric] = _string_tuple(
            candidates,
            f"{name}:iteration_candidates:{metric}",
        )

    return VideoIntentProfile(
        version=version,
        intent=raw["intent"],
        kind=raw["kind"],
        method=raw["method"],
        bridge_extractor=bridge_extractor,
        content_gate=raw["content_gate"],
        prompt_profile=raw["prompt_profile"],
        metric_policy=raw["metric_policy"],
        north_star=raw["north_star"],
        diagnostic_metrics=_string_tuple(
            raw["diagnostic_metrics"], f"{name}:diagnostic_metrics"
        ),
        vector_threshold_100=_positive_int(
            raw["vector_threshold_100"], f"{name}:vector_threshold_100"
        ),
        key_vector_dimensions=_string_tuple(
            raw["key_vector_dimensions"], f"{name}:key_vector_dimensions"
        ),
        prompt_budget=_parse_prompt_budget(raw["prompt_budget"], name),
        evaluation_policy=deepcopy(evaluation_policy),
        iteration_candidates=parsed_candidates,
        global_iteration_order=_string_tuple(
            raw["global_iteration_order"], f"{name}:global_iteration_order"
        ),
    )


def _parse_config(raw: object) -> dict[str, VideoIntentProfile]:
    if not isinstance(raw, dict):
        raise _invalid("top_level")
    version = raw.get("version")
    if not isinstance(version, str) or not version:
        raise _invalid("version")
    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise _invalid("profiles")

    parsed: dict[str, VideoIntentProfile] = {}
    for name, raw_profile in raw_profiles.items():
        if not isinstance(name, str) or not name:
            raise _invalid("profile_name")
        parsed[name] = _parse_profile(name, raw_profile, version)
    return parsed


@lru_cache(maxsize=1)
def _load_profiles() -> dict[str, VideoIntentProfile]:
    try:
        with _PROFILE_PATH.open(encoding="utf-8") as profile_file:
            raw = yaml.safe_load(profile_file)
    except (OSError, yaml.YAMLError) as exc:
        raise _invalid("load_failed") from exc
    return _parse_config(raw)


def get_video_intent_profile(intent: str) -> VideoIntentProfile:
    profile = _load_profiles().get(intent)
    if profile is None:
        raise ValueError(f"video_intent_profile_not_found:{intent}")
    return replace(
        profile,
        evaluation_policy=deepcopy(profile.evaluation_policy),
        iteration_candidates=deepcopy(profile.iteration_candidates),
    )
