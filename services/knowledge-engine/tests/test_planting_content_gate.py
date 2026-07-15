from __future__ import annotations

from dataclasses import dataclass
from math import inf, nan

import pytest

from app.services.video_content_gate import (
    build_content_contract,
    build_soft_ad_content_contract,
    evaluate_planting_content_gate,
    evaluate_soft_ad_content_gate,
)


PLANTING_METRICS = {
    "portrait_scene_alignment_score": 80,
    "pain_specificity_score": 80,
    "product_solution_fit_score": 80,
    "product_action_visible": True,
    "solution_result_visible": True,
    "justification_grounded": True,
    "belief_shift_present": True,
    "hard_cta_present": False,
    "price_promotion_present": False,
    "fabricated_qualification_present": False,
    "fake_testimonial_present": False,
}

SOFT_AD_METRICS = {
    "human_watch_gate_score": 80,
    "golden_3s_gate_score": 70,
    "douyin_native_feel_score": 75,
    "structure_fit_score": 70,
}

TRIANGLE = {
    "overall_score_100": 70,
    "edges_100": {
        "audience_content": 70,
        "product_content": 70,
    },
}


def _planting_metrics(**updates):
    result = dict(PLANTING_METRICS)
    result.update(updates)
    return result


def _soft_metrics(**updates):
    result = dict(SOFT_AD_METRICS)
    result.update(updates)
    return result


def _triangle(**updates):
    result = {
        "overall_score_100": TRIANGLE["overall_score_100"],
        "edges_100": dict(TRIANGLE["edges_100"]),
    }
    result.update(updates)
    return result


def test_planting_gate_accepts_exact_boundaries_and_reports_contract():
    result = evaluate_planting_content_gate(PLANTING_METRICS, TRIANGLE)

    assert result == {
        "pass": True,
        "failed_checks": [],
        "gate_version": "planting_v1",
        "thresholds": {"score_floor": 80, "triangle_floor": 70},
    }


@pytest.mark.parametrize(
    "field",
    [
        "portrait_scene_alignment_score",
        "pain_specificity_score",
        "product_solution_fit_score",
    ],
)
def test_planting_gate_rejects_each_numeric_score_below_boundary(field):
    result = evaluate_planting_content_gate(_planting_metrics(**{field: 79}), TRIANGLE)

    assert result["pass"] is False
    assert field in result["failed_checks"]


@pytest.mark.parametrize(
    "field",
    [
        "product_action_visible",
        "solution_result_visible",
        "justification_grounded",
        "belief_shift_present",
    ],
)
def test_planting_gate_requires_boolean_flags_to_be_true(field):
    result = evaluate_planting_content_gate(
        _planting_metrics(**{field: False}), TRIANGLE
    )

    assert result["pass"] is False
    assert field in result["failed_checks"]


@pytest.mark.parametrize(
    "field",
    [
        "hard_cta_present",
        "price_promotion_present",
        "fabricated_qualification_present",
        "fake_testimonial_present",
    ],
)
def test_planting_gate_requires_prohibited_flags_to_be_false(field):
    result = evaluate_planting_content_gate(
        _planting_metrics(**{field: True}), TRIANGLE
    )

    assert result["pass"] is False
    assert field in result["failed_checks"]


@pytest.mark.parametrize("bad_value", [True, False, nan, inf, -inf, "80", None])
def test_planting_gate_rejects_invalid_numeric_values(bad_value):
    result = evaluate_planting_content_gate(
        _planting_metrics(portrait_scene_alignment_score=bad_value), TRIANGLE
    )

    assert result["pass"] is False
    assert "portrait_scene_alignment_score" in result["failed_checks"]


def test_planting_gate_rejects_missing_values_and_deduplicates_failures_stably():
    metrics = _planting_metrics()
    del metrics["portrait_scene_alignment_score"]
    triangle = {"overall_score_100": 69, "edges_100": {}}

    result = evaluate_planting_content_gate(metrics, triangle)

    assert result["pass"] is False
    assert result["failed_checks"] == list(dict.fromkeys(result["failed_checks"]))
    assert result["failed_checks"] == [
        "portrait_scene_alignment_score",
        "script_vector_overall",
        "audience_content",
        "product_content",
    ]


def test_planting_gate_honors_custom_thresholds():
    result = evaluate_planting_content_gate(
        _planting_metrics(
            portrait_scene_alignment_score=90,
            pain_specificity_score=90,
            product_solution_fit_score=90,
        ),
        _triangle(
            overall_score_100=75,
            edges_100={"audience_content": 75, "product_content": 75},
        ),
        score_floor=90,
        triangle_floor=75,
    )

    assert result["pass"] is True
    assert result["thresholds"] == {"score_floor": 90, "triangle_floor": 75}


def test_planting_gate_accepts_triangle_compatibility_aliases():
    triangle = {
        "overall_100": 70,
        "edge_scores_100": {"audience_content": 70, "product_content": 70},
    }

    assert evaluate_planting_content_gate(PLANTING_METRICS, triangle)["pass"] is True


@pytest.mark.parametrize(
    ("triangle", "failed_check"),
    [
        (
            {"overall_score_100": 69, "edges_100": TRIANGLE["edges_100"]},
            "script_vector_overall",
        ),
        (
            {"overall_score_100": True, "edges_100": TRIANGLE["edges_100"]},
            "script_vector_overall",
        ),
        (
            {"overall_score_100": nan, "edges_100": TRIANGLE["edges_100"]},
            "script_vector_overall",
        ),
        (
            {
                "overall_score_100": 70,
                "edges_100": {"audience_content": 69, "product_content": 70},
            },
            "audience_content",
        ),
        (
            {
                "overall_score_100": 70,
                "edges_100": {"audience_content": 70, "product_content": inf},
            },
            "product_content",
        ),
        ({"overall_score_100": 70, "edges_100": "bad"}, "audience_content"),
    ],
)
def test_planting_gate_rejects_invalid_triangle_values(triangle, failed_check):
    result = evaluate_planting_content_gate(PLANTING_METRICS, triangle)

    assert result["pass"] is False
    assert failed_check in result["failed_checks"]


def test_soft_ad_gate_accepts_boundaries_without_planting_pain_fields():
    result = evaluate_soft_ad_content_gate(SOFT_AD_METRICS, TRIANGLE)

    assert result["pass"] is True
    assert result["failed_checks"] == []
    assert result["gate_version"] == "soft_ad_v1"
    assert result["thresholds"] == {
        "human_watch_gate_score": 80,
        "golden_3s_gate_score": 70,
        "douyin_native_feel_score": 75,
        "structure_fit_score": 70,
        "triangle_floor": 70,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("human_watch_gate_score", 79),
        ("golden_3s_gate_score", 69),
        ("douyin_native_feel_score", 74),
        ("structure_fit_score", 69),
        ("human_watch_gate_score", True),
        ("golden_3s_gate_score", nan),
    ],
)
def test_soft_ad_gate_rejects_below_boundary_and_invalid_scores(field, value):
    result = evaluate_soft_ad_content_gate(_soft_metrics(**{field: value}), TRIANGLE)

    assert result["pass"] is False
    assert field in result["failed_checks"]


def test_soft_ad_gate_requires_triangle_but_not_planting_fields():
    triangle = _triangle(edges_100={"audience_content": 70, "product_content": 69})

    result = evaluate_soft_ad_content_gate(SOFT_AD_METRICS, triangle)

    assert result["pass"] is False
    assert "product_content" in result["failed_checks"]
    assert all("pain" not in check for check in result["failed_checks"])


@dataclass
class Profile:
    kind: str
    intent: str
    version: str


def _profile():
    return Profile(
        kind="video_planting",
        intent="planting",
        version="profile-v3",
    )


def _bridge():
    return {
        "pain_point": "做饭没味道",
        "solution": {"selling_point": "鲜味"},
        "relevance_module": "M1",
        "justification_module": "M4",
    }


def _prompt_blocks():
    return [{"block": 1, "prompt": "厨房场景"}]


def test_build_planting_contract_from_dataclass_and_deep_copies_inputs():
    profile = _profile()
    bridge = _bridge()
    metrics = _planting_metrics()
    triangle = _triangle()
    prompt_blocks = _prompt_blocks()

    result = build_content_contract(
        profile, bridge, metrics, triangle, prompt_blocks, "sha256:abc"
    )

    assert result == {
        "version": "2026-07-15.v1",
        "kind": "video_planting",
        "intent": "planting",
        "profile_version": "profile-v3",
        "north_star_metric": "a3_ratio",
        "pain_solution_bridge": bridge,
        "method": {"relevance_module": "M1", "justification_module": "M4"},
        "content_gate": evaluate_planting_content_gate(metrics, triangle),
        "script_vector_gate": triangle,
        "prompt_blocks": prompt_blocks,
        "upstream_fact_hash": "sha256:abc",
    }

    bridge["solution"]["selling_point"] = "mutated"
    triangle["edges_100"]["audience_content"] = 0
    prompt_blocks[0]["prompt"] = "mutated"
    assert result["pain_solution_bridge"]["solution"]["selling_point"] == "鲜味"
    assert result["method"] == {
        "relevance_module": "M1",
        "justification_module": "M4",
    }
    assert result["script_vector_gate"]["edges_100"]["audience_content"] == 70
    assert result["prompt_blocks"][0]["prompt"] == "厨房场景"


def test_build_planting_contract_supports_mapping_profile():
    profile = {
        "kind": "video_planting",
        "intent": "planting",
        "version": "mapping-v1",
    }

    result = build_content_contract(
        profile, _bridge(), PLANTING_METRICS, TRIANGLE, _prompt_blocks(), "hash"
    )

    assert result["profile_version"] == "mapping-v1"
    assert result["method"] == {
        "relevance_module": "M1",
        "justification_module": "M4",
    }


@pytest.mark.parametrize("bridge", [None, {}, [], "bad"])
def test_build_planting_contract_rejects_invalid_bridge(bridge):
    with pytest.raises(ValueError, match="bridge"):
        build_content_contract(
            _profile(), bridge, PLANTING_METRICS, TRIANGLE, _prompt_blocks(), "hash"
        )


@pytest.mark.parametrize(
    "bridge",
    [
        {"pain_point": "x", "justification_module": "M4"},
        {"pain_point": "x", "relevance_module": "M1"},
        {"pain_point": "x", "relevance_module": "", "justification_module": "M4"},
        {"pain_point": "x", "relevance_module": "M1", "justification_module": None},
    ],
)
def test_build_contract_rejects_missing_or_invalid_modules(bridge):

    with pytest.raises(ValueError, match="modules"):
        build_content_contract(
            _profile(), bridge, PLANTING_METRICS, TRIANGLE, _prompt_blocks(), "hash"
        )


def test_build_soft_ad_contract_has_same_envelope_without_pain_bridge():
    profile = {
        "kind": "video_soft_ad",
        "intent": "soft_ad",
        "version": "soft-v1",
    }
    prompt_blocks = _prompt_blocks()
    triangle = _triangle()

    result = build_soft_ad_content_contract(
        profile, SOFT_AD_METRICS, triangle, prompt_blocks
    )

    assert result == {
        "version": "2026-07-15.v1",
        "kind": "video_soft_ad",
        "intent": "soft_ad",
        "profile_version": "soft-v1",
        "north_star_metric": "completion_rate",
        "content_gate": evaluate_soft_ad_content_gate(SOFT_AD_METRICS, triangle),
        "script_vector_gate": triangle,
        "prompt_blocks": prompt_blocks,
        "upstream_fact_hash": None,
    }
    assert "pain_solution_bridge" not in result

    prompt_blocks[0]["prompt"] = "mutated"
    triangle["edges_100"]["product_content"] = 0
    assert result["prompt_blocks"][0]["prompt"] == "厨房场景"
    assert result["script_vector_gate"]["edges_100"]["product_content"] == 70
