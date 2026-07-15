from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.services import video_intent_profiles as profiles


def _raw_config() -> dict[str, Any]:
    raw = yaml.safe_load(profiles._PROFILE_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_planting_profile_routes_to_a3_kernel() -> None:
    profile = profiles.get_video_intent_profile("planting")

    assert profile.kind == "video_planting"
    assert profile.intent == "planting"
    assert profile.bridge_extractor == "generate_planting_pain_solution_bridge"
    assert profile.north_star == "a3_ratio"
    assert profile.method == "M1/M2_x_M3-M9"
    assert profile.prompt_profile == "creative_pack.video_planting"
    assert profile.metric_policy == "planting_a3_v1"


def test_soft_ad_profile_routes_to_life_flow_kernel() -> None:
    profile = profiles.get_video_intent_profile("soft_ad")

    assert profile.kind == "video_soft_ad"
    assert profile.intent == "soft_ad"
    assert profile.bridge_extractor is None
    assert profile.north_star == "completion_rate"
    assert profile.method == "soft_ad_life_flow"
    assert profile.prompt_profile == "creative_pack.video_soft_ad"
    assert profile.metric_policy == "soft_ad_completion_v1"


def test_planting_prompt_budget_matches_generation_contract() -> None:
    budget = profiles.get_video_intent_profile("planting").prompt_budget

    assert budget.segment_max_seconds == 15
    assert budget.min_chars_per_second == 50
    assert budget.recommended_chars_per_second == (60, 87)
    assert budget.max_chars_per_second == 107


@pytest.mark.parametrize("intent", ["planting", "soft_ad"])
def test_evaluation_policy_keeps_unsupplied_thresholds_null(intent: str) -> None:
    policy = profiles.get_video_intent_profile(intent).evaluation_policy

    assert policy["play_3s_floor"] is None
    assert policy["completion_floor"] is None
    assert policy["a3_floor"] is None
    assert policy["cpm_ceiling"] is None
    assert policy["min_impressions"] is None
    assert policy["min_a3_eligible_users"] is None
    assert policy["max_exposure_ratio"] == 3.0
    assert policy["rate_scale"] == "0-1"
    assert policy["currency"] == "CNY"


def test_unknown_intent_has_stable_error_code() -> None:
    with pytest.raises(
        ValueError,
        match=r"^video_intent_profile_not_found:harvest$",
    ):
        profiles.get_video_intent_profile("harvest")


@pytest.mark.parametrize(
    "recommended_range",
    [
        [60],
        [87, 60],
    ],
)
def test_malformed_recommended_range_is_rejected(
    recommended_range: list[int],
) -> None:
    malformed = deepcopy(_raw_config())
    malformed["profiles"]["planting"]["prompt_budget"][
        "recommended_chars_per_second"
    ] = recommended_range

    with pytest.raises(
        ValueError,
        match="recommended_chars_per_second",
    ):
        profiles._parse_config(malformed)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {"version": "2026-07-15.v1"},
        {"version": "", "profiles": {}},
    ],
)
def test_malformed_top_level_config_is_rejected(raw: object) -> None:
    with pytest.raises(ValueError, match="video_intent_profiles_invalid"):
        profiles._parse_config(raw)


def test_profile_results_do_not_expose_cached_mutable_state() -> None:
    first = profiles.get_video_intent_profile("planting")
    first.evaluation_policy["max_exposure_ratio"] = 99.0
    first.iteration_candidates["play_3s_rate"] = ("changed",)

    second = profiles.get_video_intent_profile("planting")

    assert second.evaluation_policy["max_exposure_ratio"] == 3.0
    assert second.iteration_candidates["play_3s_rate"] == (
        "opening_hook_3s",
        "presentation_motif",
    )
    assert isinstance(second.diagnostic_metrics, tuple)
    assert isinstance(second.key_vector_dimensions, tuple)
    assert isinstance(second.global_iteration_order, tuple)
    with pytest.raises(FrozenInstanceError):
        second.kind = "video_soft_ad"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("play_3s_floor", True),
        ("play_3s_floor", -0.01),
        ("completion_floor", 1.01),
        ("a3_floor", "0.5"),
        ("cpm_ceiling", True),
        ("cpm_ceiling", -0.01),
        ("min_impressions", "100"),
        ("min_a3_eligible_users", -1),
        ("max_exposure_ratio", False),
        ("max_exposure_ratio", 0),
        ("max_exposure_ratio", 0.5),
        ("max_exposure_ratio", 1.0),
        ("rate_scale", "percent"),
        ("currency", "USD"),
    ],
)
def test_invalid_evaluation_policy_values_are_rejected(
    field: str,
    value: object,
) -> None:
    malformed = deepcopy(_raw_config())
    malformed["profiles"]["planting"]["evaluation_policy"][field] = value

    with pytest.raises(
        ValueError,
        match=r"^video_intent_profile_invalid:planting:evaluation_policy",
    ):
        profiles._parse_config(malformed)


def test_supplied_numeric_evaluation_thresholds_are_accepted() -> None:
    raw = deepcopy(_raw_config())
    policy = raw["profiles"]["planting"]["evaluation_policy"]
    policy.update(
        {
            "play_3s_floor": 0.0,
            "completion_floor": 1,
            "a3_floor": 0.25,
            "cpm_ceiling": 0,
            "min_impressions": 12.5,
            "min_a3_eligible_users": 0,
            "max_exposure_ratio": 1.01,
        }
    )

    parsed = profiles._parse_config(raw)["planting"].evaluation_policy

    assert parsed["completion_floor"] == 1
    assert parsed["min_impressions"] == 12.5
    assert parsed["max_exposure_ratio"] == 1.01


@pytest.mark.parametrize("threshold", [0, 70.5, 100])
def test_vector_threshold_accepts_numeric_values_in_closed_range(
    threshold: int | float,
) -> None:
    raw = deepcopy(_raw_config())
    raw["profiles"]["planting"]["vector_threshold_100"] = threshold

    profile = profiles._parse_config(raw)["planting"]

    assert profile.vector_threshold_100 == threshold


@pytest.mark.parametrize("threshold", [True, -0.01, 100.01, 101, "70"])
def test_vector_threshold_rejects_boolean_non_numeric_and_out_of_range(
    threshold: object,
) -> None:
    malformed = deepcopy(_raw_config())
    malformed["profiles"]["planting"]["vector_threshold_100"] = threshold

    with pytest.raises(ValueError, match="vector_threshold_100"):
        profiles._parse_config(malformed)


def test_iteration_candidate_list_rejects_duplicates() -> None:
    malformed = deepcopy(_raw_config())
    malformed["profiles"]["planting"]["iteration_candidates"][
        "play_3s_rate"
    ] = ["opening_hook_3s", "opening_hook_3s"]

    with pytest.raises(ValueError, match="iteration_candidates"):
        profiles._parse_config(malformed)


def test_global_iteration_order_rejects_duplicates() -> None:
    malformed = deepcopy(_raw_config())
    order = malformed["profiles"]["planting"]["global_iteration_order"]
    order.append(order[0])

    with pytest.raises(ValueError, match="global_iteration_order"):
        profiles._parse_config(malformed)


def test_iteration_candidate_must_exist_in_global_order() -> None:
    malformed = deepcopy(_raw_config())
    malformed["profiles"]["planting"]["iteration_candidates"][
        "play_3s_rate"
    ].append("unregistered_variable")

    with pytest.raises(ValueError, match="iteration_candidates"):
        profiles._parse_config(malformed)


def test_loader_maps_unicode_decode_errors_to_stable_load_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_yaml = tmp_path / "video_intent_profiles.yaml"
    invalid_yaml.write_bytes(b"\xff")
    monkeypatch.setattr(profiles, "_PROFILE_PATH", invalid_yaml)
    profiles._load_profiles.cache_clear()

    try:
        with pytest.raises(
            ValueError,
            match=r"^video_intent_profiles_invalid:load_failed$",
        ):
            profiles._load_profiles()
    finally:
        profiles._load_profiles.cache_clear()
