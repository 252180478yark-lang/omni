from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest
import yaml

from app.services import video_intent_profiles as profiles


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
    raw = yaml.safe_load(profiles._PROFILE_PATH.read_text(encoding="utf-8"))
    malformed = deepcopy(raw)
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
