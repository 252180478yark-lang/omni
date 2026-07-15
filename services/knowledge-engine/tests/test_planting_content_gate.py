from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from math import inf, nan
from typing import Any
from uuid import UUID

import pytest

from app.services import pipeline_lineage, video_content_gate
from app.services.video_content_gate import (
    assert_script_ready_for_media,
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


SCRIPT_ID = "11111111-1111-4111-8111-111111111111"
ARM_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EXPERIMENT_ID = "22222222-2222-4222-8222-222222222222"


def _ready_script(**updates: Any) -> dict[str, Any]:
    script: dict[str, Any] = {
        "id": SCRIPT_ID,
        "sku_id": "SKU-READY-1",
        "intent": "planting",
        "status": "adopted",
        "content_contract": {
            "version": "2026-07-15.v1",
            "intent": "planting",
            "content_gate": {"pass": True},
        },
    }
    script.update(updates)
    return script


def _ready_arm_row(**updates: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "arm_id": ARM_ID,
        "script_id": SCRIPT_ID,
        "arm_sku_id": "SKU-READY-1",
        "production_mode": "ai_video",
        "experiment_id": EXPERIMENT_ID,
        "experiment_sku_id": "SKU-READY-1",
        "experiment_intent": "planting",
        "experiment_track": "ai_video",
    }
    row.update(updates)
    return row


class _FakePool:
    def __init__(self, row: Mapping[str, Any] | None):
        self.row = row
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, sql: str, *args: Any) -> Mapping[str, Any] | None:
        self.fetchrow_calls.append((sql, args))
        return self.row


class _Record(Mapping[str, Any]):
    """Minimal asyncpg.Record-like mapping used to prevent dict-only code."""

    def __init__(self, values: Mapping[str, Any]):
        self._values = dict(values)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("script", "field"),
    [
        (None, "content_contract"),
        ({"content_contract": []}, "content_contract"),
        (
            _ready_script(
                status="draft",
                content_contract={
                    "version": "old",
                    "intent": "planting",
                    "content_gate": {"pass": True},
                },
            ),
            "contract_version",
        ),
        (
            _ready_script(
                status="draft",
                content_contract={
                    "version": "2026-07-15.v1",
                    "intent": "planting",
                    "content_gate": {"pass": False},
                },
            ),
            "content_gate",
        ),
    ],
)
async def test_media_readiness_prioritizes_contract_gate_before_status_and_arm(
    monkeypatch, script, field
):
    pool = _FakePool(_ready_arm_row())
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)

    result = await assert_script_ready_for_media(script, "not-a-uuid")

    assert result == {
        "ok": False,
        "error": "planting_content_gate_failed",
        "field": field,
    }
    assert pool.fetchrow_calls == []


@pytest.mark.asyncio
async def test_media_readiness_rejects_draft_before_malformed_arm(monkeypatch):
    pool = _FakePool(_ready_arm_row())
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)

    result = await assert_script_ready_for_media(
        _ready_script(status="draft"), "not-a-uuid"
    )

    assert result == {"ok": False, "error": "script_not_adopted"}
    assert pool.fetchrow_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("arm_id", [None, "", "not-a-uuid"])
async def test_media_readiness_rejects_malformed_arm_without_fetch(
    monkeypatch, arm_id
):
    pool = _FakePool(_ready_arm_row())
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)

    result = await assert_script_ready_for_media(_ready_script(), arm_id)

    assert result == {
        "ok": False,
        "error": "experiment_arm_missing_or_mismatch",
        "field": "experiment_arm_id",
    }
    assert pool.fetchrow_calls == []


@pytest.mark.asyncio
async def test_media_readiness_rejects_missing_joined_arm(monkeypatch):
    pool = _FakePool(None)
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)

    result = await assert_script_ready_for_media(_ready_script(), ARM_ID)

    assert result == {
        "ok": False,
        "error": "experiment_arm_missing_or_mismatch",
        "field": "experiment_arm_id",
    }
    assert len(pool.fetchrow_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("script_updates", "row_updates", "field"),
    [
        ({"id": "33333333-3333-4333-8333-333333333333"}, {}, "script_id"),
        ({"sku_id": "SKU-OTHER"}, {}, "sku_id"),
        ({}, {"experiment_sku_id": "SKU-OTHER"}, "sku_id"),
        ({"intent": "soft_ad"}, {}, "intent"),
        (
            {
                "content_contract": {
                    "version": "2026-07-15.v1",
                    "intent": "soft_ad",
                    "content_gate": {"pass": True},
                }
            },
            {},
            "intent",
        ),
        ({}, {"experiment_intent": "soft_ad"}, "intent"),
        ({}, {"production_mode": "human_brief"}, "track"),
    ],
)
async def test_media_readiness_reports_first_lineage_mismatch(
    monkeypatch, script_updates, row_updates, field
):
    pool = _FakePool(_ready_arm_row(**row_updates))
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)

    result = await assert_script_ready_for_media(
        _ready_script(**script_updates), ARM_ID
    )

    assert result == {
        "ok": False,
        "error": "experiment_arm_missing_or_mismatch",
        "field": field,
    }
    assert len(pool.fetchrow_calls) == 1


@pytest.mark.asyncio
async def test_media_readiness_uses_arm_mode_over_mixed_experiment_track(monkeypatch):
    pool = _FakePool(
        _ready_arm_row(production_mode="ai_video", experiment_track="mixed")
    )
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)

    result = await assert_script_ready_for_media(_ready_script(), ARM_ID)

    assert result == {
        "ok": True,
        "script_id": SCRIPT_ID,
        "experiment_arm_id": ARM_ID,
        "experiment_id": EXPERIMENT_ID,
        "sku_id": "SKU-READY-1",
        "intent": "planting",
        "track": "ai_video",
        "contract_version": "2026-07-15.v1",
    }


@pytest.mark.asyncio
async def test_media_readiness_rejects_human_brief_effective_track(monkeypatch):
    pool = _FakePool(
        _ready_arm_row(production_mode="", experiment_track="human_brief")
    )
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)

    result = await assert_script_ready_for_media(_ready_script(), ARM_ID)

    assert result == {
        "ok": False,
        "error": "experiment_arm_missing_or_mismatch",
        "field": "track",
    }


@pytest.mark.asyncio
async def test_media_readiness_canonicalizes_uuids_and_accepts_record_mapping(
    monkeypatch,
):
    row = _ready_arm_row(
        arm_id=UUID(ARM_ID),
        script_id=UUID(SCRIPT_ID),
        experiment_id=UUID(EXPERIMENT_ID),
    )
    pool = _FakePool(_Record(row))
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)
    script = _ready_script(id=SCRIPT_ID.upper())

    result = await assert_script_ready_for_media(script, ARM_ID.upper())

    assert result["ok"] is True
    assert result["script_id"] == SCRIPT_ID
    assert result["experiment_arm_id"] == ARM_ID
    assert result["experiment_id"] == EXPERIMENT_ID


@pytest.mark.asyncio
async def test_media_readiness_performs_one_explicit_join_without_latest_lookup(
    monkeypatch,
):
    pool = _FakePool(_ready_arm_row())
    monkeypatch.setattr(video_content_gate, "get_pool", lambda: pool)

    result = await assert_script_ready_for_media(_ready_script(), ARM_ID.upper())

    assert result["ok"] is True
    assert len(pool.fetchrow_calls) == 1
    sql, args = pool.fetchrow_calls[0]
    normalized_sql = " ".join(sql.lower().split())
    assert "pipeline.experiment_arms" in normalized_sql
    assert "pipeline.experiments" in normalized_sql
    assert " join " in normalized_sql
    assert "order by" not in normalized_sql
    assert "limit" not in normalized_sql
    assert args == (ARM_ID,)


class _ContractPersistencePool:
    def __init__(
        self,
        *,
        fetchrow_results: list[Mapping[str, Any] | None] | None = None,
        fetch_results: list[Mapping[str, Any]] | None = None,
    ):
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_results = list(fetch_results or [])
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, sql: str, *args: Any) -> Mapping[str, Any] | None:
        self.fetchrow_calls.append((sql, args))
        return self.fetchrow_results.pop(0) if self.fetchrow_results else None

    async def fetch(self, sql: str, *args: Any) -> list[Mapping[str, Any]]:
        self.fetch_calls.append((sql, args))
        return list(self.fetch_results)


def _creative_pack_kwargs(**updates: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "sku_id": "SKU-CONTRACT-1",
        "kind": "video_planting",
        "script_md": "一段可执行的种草脚本",
        "portrait_id": "33333333-3333-4333-8333-333333333333",
        "intent": "planting",
        "notes": "gate=passed",
    }
    kwargs.update(updates)
    return kwargs


@pytest.mark.asyncio
async def test_save_creative_pack_persists_content_contract_as_explicit_jsonb(
    monkeypatch,
):
    pool = _ContractPersistencePool(
        fetchrow_results=[{"v": None}, {"id": SCRIPT_ID}]
    )
    monkeypatch.setattr(pipeline_lineage, "get_pool", lambda: pool)
    contract = {"version": "2026-07-15.v1", "标题": "锅气", "gate": {"pass": True}}

    result = await pipeline_lineage.save_creative_pack(
        **_creative_pack_kwargs(content_contract=contract)
    )

    assert result == SCRIPT_ID
    assert len(pool.fetchrow_calls) == 2
    insert_sql, insert_args = pool.fetchrow_calls[-1]
    normalized_sql = " ".join(insert_sql.split())
    assert "INSERT INTO pipeline.scripts" in normalized_sql
    assert "status, version, parent_script_id, portrait_id, intent, notes, content_contract" in normalized_sql
    assert "'draft', $16, $17::uuid, $18::uuid, $19, $20, $21::jsonb" in normalized_sql
    assert len(insert_args) == 21
    assert insert_args[-2] == "gate=passed"
    assert insert_args[-1] == '{"version": "2026-07-15.v1", "标题": "锅气", "gate": {"pass": true}}'


@pytest.mark.asyncio
async def test_save_creative_pack_defaults_content_contract_to_empty_object(monkeypatch):
    pool = _ContractPersistencePool(
        fetchrow_results=[{"v": None}, {"id": SCRIPT_ID}]
    )
    monkeypatch.setattr(pipeline_lineage, "get_pool", lambda: pool)

    result = await pipeline_lineage.save_creative_pack(**_creative_pack_kwargs())

    assert result == SCRIPT_ID
    assert pool.fetchrow_calls[-1][1][-1] == "{}"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_contract", [[], "{}", 1, object()])
async def test_save_creative_pack_rejects_nonmapping_contract_before_pool_access(
    monkeypatch, invalid_contract
):
    def _unexpected_pool_access():
        raise AssertionError("invalid content_contract must not access the database pool")

    monkeypatch.setattr(pipeline_lineage, "get_pool", _unexpected_pool_access)

    result = await pipeline_lineage.save_creative_pack(
        **_creative_pack_kwargs(content_contract=invalid_contract)
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored_contract",
    [
        _Record({"version": "record-v1", "gate": {"pass": True}}),
        '{"version":"string-v1","gate":{"pass":true}}',
    ],
)
async def test_get_creative_pack_decodes_mapping_and_json_string_contracts(
    monkeypatch, stored_contract
):
    row = _Record(
        {
            "id": SCRIPT_ID,
            "hooks": "[]",
            "scenes": "[]",
            "character_sheets": "[]",
            "content_contract": stored_contract,
            "notes": "gate=passed",
            "status": "draft",
        }
    )
    pool = _ContractPersistencePool(fetchrow_results=[row])
    monkeypatch.setattr(pipeline_lineage, "get_pool", lambda: pool)

    result = await pipeline_lineage.get_creative_pack(SCRIPT_ID)

    assert result is not None
    assert isinstance(result["content_contract"], dict)
    assert result["content_contract"]["gate"] == {"pass": True}
    select_sql, select_args = pool.fetchrow_calls[0]
    assert "content_contract" in select_sql
    assert "notes" in select_sql
    assert select_args == (SCRIPT_ID,)


@pytest.mark.asyncio
async def test_list_creative_packs_decodes_contract_dict_string_and_null(monkeypatch):
    rows = [
        {"id": "one", "content_contract": {"version": "dict-v1"}},
        {"id": "two", "content_contract": '{"version":"string-v1"}'},
        {"id": "three", "content_contract": None},
    ]
    pool = _ContractPersistencePool(fetch_results=rows)
    monkeypatch.setattr(pipeline_lineage, "get_pool", lambda: pool)

    result = await pipeline_lineage.list_creative_packs(
        sku_id="SKU-CONTRACT-1", kind="video_planting"
    )

    assert [item["content_contract"] for item in result] == [
        {"version": "dict-v1"},
        {"version": "string-v1"},
        {},
    ]
    select_sql, select_args = pool.fetch_calls[0]
    assert "content_contract" in select_sql
    assert "status" in select_sql
    assert select_args == ("SKU-CONTRACT-1", "video_planting", 30)
