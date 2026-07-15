"""Focused unit tests for the planting pain-solution bridge core."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.pain_solution_bridge import (
    canonical_upstream_fact_hash,
    extract_response_text,
    parse_bridge_payload,
    validate_bridge_pair,
    validate_pain_solution_bridge,
)


def _bridge(**overrides: object) -> dict[str, object]:
    bridge: dict[str, object] = {
        "audience_segment": "重视家常菜风味的年轻家庭",
        "portrait_evidence": [
            {
                "source": "portrait",
                "field": "trigger_scenes",
                "value": "下班后给孩子做晚饭",
            }
        ],
        "pack_calibration_evidence": [
            {"field": "city_tier", "value": "一二线城市"}
        ],
        "trigger_scene": "下班晚了，十分钟内要端出一盘孩子愿意吃的菜",
        "pain_point": "时间紧时，调味步骤多且味道容易失手",
        "pain_consequence": "孩子少吃几口，做饭的人也更挫败",
        "product_action": "酱油在起锅前完成提鲜和上色",
        "visible_result": "菜色均匀、鲜味清楚，端上桌就愿意夹",
        "product_evidence": [
            {
                "source": "sku",
                "field": "owner_selling_points",
                "value": "有机本酿造",
            }
        ],
        "belief_shift": "少一道反复补味，也能把家常菜做稳",
        "relevance_module": "M2",
        "justification_module": "M5",
    }
    bridge.update(overrides)
    return bridge


def _pair() -> list[dict[str, object]]:
    first = _bridge()
    second = copy.deepcopy(first)
    second.update(
        {
            "trigger_scene": "周末朋友临时来家里，想快速做一道像样的硬菜",
            "pain_point": "临时加菜时没有时间慢慢调整咸鲜和色泽",
            "pain_consequence": "成菜寡淡或颜色发灰，待客显得仓促",
        }
    )
    return [first, second]


def test_canonical_hash_is_order_independent_and_supports_domain_types() -> None:
    uid = UUID("12345678-1234-5678-1234-567812345678")
    left = {
        "uuid": uid,
        "date": date(2026, 7, 15),
        "datetime": datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc),
        "decimal": Decimal("12.3400"),
        "mapping": {"b": 2, "a": 1},
        "set": {"beta", "alpha"},
    }
    right = {
        "set": {"alpha", "beta"},
        "mapping": {"a": 1, "b": 2},
        "decimal": Decimal("12.3400"),
        "datetime": datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc),
        "date": date(2026, 7, 15),
        "uuid": uid,
    }

    digest = canonical_upstream_fact_hash(left)

    assert digest == canonical_upstream_fact_hash(right)
    assert len(digest) == 64
    assert digest == hashlib.sha256(
        json.dumps(
            {
                "date": "2026-07-15",
                "datetime": "2026-07-15T08:30:00+00:00",
                "decimal": "12.3400",
                "mapping": {"a": 1, "b": 2},
                "set": ["alpha", "beta"],
                "uuid": "12345678-1234-5678-1234-567812345678",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_canonical_hash_sorts_nested_sets_by_canonical_value() -> None:
    assert canonical_upstream_fact_hash({"facts": {Decimal("2"), Decimal("1")}}) == (
        canonical_upstream_fact_hash({"facts": {Decimal("1"), Decimal("2")}})
    )


def test_canonical_hash_rejects_unsupported_objects_and_non_string_keys() -> None:
    with pytest.raises(TypeError, match="unsupported"):
        canonical_upstream_fact_hash({"bad": object()})

    with pytest.raises(TypeError, match="mapping keys"):
        canonical_upstream_fact_hash({1: "not silently coerced"})


def test_validate_bridge_accepts_complete_grounded_bridge() -> None:
    assert validate_pain_solution_bridge(_bridge()) == {"ok": True, "errors": []}


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("audience_segment", ""),
        ("trigger_scene", "  "),
        ("pain_point", "未知"),
        ("pain_consequence", "null"),
        ("product_action", "待补"),
        ("visible_result", "暂无"),
        ("belief_shift", "无"),
        ("relevance_module", "M3"),
        ("justification_module", "M2"),
    ],
)
def test_validate_bridge_rejects_missing_text_and_invalid_modules(
    field: str, bad_value: object
) -> None:
    result = validate_pain_solution_bridge(_bridge(**{field: bad_value}))

    assert result["ok"] is False
    assert any(field in error for error in result["errors"])


@pytest.mark.parametrize("field", ["portrait_evidence", "pack_calibration_evidence", "product_evidence"])
def test_validate_bridge_requires_nonempty_evidence_lists(field: str) -> None:
    result = validate_pain_solution_bridge(_bridge(**{field: []}))

    assert result["ok"] is False
    assert any(field in error for error in result["errors"])


def test_pack_evidence_cannot_substitute_for_portrait_or_record_evidence() -> None:
    bridge = _bridge(
        portrait_evidence=[
            {"source": "pack", "field": "city_tier", "value": "一二线城市"}
        ]
    )

    result = validate_pain_solution_bridge(bridge)

    assert result["ok"] is False
    assert any("portrait_evidence" in error and "portrait|record" in error for error in result["errors"])


@pytest.mark.parametrize(
    ("field", "entry"),
    [
        (
            "portrait_evidence",
            {"source": "portrait", "field": " ", "value": "下班做饭"},
        ),
        (
            "pack_calibration_evidence",
            {"field": "city_tier", "value": "missing"},
        ),
        (
            "product_evidence",
            {"source": "sku", "field": "owner_selling_points", "value": ""},
        ),
    ],
)
def test_validate_bridge_rejects_blank_or_placeholder_evidence(
    field: str, entry: dict[str, str]
) -> None:
    result = validate_pain_solution_bridge(_bridge(**{field: [entry]}))

    assert result["ok"] is False
    assert any(field in error for error in result["errors"])


def test_validate_bridge_rejects_wrong_product_evidence_source() -> None:
    result = validate_pain_solution_bridge(
        _bridge(
            product_evidence=[
                {"source": "portrait", "field": "claim", "value": "有机本酿造"}
            ]
        )
    )

    assert result["ok"] is False
    assert any("product_evidence" in error and "sku|matrix" in error for error in result["errors"])


@pytest.mark.parametrize("pain_point", ["年龄 25-34岁", "一线城市女性", "年龄：25-34岁，女性"])
def test_validate_bridge_rejects_attribute_only_pain_points(pain_point: str) -> None:
    result = validate_pain_solution_bridge(_bridge(pain_point=pain_point))

    assert result["ok"] is False
    assert any("pain_point" in error and "attribute" in error for error in result["errors"])


def test_validate_bridge_allows_demographic_context_inside_a_real_pain() -> None:
    result = validate_pain_solution_bridge(
        _bridge(
            pain_point="一线城市女性下班后赶着做晚饭，调味步骤占用本就有限的时间"
        )
    )

    assert result == {"ok": True, "errors": []}


def test_validate_bridge_rejects_slogan_equality_after_normalization() -> None:
    result = validate_pain_solution_bridge(
        _bridge(product_action="一拌、即鲜！", visible_result="一拌 即鲜")
    )

    assert result["ok"] is False
    assert any("product_action" in error and "visible_result" in error for error in result["errors"])


def test_evidence_catalog_matches_values_by_source_and_pack_is_separate() -> None:
    catalog = {
        "portrait": "典型触发场景：下班后给孩子做晚饭。",
        "record": "补充记录。",
        "pack": "城市层级以一二线城市为主。",
        "sku": "货品事实：有机本酿造。",
        "matrix": "矩阵备用事实。",
    }

    assert validate_pain_solution_bridge(_bridge(), catalog)["ok"] is True

    wrong_source_catalog = dict(catalog)
    wrong_source_catalog["pack"] = "城市层级未知"
    wrong_source_catalog["portrait"] += " 一二线城市"
    result = validate_pain_solution_bridge(_bridge(), wrong_source_catalog)
    assert result["ok"] is False
    assert any("pack_calibration_evidence" in error and "catalog" in error for error in result["errors"])


def test_evidence_catalog_reports_each_unmatched_source_value() -> None:
    catalog = {"portrait": "别的场景", "pack": "别的层级", "sku": "别的卖点"}

    result = validate_pain_solution_bridge(_bridge(), catalog)

    assert result["ok"] is False
    assert len([error for error in result["errors"] if "catalog" in error]) == 3


def test_validate_pair_accepts_two_bridges_with_only_pain_path_variation() -> None:
    assert validate_bridge_pair(_pair()) == {"ok": True, "errors": []}


@pytest.mark.parametrize("bad_pair", [[], [_bridge()], [_bridge(), _bridge(), _bridge()]])
def test_validate_pair_requires_exactly_two_bridges(bad_pair: list[dict[str, object]]) -> None:
    result = validate_bridge_pair(bad_pair)

    assert result["ok"] is False
    assert result["errors"] == ["bridges must contain exactly 2 items"]


def test_validate_pair_requires_fixed_fields_to_match() -> None:
    bridges = _pair()
    bridges[1]["belief_shift"] = "换了一个结论"

    result = validate_bridge_pair(bridges)

    assert result["ok"] is False
    assert any("belief_shift" in error and "identical" in error for error in result["errors"])


def test_validate_pair_requires_distinct_three_field_pain_paths() -> None:
    bridges = [_bridge(), copy.deepcopy(_bridge())]

    result = validate_bridge_pair(bridges)

    assert result["ok"] is False
    assert any("trigger_scene/pain_point/pain_consequence" in error for error in result["errors"])


def test_validate_pair_includes_indexed_item_errors() -> None:
    bridges = _pair()
    bridges[1]["visible_result"] = "待补"

    result = validate_bridge_pair(bridges)

    assert result["ok"] is False
    assert any(error.startswith("bridges[1].visible_result") for error in result["errors"])


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("plain", "plain"),
        ({"content": "dict-content"}, "dict-content"),
        ({"text": "dict-text"}, "dict-text"),
        (
            {"choices": [{"message": {"content": "openai"}}]},
            "openai",
        ),
        (
            {
                "candidates": [
                    {"content": {"parts": [{"text": "gemini "}, {"text": "parts"}]}}
                ]
            },
            "gemini parts",
        ),
        (SimpleNamespace(text="attribute-text"), "attribute-text"),
        (
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="object-openai"))]
            ),
            "object-openai",
        ),
        (
            SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        content=SimpleNamespace(
                            parts=[SimpleNamespace(text="object-"), SimpleNamespace(text="gemini")]
                        )
                    )
                ]
            ),
            "object-gemini",
        ),
    ],
)
def test_extract_response_text_supports_common_shapes(response: object, expected: str) -> None:
    assert extract_response_text(response) == expected


def test_extract_response_text_rejects_empty_or_unknown_shapes() -> None:
    with pytest.raises(ValueError, match="text"):
        extract_response_text({"choices": []})


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(_pair(), ensure_ascii=False),
        json.dumps({"bridges": _pair()}, ensure_ascii=False),
        "```json\n" + json.dumps({"bridges": _pair()}, ensure_ascii=False) + "\n```",
        "Here is the payload:\n```JSON\n" + json.dumps(_pair(), ensure_ascii=False) + "\n```\nDone.",
    ],
)
def test_parse_bridge_payload_accepts_plain_or_fenced_supported_roots(text: str) -> None:
    assert parse_bridge_payload(text) == _pair()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json", "valid JSON"),
        ("{}", "bridges"),
        ('{"bridges": {}}', "list"),
        ('{"bridges": [1, 2]}', "objects"),
    ],
)
def test_parse_bridge_payload_rejects_malformed_or_non_object_bridges(
    text: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_bridge_payload(text)
