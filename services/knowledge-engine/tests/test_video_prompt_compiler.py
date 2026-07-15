from __future__ import annotations

import pytest

from app.services.video_intent_profiles import get_video_intent_profile
from app.services.video_prompt_compiler import (
    compile_final_prompt_segment,
    prompt_budget_for_duration,
)


def _unique_detail(prefix: str, count: int) -> str:
    return "".join(
        f"{prefix}{index:03d}保留人物动作表情产品位置光线变化。"
        for index in range(count)
    )


def _valid_source() -> dict:
    return {
        "identity_product_anchor": (
            "主角小林穿米色针织衫，保持同一张脸。"
            "和田宽寿喜烧汁保持方瓶、红盖和米白标签一致。"
        ),
        "reference_instruction": (
            "角色参考图锁定主角小林，产品参考图锁定和田宽寿喜烧汁。"
        ),
        "product_solution_action": (
            "主角把和田宽寿喜烧汁倒入锅中完成调味，停止反复找调料试味。"
        ),
        "timeline": (
            "0-3秒小林晚归进厨房放下通勤包；"
            "3-8秒小林把寿喜烧汁连续倒入锅中并翻动食材；"
            "8-15秒热气升起，小林把颜色均匀的热饭端上桌。"
        ),
        "scene_detail": _unique_detail("场景", 24),
        "sound_detail": "钥匙落桌声、锅中轻响、瓷碗放到桌面的清脆声。",
        "decorative_detail": "竖屏手机实拍，自然室内光，轻微手持感。",
        "negative": "禁止换脸、包装变形、手部畸形、乱码、动作跳变。",
        "required_anchors": {
            "character": "主角小林",
            "product": "和田宽寿喜烧汁",
            "action": "倒入锅中",
            "result": "热饭端上桌",
        },
    }


def test_prompt_budget_scales_with_segment_duration() -> None:
    profile = get_video_intent_profile("planting")

    budget = prompt_budget_for_duration(15, profile.prompt_budget)

    assert budget.min_chars == 750
    assert budget.recommended_chars == (900, 1305)
    assert budget.max_chars == 1605


@pytest.mark.parametrize("duration_seconds", [0, 16])
def test_prompt_budget_rejects_duration_outside_one_to_fifteen(
    duration_seconds: int,
) -> None:
    profile = get_video_intent_profile("planting")

    with pytest.raises(ValueError, match=r"^video_segment_duration_invalid$"):
        prompt_budget_for_duration(duration_seconds, profile.prompt_budget)


def test_compiler_orders_three_layers_and_preserves_executable_anchors() -> None:
    result = compile_final_prompt_segment(
        _valid_source(),
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is True
    prompt = result["final_prompt"]
    assert prompt.index("主角小林") < prompt.index("倒入锅中")
    assert prompt.index("倒入锅中") < prompt.index("禁止换脸")
    assert prompt.endswith("禁止换脸、包装变形、手部畸形、乱码、动作跳变。")
    assert result["char_count"] == len(prompt)
    assert result["failed_checks"] == []


def test_over_budget_prompt_removes_only_lower_priority_duplicates() -> None:
    source = _valid_source()
    source["identity_product_anchor"] += "竖屏手机实拍。"
    source["decorative_detail"] = (
        "竖屏手机实拍。" * 220
        + "独特装饰细节是窗边一盏暖黄小灯。"
    )

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is True
    assert result["char_count"] <= 1605
    assert result["final_prompt"].count("竖屏手机实拍。") == 1
    assert "独特装饰细节是窗边一盏暖黄小灯。" in result["final_prompt"]
    assert result["final_prompt"].endswith(source["negative"])


def test_unique_over_hard_max_fails_without_tail_truncation() -> None:
    source = _valid_source()
    source["identity_product_anchor"] = _unique_detail("独特身份", 120)

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_capacity_exceeded"
    assert "capacity" in result["failed_checks"]


def test_prompt_below_duration_scaled_minimum_fails_closed() -> None:
    source = _valid_source()
    source["scene_detail"] = "灶台有一束自然光。"

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_detail_insufficient"
    assert result["char_count"] < 750
    assert "min_chars" in result["failed_checks"]


def test_non_contiguous_timestamps_fail_with_structured_check() -> None:
    source = _valid_source()
    source["timeline"] = (
        "0-3秒小林晚归进厨房；"
        "4-8秒小林把寿喜烧汁倒入锅中；"
        "8-15秒小林把热饭端上桌。"
    )

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_detail_insufficient"
    assert "timestamp_continuity" in result["failed_checks"]


@pytest.mark.parametrize(
    ("category", "missing_anchor"),
    [
        ("character", "主角小林"),
        ("product", "和田宽寿喜烧汁"),
        ("action", "倒入锅中"),
        ("result", "热饭端上桌"),
    ],
    ids=["character", "product", "action", "result"],
)
def test_missing_executable_anchor_fails_explicitly(
    category: str,
    missing_anchor: str,
) -> None:
    source = _valid_source()
    for field, value in tuple(source.items()):
        if isinstance(value, str):
            source[field] = value.replace(missing_anchor, "替代描述")

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_detail_insufficient"
    assert f"required_anchor:{category}" in result["failed_checks"]


def test_required_anchor_mapping_requires_all_four_categories() -> None:
    source = _valid_source()
    source["required_anchors"] = {
        "character": "主角小林",
        "product": "和田宽寿喜烧汁",
        "action": "倒入锅中",
        "result": "热饭端上桌",
    }

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is True
    assert result["failed_checks"] == []


def test_required_anchor_list_schema_fails_even_with_all_four_positions() -> None:
    source = _valid_source()
    source["required_anchors"] = [
        "主角小林",
        "和田宽寿喜烧汁",
        "倒入锅中",
        "热饭端上桌",
    ]

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_detail_insufficient"
    assert "required_anchors_schema" in result["failed_checks"]


@pytest.mark.parametrize("category", ["character", "product", "action", "result"])
def test_required_anchor_mapping_fails_closed_when_category_missing(
    category: str,
) -> None:
    source = _valid_source()
    anchors = {
        "character": "主角小林",
        "product": "和田宽寿喜烧汁",
        "action": "倒入锅中",
        "result": "热饭端上桌",
    }
    anchors.pop(category)
    source["required_anchors"] = anchors

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_detail_insufficient"
    assert f"required_anchor:{category}" in result["failed_checks"]


def test_single_action_required_anchor_list_cannot_pass() -> None:
    source = _valid_source()
    source["required_anchors"] = ["倒入锅中"]

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_detail_insufficient"
    assert "required_anchor:product" in result["failed_checks"]
    assert "required_anchor:result" in result["failed_checks"]


def test_capacity_error_precedes_anchor_failures_without_truncation() -> None:
    source = _valid_source()
    source["identity_product_anchor"] = _unique_detail("独特身份", 120)
    source["required_anchors"] = {}

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_capacity_exceeded"
    assert result["char_count"] > result["budget"]["max_chars"]
    assert "capacity" in result["failed_checks"]
    assert "required_anchor:character" in result["failed_checks"]
    assert "required_anchor:product" in result["failed_checks"]
    assert "required_anchor:action" in result["failed_checks"]
    assert "required_anchor:result" in result["failed_checks"]


def test_unicode_code_points_and_inserted_whitespace_are_counted() -> None:
    source = _valid_source()
    source["sound_detail"] += " 人物轻声说：饭好了 🍲。"

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is True
    assert "饭好了 🍲" in result["final_prompt"]
    assert "\n" in result["final_prompt"]
    assert result["char_count"] == len(result["final_prompt"])


def test_compile_rejects_formal_segment_over_fifteen_seconds() -> None:
    result = compile_final_prompt_segment(
        _valid_source(),
        duration_seconds=22,
        intent="planting",
    )

    assert result == {
        "ok": False,
        "error": "video_segment_duration_invalid",
        "failed_checks": ["duration"],
    }


def test_same_priority_duplicates_are_not_deleted_to_fit_capacity() -> None:
    source = _valid_source()
    source["decorative_detail"] = "本层独有电影质感。" * 240

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_capacity_exceeded"
    assert result["compression"] == []


def test_negative_constraint_layer_is_required() -> None:
    source = _valid_source()
    source["negative"] = ""

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is False
    assert result["error"] == "prompt_detail_insufficient"
    assert "negative" in result["failed_checks"]


def test_compressed_timeline_is_validated_from_its_higher_priority_copy() -> None:
    source = _valid_source()
    source["product_solution_action"] = source["timeline"]
    source["scene_detail"] = _unique_detail("场景", 62)

    result = compile_final_prompt_segment(
        source,
        duration_seconds=15,
        intent="planting",
    )

    assert result["ok"] is True
    assert {item["field"] for item in result["compression"]} == {"timeline"}
    assert result["char_count"] <= 1605
    assert result["failed_checks"] == []
