"""Focused unit tests for the planting pain-solution bridge core."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
import yaml

from app.mcp import model_config, prompts
from app.services import pain_solution_bridge as bridge_service
from app.services.pain_solution_bridge import (
    canonical_upstream_fact_hash,
    extract_response_text,
    load_planting_bridge_context,
    parse_bridge_payload,
    validate_bridge_pair,
    validate_pain_solution_bridge,
)


SKU_ID = "SKU-TEST-001"
RECORD_ID = "11111111-1111-4111-8111-111111111111"
MATRIX_ID = "22222222-2222-4222-8222-222222222222"
RUN_ID = "33333333-3333-4333-8333-333333333333"
PORTRAIT_ID = "44444444-4444-4444-8444-444444444444"
PACK_ID = "55555555-5555-4555-8555-555555555555"
_UNSET = object()


class _FakePool:
    def __init__(self, sku: dict[str, object] | None) -> None:
        self.sku = sku
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        self.calls.append((query, args))
        return copy.deepcopy(self.sku)


def _sku() -> dict[str, object]:
    return {
        "id": SKU_ID,
        "name": "test seasoning",
        "category": "seasoning",
        "price_min": Decimal("29.90"),
        "price_max": Decimal("39.90"),
        "specifications": '{"volume":"500ml"}',
        "owner_selling_points": '["organic brew","fresh taste"]',
        "owner_notes": "owner note",
        "platform_status": "active",
    }


def _record(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": RECORD_ID,
        "audience_run_id": RUN_ID,
        "matrix_run_id": MATRIX_ID,
        "sku_id": SKU_ID,
        "ordinal": 2,
        "name": "busy family cook",
        "kb_doc": "audience study",
        "kb_section": "family dinner",
        "kb_chunk_text": "weeknight dinner must be fast and reliable",
        "match_reasons": ["needs stable flavor"],
        "layer_tags": ["family cook"],
        "raw_md_segment": "record raw markdown",
        "status": "adopted",
        "selected_for_pack": False,
    }
    value.update(overrides)
    return value


def _matrix(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": MATRIX_ID,
        "sku_id": SKU_ID,
        "matrix_md": "matrix evidence: organic brew and stable flavor",
        "status": "adopted",
    }
    value.update(overrides)
    return value


def _portrait(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": PORTRAIT_ID,
        "audience_record_id": RECORD_ID,
        "audience_run_id": RUN_ID,
        "matrix_run_id": MATRIX_ID,
        "sku_id": SKU_ID,
        "portrait_md": "portrait evidence: rushed weeknight family dinner",
        "status": "adopted",
    }
    value.update(overrides)
    return value


def _pack(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": PACK_ID,
        "audience_record_id": RECORD_ID,
        "audience_run_id": RUN_ID,
        "matrix_run_id": MATRIX_ID,
        "sku_id": SKU_ID,
        "pack_md": "pack calibration: high-value city users",
        "dmp_tags": ["high consumption", "tier 1-2 city"],
        "status": "adopted",
    }
    value.update(overrides)
    return value


def _install_lineage_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sku: dict[str, object] | None | object = _UNSET,
    record: dict[str, object] | None | object = _UNSET,
    matrix: dict[str, object] | None | object = _UNSET,
    portrait: dict[str, object] | None | object = _UNSET,
    pack: dict[str, object] | None | object = _UNSET,
) -> tuple[_FakePool, list[tuple[str, str]]]:
    resolved_sku = _sku() if sku is _UNSET else sku
    assert resolved_sku is None or isinstance(resolved_sku, dict)
    pool = _FakePool(resolved_sku)
    calls: list[tuple[str, str]] = []

    async def get_record(value: str) -> dict[str, object] | None:
        calls.append(("record", value))
        resolved = _record() if record is _UNSET else record
        assert resolved is None or isinstance(resolved, dict)
        return copy.deepcopy(resolved)

    async def get_matrix(value: str) -> dict[str, object] | None:
        calls.append(("matrix", value))
        resolved = _matrix() if matrix is _UNSET else matrix
        assert resolved is None or isinstance(resolved, dict)
        return copy.deepcopy(resolved)

    async def get_portrait(value: str) -> dict[str, object] | None:
        calls.append(("portrait", value))
        resolved = _portrait() if portrait is _UNSET else portrait
        assert resolved is None or isinstance(resolved, dict)
        return copy.deepcopy(resolved)

    async def get_pack(value: str) -> dict[str, object] | None:
        calls.append(("pack", value))
        resolved = _pack() if pack is _UNSET else pack
        assert resolved is None or isinstance(resolved, dict)
        return copy.deepcopy(resolved)

    monkeypatch.setattr(bridge_service, "get_pool", lambda: pool)
    monkeypatch.setattr(bridge_service.pipeline_lineage, "get_audience_record", get_record)
    monkeypatch.setattr(bridge_service.pipeline_lineage, "get_matrix_run", get_matrix)
    monkeypatch.setattr(bridge_service.pipeline_lineage, "get_audience_portrait", get_portrait)
    monkeypatch.setattr(bridge_service.pipeline_lineage, "get_audience_pack", get_pack)
    return pool, calls


def _bridge(**overrides: object) -> dict[str, object]:
    bridge: dict[str, object] = {
        "audience_segment": "重视家常菜风味的年轻家庭",
        "portrait_evidence": [
            {
                "source": "portrait",
                "field": "portrait_md",
                "value": "下班后给孩子做晚饭",
            }
        ],
        "pack_calibration_evidence": [
            {"field": "pack_md", "value": "一二线城市"}
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
    bridge = _bridge()

    assert validate_pain_solution_bridge(bridge) == {
        "ok": True,
        "bridge": bridge,
        "missing_or_invalid": [],
        "errors": [],
    }


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


@pytest.mark.parametrize("field", ["portrait_evidence", "product_evidence"])
def test_validate_bridge_requires_nonempty_evidence_lists(field: str) -> None:
    result = validate_pain_solution_bridge(_bridge(**{field: []}))

    assert result["ok"] is False
    assert any(field in error for error in result["errors"])


def test_validate_bridge_pack_evidence_policy_tracks_real_pack_context() -> None:
    no_pack = _bridge(pack_calibration_evidence=[])
    assert validate_pain_solution_bridge(
        no_pack,
        evidence_catalog={
            "portrait": {
                "portrait_md": no_pack["portrait_evidence"][0]["value"]
            },
            "sku": {
                "owner_selling_points": no_pack["product_evidence"][0]["value"]
            },
        },
    )["ok"] is True

    packed = validate_pain_solution_bridge(
        no_pack,
        evidence_catalog={
            "portrait": {
                "portrait_md": no_pack["portrait_evidence"][0]["value"]
            },
            "sku": {
                "owner_selling_points": no_pack["product_evidence"][0]["value"]
            },
            "pack": {"pack_md": "pack calibration exists"},
        },
    )
    assert packed["ok"] is False
    assert "pack_calibration_evidence" in packed["missing_or_invalid"]

    fabricated = _bridge()
    ungrounded = validate_pain_solution_bridge(
        fabricated,
        evidence_catalog={
            "portrait": {
                "portrait_md": fabricated["portrait_evidence"][0]["value"]
            },
            "sku": {
                "owner_selling_points": fabricated["product_evidence"][0]["value"]
            },
        },
    )
    assert ungrounded["ok"] is False
    assert any("pack_calibration_evidence" in error for error in ungrounded["errors"])


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

    assert result["ok"] is True
    assert result["bridge"]["pain_point"]
    assert result["missing_or_invalid"] == []
    assert result["errors"] == []


@pytest.mark.parametrize(
    "bridge",
    [
        {**_bridge(), "unexpected": "must fail"},
        {key: value for key, value in _bridge().items() if key != "belief_shift"},
        {
            **_bridge(),
            "portrait_evidence": [
                {
                    **_bridge()["portrait_evidence"][0],
                    "invented_confidence": 0.99,
                }
            ],
        },
        {
            **_bridge(),
            "product_evidence": [
                {
                    **_bridge()["product_evidence"][0],
                    "invented_confidence": 0.99,
                }
            ],
        },
    ],
)
def test_validate_bridge_rejects_missing_or_extra_schema_keys(
    bridge: dict[str, object],
) -> None:
    result = validate_pain_solution_bridge(bridge)

    assert result["ok"] is False
    assert result["error"] == "pain_solution_bridge_invalid"
    assert result["missing_or_invalid"]
    assert any(
        marker in " ".join(result["errors"])
        for marker in ("unexpected", "missing")
    )


def test_validate_bridge_rejects_slogan_equality_after_normalization() -> None:
    result = validate_pain_solution_bridge(
        _bridge(product_action="一拌、即鲜！", visible_result="一拌 即鲜")
    )

    assert result["ok"] is False
    assert any("product_action" in error and "visible_result" in error for error in result["errors"])


def test_legacy_flat_evidence_catalog_matches_known_field_labels() -> None:
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


def test_legacy_flat_evidence_catalog_reports_each_unmatched_value() -> None:
    catalog = {"portrait": "别的场景", "pack": "别的层级", "sku": "别的卖点"}

    result = validate_pain_solution_bridge(_bridge(), catalog)

    assert result["ok"] is False
    assert len([error for error in result["errors"] if "catalog" in error]) == 3


def test_legacy_flat_catalog_rejects_unknown_claimed_field() -> None:
    bridge = _bridge(
        portrait_evidence=[
            {
                "source": "portrait",
                "field": "invented_field",
                "value": "weeknight dinner",
            }
        ]
    )
    result = validate_pain_solution_bridge(
        bridge,
        {
            "portrait": "weeknight dinner",
            "pack": bridge["pack_calibration_evidence"][0]["value"],
            "sku": bridge["product_evidence"][0]["value"],
        },
    )

    assert result["ok"] is False
    assert any("field" in error and "not present" in error for error in result["errors"])


@pytest.mark.parametrize("bad_value", ["a", "鲜", "!!!", "\u200b"])
def test_evidence_value_requires_two_meaningful_characters(bad_value: str) -> None:
    bridge = _bridge(
        portrait_evidence=[
            {"source": "portrait", "field": "portrait_md", "value": bad_value}
        ]
    )
    result = validate_pain_solution_bridge(
        bridge,
        {
            "portrait": {"portrait_md": f"prefix {bad_value} suffix"},
            "pack": {
                "pack_md": bridge["pack_calibration_evidence"][0]["value"]
            },
            "sku": {
                "owner_selling_points": bridge["product_evidence"][0]["value"]
            },
        },
    )

    assert result["ok"] is False
    assert any("meaningful" in error for error in result["errors"])


@pytest.mark.parametrize("good_value", ["鲜味", "5度", "10ml"])
def test_evidence_value_allows_two_plus_cjk_or_numeric_unit_text(
    good_value: str,
) -> None:
    bridge = _bridge(
        portrait_evidence=[
            {"source": "portrait", "field": "portrait_md", "value": good_value}
        ]
    )
    result = validate_pain_solution_bridge(
        bridge,
        {
            "portrait": {"portrait_md": f"prefix {good_value} suffix"},
            "pack": {
                "pack_md": bridge["pack_calibration_evidence"][0]["value"]
            },
            "sku": {
                "owner_selling_points": bridge["product_evidence"][0]["value"]
            },
        },
    )

    assert result["ok"] is True


def test_evidence_field_must_exist_and_value_must_match_that_exact_field() -> None:
    bridge = _bridge(
        portrait_evidence=[
            {
                "source": "portrait",
                "field": "missing_field",
                "value": "weeknight dinner",
            }
        ]
    )
    base_catalog = {
        "pack": {"pack_md": bridge["pack_calibration_evidence"][0]["value"]},
        "sku": {
            "owner_selling_points": bridge["product_evidence"][0]["value"]
        },
    }
    missing_field = validate_pain_solution_bridge(
        bridge,
        {**base_catalog, "portrait": {"portrait_md": "weeknight dinner"}},
    )
    assert missing_field["ok"] is False
    assert any("field" in error and "not present" in error for error in missing_field["errors"])

    bridge["portrait_evidence"][0]["field"] = "portrait_md"
    wrong_field = validate_pain_solution_bridge(
        bridge,
        {
            **base_catalog,
            "portrait": {
                "portrait_md": "different content",
                "other_field": "weeknight dinner",
            },
        },
    )
    assert wrong_field["ok"] is False
    assert any("exact field" in error for error in wrong_field["errors"])


def test_validate_pair_accepts_two_bridges_with_only_pain_path_variation() -> None:
    bridges = _pair()

    assert validate_bridge_pair(bridges) == {
        "ok": True,
        "bridges": bridges,
        "missing_or_invalid": [],
        "errors": [],
    }


@pytest.mark.parametrize("bad_pair", [[], [_bridge()], [_bridge(), _bridge(), _bridge()]])
def test_validate_pair_requires_exactly_two_bridges(bad_pair: list[dict[str, object]]) -> None:
    result = validate_bridge_pair(bad_pair)

    assert result["ok"] is False
    assert result["error"] == "pain_solution_bridge_invalid"
    assert result["missing_or_invalid"] == ["bridges"]
    assert result["errors"] == ["bridges must contain exactly 2 items"]


def test_validate_pair_rejects_same_extra_root_key_on_both_candidates() -> None:
    bridges = _pair()
    bridges[0]["invented_score"] = 91
    bridges[1]["invented_score"] = 91

    result = validate_bridge_pair(bridges)

    assert result["ok"] is False
    assert "bridges[0].invented_score" in result["missing_or_invalid"]
    assert "bridges[1].invented_score" in result["missing_or_invalid"]


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


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _expected_field_catalog(values: dict[str, object]) -> dict[str, str]:
    return {
        field: value if isinstance(value, str) else _stable_json(value)
        for field, value in values.items()
    }


@pytest.mark.asyncio
async def test_load_context_without_pack_returns_stable_facts_and_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool, calls = _install_lineage_fakes(monkeypatch)

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    expected_sku = {
        "id": SKU_ID,
        "name": "test seasoning",
        "category": "seasoning",
        "price_min": Decimal("29.90"),
        "price_max": Decimal("39.90"),
        "specifications": {"volume": "500ml"},
        "owner_selling_points": ["organic brew", "fresh taste"],
        "owner_notes": "owner note",
        "platform_status": "active",
    }
    expected_record = _record()
    expected_facts = {
        "lineage": {
            "sku_id": SKU_ID,
            "matrix_run_id": MATRIX_ID,
            "audience_run_id": RUN_ID,
            "audience_record_id": RECORD_ID,
            "portrait_id": PORTRAIT_ID,
            "audience_pack_id": None,
        },
        "sku_facts": expected_sku,
        "matrix_evidence": {
            "id": MATRIX_ID,
            "matrix_md": "matrix evidence: organic brew and stable flavor",
        },
        "portrait_record_evidence": {
            "record": expected_record,
            "portrait": {
                "id": PORTRAIT_ID,
                "portrait_md": "portrait evidence: rushed weeknight family dinner",
            },
        },
        "pack_calibration": None,
        "eligible_evidence_catalog": {
            "sku": _expected_field_catalog(expected_sku),
            "matrix": {
                "matrix_md": "matrix evidence: organic brew and stable flavor"
            },
            "record": _expected_field_catalog(expected_record),
            "portrait": {
                "portrait_md": "portrait evidence: rushed weeknight family dinner"
            },
        },
        "pack_calibration_catalog": {},
    }
    assert result == {
        "ok": True,
        "facts": expected_facts,
        "upstream_fact_hash": canonical_upstream_fact_hash(expected_facts),
    }
    assert calls == [
        ("record", RECORD_ID),
        ("matrix", MATRIX_ID),
        ("portrait", PORTRAIT_ID),
    ]
    assert len(pool.calls) == 1
    query, args = pool.calls[0]
    assert args == (SKU_ID,)
    compact_query = " ".join(query.split()).lower()
    assert compact_query == (
        "select id,name,category,price_min,price_max,specifications,"
        "owner_selling_points,owner_notes,platform_status "
        "from mvp_sku where id=$1"
    )


@pytest.mark.asyncio
async def test_load_context_with_pack_keeps_calibration_outside_eligible_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(monkeypatch)

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID
    )

    assert result["ok"] is True
    facts = result["facts"]
    assert facts["lineage"]["audience_pack_id"] == PACK_ID
    assert facts["pack_calibration"] == {
        "id": PACK_ID,
        "pack_md": "pack calibration: high-value city users",
        "dmp_tags": ["high consumption", "tier 1-2 city"],
    }
    assert facts["pack_calibration_catalog"] == {
        "pack_md": "pack calibration: high-value city users",
        "dmp_tags": _stable_json(["high consumption", "tier 1-2 city"]),
    }
    assert set(facts["eligible_evidence_catalog"]) == {
        "sku",
        "matrix",
        "record",
        "portrait",
    }
    assert "pack calibration" not in _stable_json(
        facts["eligible_evidence_catalog"]
    )
    assert calls[-1] == ("pack", PACK_ID)
    assert result["upstream_fact_hash"] == canonical_upstream_fact_hash(facts)


@pytest.mark.asyncio
async def test_load_context_normalizes_uppercase_explicit_uuids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(monkeypatch)

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID.upper(), PORTRAIT_ID.upper(), PACK_ID.upper()
    )

    assert result["ok"] is True
    assert calls == [
        ("record", RECORD_ID),
        ("matrix", MATRIX_ID),
        ("portrait", PORTRAIT_ID),
        ("pack", PACK_ID),
    ]


@pytest.mark.asyncio
async def test_load_context_does_not_fetch_pack_when_id_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(monkeypatch)

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID, None
    )

    assert result["ok"] is True
    assert all(name != "pack" for name, _ in calls)


@pytest.mark.asyncio
async def test_load_context_never_uses_list_or_latest_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_lineage_fakes(monkeypatch)

    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("list/latest lineage helper must not be used")

    for name in (
        "list_audience_records",
        "list_matrix_runs",
        "list_audience_portraits",
        "list_audience_packs",
        "get_latest_audience_record",
        "get_latest_audience_portrait",
    ):
        monkeypatch.setattr(
            bridge_service.pipeline_lineage,
            name,
            forbidden,
            raising=False,
        )

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID
    )

    assert result["ok"] is True


def _assert_lineage_failure(
    result: dict[str, object], reason: str
) -> None:
    assert result["ok"] is False
    assert result["error"] == "upstream_lineage_incomplete"
    assert result["reason"] == reason
    assert isinstance(result["passed_checks"], list)
    assert isinstance(result["lineage"], dict)
    assert isinstance(result["detail"], dict)


@pytest.mark.asyncio
async def test_load_context_reports_sku_not_found_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(monkeypatch, sku=None)

    result = await load_planting_bridge_context(
        SKU_ID, "not-a-uuid", "also-not-a-uuid"
    )

    _assert_lineage_failure(result, "sku_not_found")
    assert result["passed_checks"] == []
    assert calls == []


@pytest.mark.asyncio
async def test_load_context_reports_malformed_record_uuid_without_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(monkeypatch)

    result = await load_planting_bridge_context(
        SKU_ID, "not-a-uuid", "also-not-a-uuid"
    )

    _assert_lineage_failure(result, "invalid_audience_record_id")
    assert result["passed_checks"] == ["sku_exists"]
    assert calls == []


@pytest.mark.asyncio
async def test_load_context_reports_record_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(monkeypatch, record=None)

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, "not-a-uuid"
    )

    _assert_lineage_failure(result, "record_not_found")
    assert calls == [("record", RECORD_ID)]


@pytest.mark.asyncio
async def test_load_context_reports_record_sku_mismatch_before_later_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(
        monkeypatch, record=_record(sku_id="SKU-OTHER")
    )

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, "not-a-uuid"
    )

    _assert_lineage_failure(result, "record_sku_mismatch")
    assert calls == [("record", RECORD_ID)]


@pytest.mark.asyncio
async def test_load_context_rejects_unselected_draft_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(
        monkeypatch,
        record=_record(status="draft", selected_for_pack=False),
        matrix=None,
    )

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    _assert_lineage_failure(result, "record_not_eligible")
    assert calls == [("record", RECORD_ID)]


@pytest.mark.asyncio
async def test_selected_for_pack_allows_draft_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_lineage_fakes(
        monkeypatch,
        record=_record(status="draft", selected_for_pack=True),
    )

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    assert result["ok"] is True


@pytest.mark.asyncio
async def test_load_context_reports_matrix_missing_and_not_adopted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, missing_calls = _install_lineage_fakes(monkeypatch, matrix=None)
    missing = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )
    _assert_lineage_failure(missing, "matrix_not_found")
    assert missing_calls == [("record", RECORD_ID), ("matrix", MATRIX_ID)]

    _, draft_calls = _install_lineage_fakes(
        monkeypatch, matrix=_matrix(status="draft")
    )
    draft = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )
    _assert_lineage_failure(draft, "matrix_not_adopted")
    assert draft_calls == [("record", RECORD_ID), ("matrix", MATRIX_ID)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "66666666-6666-4666-8666-666666666666"},
        {"sku_id": "SKU-OTHER"},
    ],
)
async def test_load_context_compares_matrix_id_and_sku_lineage(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    _, calls = _install_lineage_fakes(
        monkeypatch, matrix=_matrix(**overrides)
    )

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    _assert_lineage_failure(result, "matrix_lineage_mismatch")
    assert all(name != "portrait" for name, _ in calls)


@pytest.mark.asyncio
async def test_load_context_reports_malformed_portrait_uuid_after_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(monkeypatch)

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, "not-a-uuid"
    )

    _assert_lineage_failure(result, "invalid_portrait_id")
    assert calls == [("record", RECORD_ID), ("matrix", MATRIX_ID)]


@pytest.mark.asyncio
async def test_load_context_reports_portrait_missing_and_not_adopted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, missing_calls = _install_lineage_fakes(monkeypatch, portrait=None)
    missing = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )
    _assert_lineage_failure(missing, "portrait_not_found")
    assert missing_calls[-1] == ("portrait", PORTRAIT_ID)

    _, draft_calls = _install_lineage_fakes(
        monkeypatch, portrait=_portrait(status="draft")
    )
    draft = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )
    _assert_lineage_failure(draft, "portrait_not_adopted")
    assert draft_calls[-1] == ("portrait", PORTRAIT_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"sku_id": "SKU-OTHER"},
        {"audience_record_id": "66666666-6666-4666-8666-666666666666"},
        {"audience_run_id": "66666666-6666-4666-8666-666666666666"},
        {"matrix_run_id": "66666666-6666-4666-8666-666666666666"},
    ],
)
async def test_load_context_compares_all_four_portrait_lineage_fields(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    _, calls = _install_lineage_fakes(
        monkeypatch, portrait=_portrait(**overrides)
    )

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID
    )

    _assert_lineage_failure(result, "portrait_lineage_mismatch")
    assert all(name != "pack" for name, _ in calls)


@pytest.mark.asyncio
async def test_load_context_reports_malformed_pack_uuid_without_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_lineage_fakes(monkeypatch)

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID, "not-a-uuid"
    )

    _assert_lineage_failure(result, "invalid_audience_pack_id")
    assert all(name != "pack" for name, _ in calls)


@pytest.mark.asyncio
async def test_load_context_reports_pack_missing_and_not_adopted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, missing_calls = _install_lineage_fakes(monkeypatch, pack=None)
    missing = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID
    )
    _assert_lineage_failure(missing, "pack_not_found")
    assert missing_calls[-1] == ("pack", PACK_ID)

    _, draft_calls = _install_lineage_fakes(
        monkeypatch, pack=_pack(status="draft")
    )
    draft = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID
    )
    _assert_lineage_failure(draft, "pack_not_adopted")
    assert draft_calls[-1] == ("pack", PACK_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"sku_id": "SKU-OTHER"},
        {"audience_record_id": "66666666-6666-4666-8666-666666666666"},
        {"audience_run_id": "66666666-6666-4666-8666-666666666666"},
        {"matrix_run_id": "66666666-6666-4666-8666-666666666666"},
    ],
)
async def test_load_context_compares_all_four_pack_lineage_fields(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    _install_lineage_fakes(monkeypatch, pack=_pack(**overrides))

    result = await load_planting_bridge_context(
        SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID
    )

    _assert_lineage_failure(result, "pack_lineage_mismatch")


# --- MCP tool contract -----------------------------------------------------


def _planting_tool_module():
    return importlib.import_module("app.mcp.tools.planting")


def _tool_context() -> dict[str, object]:
    bridges = _pair()
    first = bridges[0]
    portrait_value = first["portrait_evidence"][0]["value"]
    product_value = first["product_evidence"][0]["value"]
    pack_value = first["pack_calibration_evidence"][0]["value"]
    facts = {
        "lineage": {"sku_id": SKU_ID, "audience_record_id": RECORD_ID},
        "sku_facts": {"id": SKU_ID, "owner_selling_points": product_value},
        "matrix_evidence": {"matrix_md": product_value},
        "portrait_record_evidence": {
            "record": {"name": first["audience_segment"]},
            "portrait": {"portrait_md": portrait_value},
        },
        "pack_calibration": {"pack_md": pack_value},
        "eligible_evidence_catalog": {
            "sku": {"owner_selling_points": str(product_value)},
            "matrix": {"matrix_md": str(product_value)},
            "record": {"name": str(first["audience_segment"])},
            "portrait": {"portrait_md": str(portrait_value)},
        },
        "pack_calibration_catalog": {"pack_md": str(pack_value)},
    }
    return {
        "ok": True,
        "facts": facts,
        "upstream_fact_hash": canonical_upstream_fact_hash(facts),
    }


def _tool_context_without_pack() -> dict[str, object]:
    context = copy.deepcopy(_tool_context())
    facts = context["facts"]
    facts["pack_calibration"] = None
    facts["pack_calibration_catalog"] = {}
    context["upstream_fact_hash"] = canonical_upstream_fact_hash(facts)
    return context


class _FakeAIHubClient:
    calls: list[dict[str, object]] = []
    response: object = None
    failure: Exception | None = None
    timeouts: list[float] = []

    def __init__(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    async def chat(self, **kwargs: object) -> object:
        self.calls.append(copy.deepcopy(kwargs))
        if self.failure is not None:
            raise self.failure
        return copy.deepcopy(self.response)


def _install_tool_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: object | None = None,
    config: dict[str, object] | None = None,
    context: dict[str, object] | None = None,
) -> object:
    planting = _planting_tool_module()
    _FakeAIHubClient.calls = []
    _FakeAIHubClient.timeouts = []
    _FakeAIHubClient.failure = None
    _FakeAIHubClient.response = response
    monkeypatch.setattr(planting, "AIHubClient", _FakeAIHubClient)
    monkeypatch.setattr(
        planting,
        "get_model_for_tool",
        lambda _name: copy.deepcopy(
            config
            or {
                "provider": "gemini",
                "model": "gemini-3.1-pro-preview",
                "temperature": 0.2,
                "max_tokens": 4000,
                "prompts": {
                    "system": "planting_pain_solution_bridge.system",
                    "user": "planting_pain_solution_bridge.user",
                },
            }
        ),
    )

    async def fake_loader(*_args: object, **_kwargs: object) -> dict[str, object]:
        return copy.deepcopy(context or _tool_context())

    monkeypatch.setattr(planting, "load_planting_bridge_context", fake_loader)
    return planting


def test_bridge_tool_has_exact_base_yaml_config() -> None:
    raw = yaml.safe_load(model_config.CONFIG_PATH.read_text(encoding="utf-8"))

    assert raw["generate_planting_pain_solution_bridge"] == {
        "provider": "gemini",
        "model": "gemini-3.1-pro-preview",
        "temperature": 0.2,
        "max_tokens": 4000,
        "prompts": {
            "system": "planting_pain_solution_bridge.system",
            "user": "planting_pain_solution_bridge.user",
        },
    }


@pytest.mark.asyncio
async def test_bridge_tool_calls_pro_once_and_returns_review_only_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair = _pair()
    planting = _install_tool_fakes(
        monkeypatch,
        response={"content": json.dumps({"bridges": pair}, ensure_ascii=False)},
    )

    result = await planting._generate_planting_pain_solution_bridge_impl(
        SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID
    )

    assert result["ok"] is True
    assert result["result"]["bridges"] == pair
    assert result["result"]["upstream_fact_hash"] == _tool_context()["upstream_fact_hash"]
    assert result["next_step_hint"]["suggested_tool"] is None
    human_text = result["next_step_hint"]["human_text"]
    assert "审" in human_text
    assert "不会自动" in human_text
    assert _FakeAIHubClient.timeouts == [360]
    assert len(_FakeAIHubClient.calls) == 1
    call = _FakeAIHubClient.calls[0]
    assert call["provider"] == "gemini"
    assert call["model"] == "gemini-3.1-pro-preview"
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 4000
    assert call["enforce_human_voice"] is False
    assert [message["role"] for message in call["messages"]] == ["system", "user"]
    trace = result["trace"]
    assert trace["model_provider"] == "gemini"
    assert trace["model"] == "gemini-3.1-pro-preview"
    assert trace["params"]["temperature"] == 0.2
    assert trace["params"]["max_tokens"] == 4000
    assert trace["params"]["upstream_fact_hash"] == result["result"]["upstream_fact_hash"]
    assert trace["cost_estimate"] == "1 Gemini Pro call"


@pytest.mark.asyncio
async def test_bridge_tool_succeeds_without_optional_pack_and_requires_empty_pack_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair = _pair()
    for bridge in pair:
        bridge["pack_calibration_evidence"] = []
    planting = _install_tool_fakes(
        monkeypatch,
        context=_tool_context_without_pack(),
        response={"content": json.dumps({"bridges": pair}, ensure_ascii=False)},
    )

    result = await planting._generate_planting_pain_solution_bridge_impl(
        SKU_ID, RECORD_ID, PORTRAIT_ID, None
    )

    assert result["ok"] is True
    assert result["result"]["bridges"] == pair
    assert result["result"]["bridges"][0]["pack_calibration_evidence"] == []
    assert len(_FakeAIHubClient.calls) == 1


@pytest.mark.asyncio
async def test_bridge_tool_normalizes_validated_effective_config_for_call_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair = _pair()
    planting = _install_tool_fakes(
        monkeypatch,
        config={
            "provider": "gemini",
            "model": "gemini-3.1-pro-preview",
            "temperature": "0.2",
            "max_tokens": "4000",
            "prompts": {
                "system": "planting_pain_solution_bridge.system",
                "user": "planting_pain_solution_bridge.user",
            },
        },
        response={"content": json.dumps({"bridges": pair}, ensure_ascii=False)},
    )

    result = await planting._generate_planting_pain_solution_bridge_impl(
        SKU_ID, RECORD_ID, PORTRAIT_ID, PACK_ID
    )

    assert result["ok"] is True
    call = _FakeAIHubClient.calls[0]
    assert call["provider"] == "gemini"
    assert call["model"] == "gemini-3.1-pro-preview"
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 4000
    assert result["trace"]["model_provider"] == call["provider"]
    assert result["trace"]["model"] == call["model"]
    assert result["trace"]["params"]["temperature"] == call["temperature"]
    assert result["trace"]["params"]["max_tokens"] == call["max_tokens"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "bad_value"),
    [
        ("provider", "openai"),
        ("model", "gemini-3-flash-preview"),
        ("temperature", 0.3),
        ("max_tokens", 3999),
    ],
)
async def test_bridge_tool_rejects_every_model_config_drift_before_ai_call(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    bad_value: object,
) -> None:
    config = {
        "provider": "gemini",
        "model": "gemini-3.1-pro-preview",
        "temperature": 0.2,
        "max_tokens": 4000,
    }
    config[key] = bad_value
    planting = _install_tool_fakes(monkeypatch, config=config)

    result = await planting._generate_planting_pain_solution_bridge_impl(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    assert result["ok"] is False
    assert result["error"] == "pain_solution_bridge_model_misconfigured"
    assert key in result["detail"]
    assert _FakeAIHubClient.calls == []
    assert _FakeAIHubClient.timeouts == []


@pytest.mark.asyncio
async def test_bridge_tool_model_exception_is_one_call_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planting = _install_tool_fakes(monkeypatch)
    _FakeAIHubClient.failure = RuntimeError("provider unavailable")

    result = await planting._generate_planting_pain_solution_bridge_impl(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    assert result["ok"] is False
    assert result["error"] == "pain_solution_bridge_generation_failed"
    assert "provider unavailable" in result["detail"]
    assert len(_FakeAIHubClient.calls) == 1
    assert _FakeAIHubClient.calls[0]["model"] == "gemini-3.1-pro-preview"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error_fragment"),
    [
        ({"content": "not json"}, "valid JSON"),
        ({"content": '{"bridges": []}'}, "exactly 2"),
        (
            {
                "content": json.dumps(
                    {
                        "bridges": [
                            _bridge(
                                portrait_evidence=[
                                    {"source": "portrait", "field": "x", "value": "invented"}
                                ]
                            ),
                            _pair()[1],
                        ]
                    },
                    ensure_ascii=False,
                )
            },
            "evidence_catalog",
        ),
        (
            {
                "content": json.dumps(
                    {
                        "bridges": [
                            _pair()[0],
                            {**_pair()[1], "belief_shift": "changed fixed fact"},
                        ]
                    },
                    ensure_ascii=False,
                )
            },
            "cross_candidate_drift",
        ),
    ],
)
async def test_bridge_tool_fails_closed_on_invalid_model_payloads(
    monkeypatch: pytest.MonkeyPatch,
    response: object,
    error_fragment: str,
) -> None:
    planting = _install_tool_fakes(monkeypatch, response=response)

    result = await planting._generate_planting_pain_solution_bridge_impl(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    assert result["ok"] is False
    assert result["error"] == "pain_solution_bridge_invalid"
    assert result["missing_or_invalid"]
    assert error_fragment in json.dumps(result.get("errors"), ensure_ascii=False)
    assert len(_FakeAIHubClient.calls) == 1
    assert result["trace"]["params"]["upstream_fact_hash"] == _tool_context()["upstream_fact_hash"]


def test_bridge_prompt_replacement_is_single_pass_and_preserves_injected_sentinels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planting = _planting_tool_module()
    sentinels = tuple(planting._SENTINELS)
    names = tuple(planting._SENTINELS.values())
    user_template = "\n".join(
        f"{name}_BEGIN\n{sentinel}\n{name}_END"
        for sentinel, name in planting._SENTINELS.items()
    )

    def fake_load(name: str) -> str:
        if name.endswith(".system"):
            return "system prompt with literal JSON braces: {example}"
        return user_template

    monkeypatch.setattr(planting.prompts, "load", fake_load)
    marker_text = " | ".join(sentinels)
    facts = {name: {"payload": f"{name}: {marker_text}"} for name in names}

    _, rendered = planting._render_bridge_prompts(facts)

    for name in names:
        block = rendered.split(f"{name}_BEGIN\n", 1)[1].split(
            f"\n{name}_END", 1
        )[0]
        parsed = json.loads(block)
        assert parsed == {"payload": f"{name}: {marker_text}"}


@pytest.mark.parametrize("case", ["missing", "duplicate", "system"])
def test_bridge_prompt_requires_each_sentinel_exactly_once_in_user_template(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    planting = _planting_tool_module()
    sentinels = tuple(planting._SENTINELS)
    user_template = "\n".join(sentinels)
    system_template = "system"
    if case == "missing":
        user_template = user_template.replace(sentinels[0], "", 1)
    elif case == "duplicate":
        user_template += f"\n{sentinels[0]}"
    else:
        system_template += f"\n{sentinels[0]}"

    def fake_load(name: str) -> str:
        return system_template if name.endswith(".system") else user_template

    monkeypatch.setattr(planting.prompts, "load", fake_load)

    with pytest.raises(ValueError, match="sentinel"):
        planting._render_bridge_prompts(
            {facts_key: {"value": "grounded"} for facts_key in planting._SENTINELS.values()}
        )


def test_bridge_prompt_rendering_uses_safe_sentinels_and_all_upstream_sections() -> None:
    planting = _planting_tool_module()
    facts = _tool_context()["facts"]

    system_prompt, user_prompt = planting._render_bridge_prompts(facts)

    rendered = system_prompt + "\n" + user_prompt
    assert "{" in rendered and "}" in rendered
    assert SKU_ID in rendered
    assert str(facts["matrix_evidence"]["matrix_md"]) in rendered
    assert str(facts["portrait_record_evidence"]["portrait"]["portrait_md"]) in rendered
    assert str(facts["pack_calibration"]["pack_md"]) in rendered
    assert "SKU_FACTS_JSON" not in rendered
    assert "MATRIX_EVIDENCE_JSON" not in rendered
    assert "PORTRAIT_RECORD_EVIDENCE_JSON" not in rendered
    assert "PACK_CALIBRATION_JSON" not in rendered


@pytest.mark.asyncio
async def test_bridge_tool_returns_upstream_failure_without_ai_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream = {
        "ok": False,
        "error": "upstream_lineage_incomplete",
        "reason": "portrait_not_adopted",
    }
    planting = _install_tool_fakes(monkeypatch, context=upstream)

    result = await planting._generate_planting_pain_solution_bridge_impl(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    assert result == upstream
    assert _FakeAIHubClient.calls == []
    assert _FakeAIHubClient.timeouts == []


@pytest.mark.asyncio
async def test_bridge_tool_prioritizes_upstream_failure_over_bad_model_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream = {
        "ok": False,
        "error": "upstream_lineage_incomplete",
        "reason": "portrait_not_adopted",
    }
    planting = _install_tool_fakes(
        monkeypatch,
        context=upstream,
        config={
            "provider": "openai",
            "model": "wrong",
            "temperature": 9,
            "max_tokens": 1,
        },
    )

    result = await planting._generate_planting_pain_solution_bridge_impl(
        SKU_ID, RECORD_ID, PORTRAIT_ID
    )

    assert result == upstream
    assert _FakeAIHubClient.calls == []
    assert _FakeAIHubClient.timeouts == []


@pytest.mark.asyncio
async def test_bridge_tool_is_registered_in_server_doctor_and_prompt_contract() -> None:
    planting = _planting_tool_module()
    from app.mcp.doctor import _wanted_tools
    from app.mcp.server import mcp

    assert hasattr(planting, "generate_planting_pain_solution_bridge")
    assert "generate_planting_pain_solution_bridge" in _wanted_tools()
    names = {tool.name for tool in await mcp.list_tools()}
    assert "generate_planting_pain_solution_bridge" in names
    templates = set(prompts.list_templates())
    assert "planting_pain_solution_bridge.system" in templates
    assert "planting_pain_solution_bridge.user" in templates
