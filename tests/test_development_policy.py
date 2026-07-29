from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omni_development_policy_tests", ROOT / "scripts" / "development_policy.py"
)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


def test_risk_policy_selects_proportional_contracts_without_review_gate() -> None:
    assert policy.classify_change(["docs/guide.md"], read_only=True).level == "R0"
    assert policy.classify_change(["docs/guide.md"]).level == "R1"
    r1 = policy.classify_change(["services/example/worker.py"])
    assert (r1.level, r1.contract_profile, r1.approval_required) == ("R1", "light", False)
    r2 = policy.classify_change(["services/example/worker.py", "frontend/src/page.tsx"])
    assert (r2.level, r2.contract_profile, r2.approval_required) == ("R2", "full", False)


def test_breaking_source_contract_is_r2_until_an_r3_effect_is_requested() -> None:
    impact = {"compatibility": {"api": {"status": "breaking"}}}
    source_only = policy.classify_change(["services/example/app.py"], impact=impact)
    assert source_only.level == "R2"
    assert source_only.approval_required is False

    external = policy.classify_change(
        ["services/example/app.py"], effect_kinds=["external_publish"]
    )
    assert external.level == "R3"
    assert external.contract_profile == "full_with_approval"
    assert external.approval_required is True


def test_same_risk_delta_is_auto_amended_but_escalation_blocks() -> None:
    same = policy.classify_scope_delta(
        "R1", ["services/example/app.py"], ["services/example/app.py", "services/example/tester.py"]
    )
    assert same.action == "auto_amend_contract"
    assert same.blocked is False

    escalated = policy.classify_scope_delta(
        "R1", ["services/example/app.py"], ["services/example/app.py", "migrations/099_add.sql"]
    )
    assert escalated.action == "block_risk_escalation"
    assert escalated.required_level == "R2"

    covered = policy.classify_scope_delta(
        "R1", ["services/**"], ["services/a.py", "services/nested/b.py"]
    )
    assert covered.action == "continue"
    assert covered.added_paths == ()


def test_docs_migration_name_is_not_a_database_boundary_and_effects_raise_r3() -> None:
    assert policy.classify_change(["docs/migrations-guide.md"]).level == "R1"
    impact = {
        "risk": {
            "external_effects": [
                {"kind": "external_publish", "target": "fixture", "operation": "publish"}
            ]
        }
    }
    assert policy.classify_change(["services/a.py"], impact=impact).level == "R3"


@pytest.mark.parametrize(
    "value",
    ["C:relative.txt", "C:/absolute.txt", "//server/share.txt", "dir/file:stream", "dir/CON.txt", "dir/name. ", "../escape"],
)
def test_windows_unsafe_paths_are_rejected(value: str) -> None:
    with pytest.raises(policy.PolicyInputError):
        policy.normalize_path(value)


def test_windows_collision_key_is_case_insensitive() -> None:
    assert policy.path_collision_key("Services/App.py") == policy.path_collision_key("services/app.py")


@pytest.mark.parametrize("value", ["a//b.py", "a/b/", "a/./b.py"])
def test_ambiguous_repository_paths_are_rejected(value: str) -> None:
    with pytest.raises(policy.PolicyInputError):
        policy.normalize_path(value)


@pytest.mark.parametrize(
    "path",
    [
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "services/example/Dockerfile",
        "dev-start.ps1",
        "services/infra-core/docker-compose.infra.yml",
        "config/runtime-manifest.yaml",
        "scripts/runtime_allocation.py",
    ],
)
def test_runtime_and_infrastructure_paths_have_an_explicit_r2_floor(path: str) -> None:
    decision = policy.classify_change([path])
    assert decision.level == "R2"
    assert "infrastructure" in decision.boundaries


def test_debt_ratchet_reports_history_but_blocks_only_new_changed_path_debt() -> None:
    baseline = [
        {"path": "legacy.py", "rule": "lint", "message": "old"},
        {"path": "changed.py", "rule": "lint", "message": "old"},
    ]
    current = [
        *baseline,
        {"path": "legacy.py", "rule": "lint", "message": "new elsewhere"},
    ]
    passed = policy.evaluate_debt_ratchet(baseline, current, changed_paths=["changed.py"])
    assert passed.passed is True
    assert len(passed.historical_violations) == 2

    current.append({"path": "changed.py", "rule": "lint", "message": "new here"})
    blocked = policy.evaluate_debt_ratchet(baseline, current, changed_paths=["changed.py"])
    assert blocked.passed is False
    assert blocked.new_violations == ("changed.py|lint|new here",)
