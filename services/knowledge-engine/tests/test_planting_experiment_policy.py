"""Formal planting experiment policy and same-round arm lineage tests.

These tests use small fake pools so validation order can be asserted without
creating database side effects.
"""
from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from app.services import experiment_lab as lab


class _NoAcquire:
    def __call__(self):
        raise AssertionError("validation failure must happen before a transaction")


class _CreatePool:
    def __init__(self) -> None:
        self.insert_sql = ""
        self.insert_args: tuple[Any, ...] = ()

    async def fetchrow(self, query: str, *args: Any):
        assert "INSERT INTO pipeline.experiments" in query
        self.insert_sql = query
        self.insert_args = args
        return {
            "id": "11111111-1111-4111-8111-111111111111",
            "sku_id": args[0],
            "intent": args[5],
            "track": args[9],
            "north_star_metric": args[6],
            "north_star_direction": args[7],
            "status": "running",
            "evaluation_policy": args[10],
            "created_at": None,
        }


@pytest.mark.asyncio
async def test_planting_experiment_snapshots_a3_policy(monkeypatch):
    pool = _CreatePool()
    monkeypatch.setattr(lab, "get_pool", lambda: pool)

    result = await lab.create_experiment(
        sku_id="SKU-PLANTING",
        intent="planting",
        audience_record_id="22222222-2222-4222-8222-222222222222",
        track="ai_video",
    )

    assert result["ok"] is True
    assert result["experiment"]["north_star_metric"] == "a3_ratio"
    policy = result["experiment"]["evaluation_policy"]
    assert policy["profile_version"] == "2026-07-15.v1"
    assert policy["intent"] == "planting"
    assert policy["north_star"] == "a3_ratio"
    assert set(policy["diagnostic_metrics"]) == {
        "cpm",
        "completion_rate",
        "play_3s_rate",
    }
    assert policy["max_exposure_ratio"] == 3.0
    assert policy["rate_scale"] == "0-1"
    assert policy["currency"] == "CNY"
    assert "evaluation_policy" in pool.insert_sql
    assert json.loads(pool.insert_args[10])["profile_version"] == "2026-07-15.v1"


@pytest.mark.asyncio
async def test_soft_ad_keeps_completion_rate_policy(monkeypatch):
    pool = _CreatePool()
    monkeypatch.setattr(lab, "get_pool", lambda: pool)

    result = await lab.create_experiment(
        sku_id="SKU-SOFT",
        intent="soft_ad",
        audience_record_id="22222222-2222-4222-8222-222222222222",
        track="ai_video",
    )

    assert result["ok"] is True
    assert result["experiment"]["north_star_metric"] == "completion_rate"
    assert result["experiment"]["evaluation_policy"]["north_star"] == "completion_rate"


@pytest.mark.asyncio
async def test_explicit_business_thresholds_are_validated_and_snapshotted(monkeypatch):
    pool = _CreatePool()
    monkeypatch.setattr(lab, "get_pool", lambda: pool)
    overrides = {
        "play_3s_floor": 0.35,
        "completion_floor": 0.18,
        "a3_floor": 0.02,
        "cpm_ceiling": 80.0,
        "min_impressions": 1000,
        "min_a3_eligible_users": 200,
    }

    result = await lab.create_experiment(
        sku_id="SKU-PLANTING",
        intent="planting",
        audience_record_id="22222222-2222-4222-8222-222222222222",
        track="ai_video",
        evaluation_policy_overrides=overrides,
    )

    assert result["ok"] is True
    policy = result["experiment"]["evaluation_policy"]
    assert {key: policy[key] for key in overrides} == overrides
    assert policy["max_exposure_ratio"] == 3.0
    assert policy["profile_version"] == "2026-07-15.v1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"play_3s_floor": -0.01}, "play_3s_floor"),
        ({"completion_floor": 1.01}, "completion_floor"),
        ({"a3_floor": True}, "a3_floor"),
        ({"cpm_ceiling": -1}, "cpm_ceiling"),
        ({"min_impressions": -1}, "min_impressions"),
        ({"min_a3_eligible_users": -1}, "min_a3_eligible_users"),
        ({"currency": "USD"}, "currency"),
        ({"profile_version": "fake"}, "profile_version"),
        ({"max_exposure_ratio": 9}, "max_exposure_ratio"),
    ],
)
async def test_policy_override_rejects_invalid_or_immutable_fields(
    monkeypatch, overrides, field
):
    monkeypatch.setattr(
        lab,
        "get_pool",
        lambda: (_ for _ in ()).throw(
            AssertionError("invalid policy must fail before pool access")
        ),
    )

    result = await lab.create_experiment(
        sku_id="SKU-PLANTING",
        intent="planting",
        audience_record_id="22222222-2222-4222-8222-222222222222",
        track="ai_video",
        evaluation_policy_overrides=overrides,
    )

    assert result == {
        "ok": False,
        "error": "invalid_evaluation_policy_overrides",
        "field": field,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["planting", "soft_ad"])
@pytest.mark.parametrize(
    "profile_error",
    [
        "video_intent_profile_not_found:test",
        "video_intent_profiles_invalid:load_failed",
    ],
)
async def test_formal_profile_failure_blocks_experiment_creation(
    monkeypatch, intent, profile_error
):
    def fail_profile_loader(_intent: str):
        raise ValueError(profile_error)

    monkeypatch.setattr(lab, "get_video_intent_profile", fail_profile_loader)
    monkeypatch.setattr(
        lab,
        "get_pool",
        lambda: (_ for _ in ()).throw(
            AssertionError("formal profile failure must stop before pool access")
        ),
    )

    result = await lab.create_experiment(
        sku_id="SKU-POLICY-FAIL",
        intent=intent,
        audience_record_id="22222222-2222-4222-8222-222222222222",
        track="ai_video",
    )

    assert result == {
        "ok": False,
        "error": "evaluation_policy_unavailable",
        "intent": intent,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["harvest", "hard_ad"])
async def test_unconfigured_legacy_profile_keeps_empty_policy(monkeypatch, intent):
    pool = _CreatePool()

    def missing_legacy_profile(requested_intent: str):
        raise ValueError(f"video_intent_profile_not_found:{requested_intent}")

    monkeypatch.setattr(lab, "get_video_intent_profile", missing_legacy_profile)
    monkeypatch.setattr(lab, "get_pool", lambda: pool)

    result = await lab.create_experiment(
        sku_id="SKU-LEGACY",
        intent=intent,
        audience_record_id="22222222-2222-4222-8222-222222222222",
        track="ai_video",
    )

    assert result["ok"] is True
    assert result["experiment"]["evaluation_policy"] == {}


@pytest.mark.asyncio
async def test_formal_planting_rejects_non_a3_custom_north_star_before_pool(monkeypatch):
    monkeypatch.setattr(
        lab,
        "get_pool",
        lambda: (_ for _ in ()).throw(AssertionError("must fail before pool access")),
    )
    result = await lab.create_experiment(
        sku_id="SKU-PLANTING",
        intent="planting",
        audience_record_id="22222222-2222-4222-8222-222222222222",
        track="ai_video",
        north_star_metric="completion_rate",
    )
    assert result["ok"] is False
    assert result["error"] == "bad_north_star_metric"
    assert result["field"] == "north_star_metric"


class _LineagePool:
    def __init__(self, *, exp: dict[str, Any], script: dict[str, Any], open_round=None):
        self.exp = exp
        self.script = script
        self.open_round = open_round
        self.acquire = _NoAcquire()

    async def fetchrow(self, query: str, *args: Any):
        if "FROM pipeline.experiments e" in query and "pipeline.scripts s" in query:
            return {**self.exp, **self.script}
        if "pipeline.experiment_rounds" in query:
            return self.open_round
        raise AssertionError(f"unexpected query: {query}")


def _formal_exp(**updates: Any) -> dict[str, Any]:
    value = {
        "id": "11111111-1111-4111-8111-111111111111",
        "experiment_sku_id": "SKU-P",
        "experiment_intent": "planting",
        "experiment_track": "ai_video",
        "north_star_metric": "a3_ratio",
        "experiment_status": "running",
    }
    value.update(updates)
    return value


def _formal_script(**updates: Any) -> dict[str, Any]:
    value = {
        "script_id": "33333333-3333-4333-8333-333333333333",
        "script_sku_id": "SKU-P",
        "script_kind": "video_planting",
        "script_intent": "planting",
        "script_status": "draft",
    }
    value.update(updates)
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exp_updates", "script_updates", "field"),
    [
        ({}, {"script_sku_id": "SKU-OTHER"}, "sku_id"),
        ({}, {"script_intent": "soft_ad"}, "intent"),
        ({"experiment_intent": "soft_ad"}, {}, "intent"),
        ({}, {"script_kind": "director_brief"}, "track"),
        ({"experiment_track": "human_brief"}, {}, "track"),
    ],
)
async def test_attach_arm_rejects_formal_planting_lineage_before_transaction(
    monkeypatch, exp_updates, script_updates, field
):
    pool = _LineagePool(
        exp=_formal_exp(**exp_updates),
        script=_formal_script(**script_updates),
    )
    monkeypatch.setattr(lab, "get_pool", lambda: pool)

    result = await lab.attach_arm(
        experiment_id="11111111-1111-4111-8111-111111111111",
        script_id="33333333-3333-4333-8333-333333333333",
        variable_value="晚归催饭",
        swept_variable="pain_scene_bridge",
    )

    assert result == {
        "ok": False,
        "error": "experiment_arm_missing_or_mismatch",
        "field": field,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("round_no", "swept_variable", "field"),
    [
        (None, "pain_scene_bridge", "round_no"),
        (2, "pain_scene_bridge", "round_no"),
        (1, None, "swept_variable"),
        (1, "opening_hook_3s", "swept_variable"),
    ],
)
async def test_attach_arm_requires_explicit_matching_open_round_for_second_planting_arm(
    monkeypatch, round_no, swept_variable, field
):
    pool = _LineagePool(
        exp=_formal_exp(),
        script=_formal_script(),
        open_round={
            "id": "44444444-4444-4444-8444-444444444444",
            "round_no": 1,
            "swept_variable": "pain_scene_bridge",
            "status": "open",
            "arm_count": 1,
        },
    )
    monkeypatch.setattr(lab, "get_pool", lambda: pool)
    result = await lab.attach_arm(
        experiment_id="11111111-1111-4111-8111-111111111111",
        script_id="33333333-3333-4333-8333-333333333333",
        variable_value="反复试味",
        round_no=round_no,
        swept_variable=swept_variable,
    )
    assert result == {
        "ok": False,
        "error": "experiment_arm_missing_or_mismatch",
        "field": field,
    }


class _AdoptPool:
    def __init__(self) -> None:
        self.experiment_query_args: list[tuple[Any, ...]] = []
        self.script = {
            "sku_id": "SKU-P",
            "kind": "video_planting",
            "intent": "planting",
            "status": "draft",
            "portrait_id": "55555555-5555-4555-8555-555555555555",
            "audience_record_id": "66666666-6666-4666-8666-666666666666",
        }

    async def fetchrow(self, query: str, *args: Any):
        if "FROM pipeline.scripts" in query:
            return self.script
        if "FROM pipeline.experiments" in query:
            self.experiment_query_args.append(args)
            return {
                "id": "11111111-1111-4111-8111-111111111111",
                "sku_id": "SKU-P",
                "intent": "planting",
                "track": "ai_video",
                "north_star_metric": "a3_ratio",
            }
        if "FROM pipeline.experiment_rounds" in query:
            return {
                "id": "44444444-4444-4444-8444-444444444444",
                "round_no": 1,
                "swept_variable": "pain_scene_bridge",
                "status": "open",
                "arm_count": 1,
            }
        raise AssertionError(f"unexpected query: {query}")

    async def fetchval(self, query: str, *args: Any):
        return 1


@pytest.mark.asyncio
async def test_second_planting_candidate_requires_explicit_experiment_and_round(
    monkeypatch,
):
    pool = _AdoptPool()
    monkeypatch.setattr(lab, "get_pool", lambda: pool)
    calls = []

    async def fake_attach(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "arm": {"round_no": 1}}

    monkeypatch.setattr(lab, "attach_arm", fake_attach)
    result = await lab.adopt_script_as_arm(
        script_id="33333333-3333-4333-8333-333333333333",
        variable_value="反复试味",
        swept_variable="pain_scene_bridge",
    )
    assert result["ok"] is False
    assert result["error"] == "planting_second_arm_requires_explicit_round"
    assert calls == []
    assert pool.script["status"] == "draft"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_experiment_id", ["", "not-a-uuid"])
async def test_explicit_planting_experiment_id_must_be_nonempty_uuid(
    monkeypatch, bad_experiment_id
):
    monkeypatch.setattr(
        lab,
        "get_pool",
        lambda: (_ for _ in ()).throw(
            AssertionError("invalid explicit experiment id must fail before DB lookup")
        ),
    )

    result = await lab.adopt_script_as_arm(
        script_id="33333333-3333-4333-8333-333333333333",
        variable_value="反复试味",
        swept_variable="pain_scene_bridge",
        experiment_id=bad_experiment_id,
        round_no=1,
    )

    assert result == {
        "ok": False,
        "error": "experiment_arm_missing_or_mismatch",
        "field": "experiment_id",
    }


@pytest.mark.asyncio
async def test_explicit_second_planting_candidate_reuses_same_round(monkeypatch):
    pool = _AdoptPool()
    monkeypatch.setattr(lab, "get_pool", lambda: pool)

    async def fake_attach(**kwargs):
        return {
            "ok": True,
            "arm": {
                "arm_id": "77777777-7777-4777-8777-777777777777",
                "arm_label": "B",
                "round_no": kwargs["round_no"],
                "swept_variable": kwargs["swept_variable"],
                "swept_variable_label": "痛点场景桥",
                "variable_value": kwargs["variable_value"],
                "script_id": kwargs["script_id"],
                "arm_code": "R1B",
            },
            "script_adopted": True,
            "warnings": [],
        }

    monkeypatch.setattr(lab, "attach_arm", fake_attach)
    result = await lab.adopt_script_as_arm(
        script_id="33333333-3333-4333-8333-333333333333",
        variable_value="反复试味",
        swept_variable="pain_scene_bridge",
        experiment_id="11111111-1111-4111-8111-111111111111",
        round_no=1,
    )
    assert result["ok"] is True
    assert result["experiment_id"] == "11111111-1111-4111-8111-111111111111"
    assert result["round_no"] == 1
    assert result["arm"]["round_no"] == 1
    assert pool.experiment_query_args == [
        ("11111111-1111-4111-8111-111111111111",)
    ]


def test_mcp_experiment_create_exposes_policy_overrides():
    from app.mcp.tools.experiment import experiment_create

    assert "evaluation_policy_overrides" in inspect.signature(experiment_create).parameters


def test_planting_variable_vocabulary_is_registered():
    assert {
        "pain_scene_bridge",
        "presentation_motif",
        "justification_density",
        "justification_module",
    }.issubset(lab.SWEEP_VARIABLE_LABELS)
