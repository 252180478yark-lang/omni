#!/usr/bin/env python3
"""Create, transition, and validate Omni feature-development contracts."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment failure path
    raise SystemExit("PyYAML is required: install package 'pyyaml'.") from exc


STATES = (
    "DISCOVERED",
    "IMPACT_LOCKED",
    "IMPLEMENTING",
    "VERIFYING",
    "GRAPH_DIFF_READY",
    "COMPLETE",
)
NEXT_STATE = {state: STATES[index + 1] for index, state in enumerate(STATES[:-1])}
SCOPE_KEYS = (
    "pages",
    "apis",
    "mcp_tools",
    "services",
    "database",
    "data_sources",
    "states_workflows",
    "tests",
    "docs",
)
ACTIONS = {"reuse", "modify", "add", "remove"}
CONTRACT_CHANGES = {"none", "compatible", "breaking"}
FINAL_GRAPH_STATUSES = {"clean", "accepted"}
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}
RISK_LEVELS = ("R0", "R1", "R2", "R3")
EXTERNAL_EFFECT_KINDS = {
    "external_publish",
    "external_message",
    "paid_generation",
    "credential_access",
    "shared_database_migration",
    "production_database_migration",
    "hard_delete_user_data",
    "physical_client_retirement",
}
CONTRACT_PROFILES = {
    "R0": "none",
    "R1": "light",
    "R2": "full",
    "R3": "full_with_approval",
}
DELIVERY_AUTHORITY = "ci_attestation"
DELIVERY_READY_STATUS = "ready_for_ci"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_yaml_text(text: str, label: str) -> dict[str, Any]:
    """Parse one contract mapping from text supplied by a named evaluation source."""

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"top-level YAML value must be a mapping: {label}")
    return data


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"file does not exist: {path}")
    return read_yaml_text(path.read_text(encoding="utf-8"), str(path))


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_list(value: Any) -> bool:
    return isinstance(value, list)


def state_at_least(state: str, threshold: str) -> bool:
    return state in STATES and STATES.index(state) >= STATES.index(threshold)


def require_text(errors: list[str], value: Any, field: str) -> None:
    if not is_text(value):
        errors.append(f"{field} must be non-empty text")


def require_list(errors: list[str], value: Any, field: str) -> None:
    if not is_list(value):
        errors.append(f"{field} must be a list")


def validate_feature_identity(
    errors: list[str],
    impact: dict[str, Any],
    *,
    required: bool,
) -> None:
    """Validate the v2 feature and baseline identity without parsing future graph data."""

    refs = impact.get("feature_refs")
    if refs is None and not required:
        return
    if not is_list(refs):
        errors.append("impact.feature_refs must be a list")
    elif required and not refs:
        errors.append("impact.feature_refs must contain at least one feature reference")
    elif refs:
        feature_ids: set[str] = set()
        for index, item in enumerate(refs):
            prefix = f"impact.feature_refs[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            feature_id = item.get("feature_id")
            require_text(errors, feature_id, f"{prefix}.feature_id")
            require_text(errors, item.get("feature_ref"), f"{prefix}.feature_ref")
            if is_text(feature_id):
                if feature_id in feature_ids:
                    errors.append(f"duplicate feature_id: {feature_id}")
                feature_ids.add(feature_id)

    before_snapshot = impact.get("before_snapshot")
    if before_snapshot is None and not required:
        return
    if not isinstance(before_snapshot, dict):
        errors.append("impact.before_snapshot must be a mapping")
    elif required:
        require_text(errors, before_snapshot.get("ref"), "impact.before_snapshot.ref")


def validate_risk_contract(
    errors: list[str],
    impact: dict[str, Any],
    *,
    required: bool,
) -> None:
    """Validate the machine-readable v3 risk declaration."""

    risk = impact.get("risk")
    if risk is None and not required:
        return
    if not isinstance(risk, dict):
        errors.append("impact.risk must be a mapping")
        return

    level = risk.get("level")
    if level not in RISK_LEVELS:
        errors.append(f"impact.risk.level must be one of: {', '.join(RISK_LEVELS)}")
    for field in ("reasons", "external_effects"):
        require_list(errors, risk.get(field), f"impact.risk.{field}")
    external_effects = risk.get("external_effects")
    if isinstance(external_effects, list):
        for index, effect in enumerate(external_effects):
            prefix = f"impact.risk.external_effects[{index}]"
            if not isinstance(effect, dict):
                errors.append(f"{prefix} must be a structured mapping")
                continue
            if effect.get("kind") not in EXTERNAL_EFFECT_KINDS:
                errors.append(
                    f"{prefix}.kind must be one of: {', '.join(sorted(EXTERNAL_EFFECT_KINDS))}"
                )
            require_text(errors, effect.get("target"), f"{prefix}.target")
            require_text(errors, effect.get("operation"), f"{prefix}.operation")
    contract_profile = risk.get("contract_profile")
    if contract_profile is not None:
        expected_profile = CONTRACT_PROFILES.get(str(level))
        if contract_profile != expected_profile:
            errors.append(
                "impact.risk.contract_profile must match the declared risk level "
                f"({level} -> {expected_profile})"
            )
    scope_deltas = risk.get("scope_deltas")
    if scope_deltas is not None:
        if not isinstance(scope_deltas, list):
            errors.append("impact.risk.scope_deltas must be a list")
        else:
            for index, delta in enumerate(scope_deltas):
                prefix = f"impact.risk.scope_deltas[{index}]"
                if not isinstance(delta, dict):
                    errors.append(f"{prefix} must be a mapping")
                    continue
                require_list(errors, delta.get("added_paths"), f"{prefix}.added_paths")
                require_text(errors, delta.get("reason"), f"{prefix}.reason")
                if delta.get("required_level") not in RISK_LEVELS:
                    errors.append(f"{prefix}.required_level must be one of: {', '.join(RISK_LEVELS)}")
                elif level in RISK_LEVELS and RISK_LEVELS.index(delta["required_level"]) > RISK_LEVELS.index(level):
                    errors.append(f"{prefix}.required_level must not exceed impact.risk.level")
    approval = risk.get("approval")
    if not isinstance(approval, dict):
        errors.append("impact.risk.approval must be a mapping")
    else:
        if approval.get("required") not in (True, False):
            errors.append("impact.risk.approval.required must be boolean")
        gate_ref = approval.get("gate_ref")
        if gate_ref is not None and not isinstance(gate_ref, str):
            errors.append("impact.risk.approval.gate_ref must be text")
    if required and level != "R0" and not risk.get("reasons"):
        errors.append("impact.risk.reasons must explain every non-R0 change")
    if required and level == "R3" and not risk.get("external_effects"):
        errors.append("impact.risk.external_effects must describe the R3 external effect")
    if required and level == "R3" and isinstance(approval, dict):
        if approval.get("required") is not True:
            errors.append("impact.risk.approval.required must be true for R3")
        require_text(errors, approval.get("gate_ref"), "impact.risk.approval.gate_ref")
    if required and level in {"R0", "R1", "R2"} and risk.get("external_effects"):
        errors.append("impact.risk.level must be R3 when external_effects are declared")


def validate_delivery_intent(
    errors: list[str],
    impact: dict[str, Any],
    *,
    required: bool,
) -> None:
    """Validate v3 delivery intent without claiming the delivered commit locally."""

    delivery = impact.get("delivery")
    if delivery is None and not required:
        return
    if not isinstance(delivery, dict):
        errors.append("impact.delivery must be a mapping")
        return
    if delivery.get("authority") != DELIVERY_AUTHORITY:
        errors.append(f"impact.delivery.authority must equal {DELIVERY_AUTHORITY}")
    base_commit = delivery.get("base_commit")
    if required and (
        not isinstance(base_commit, str)
        or re.fullmatch(r"[0-9a-fA-F]{40}", base_commit.strip()) is None
    ):
        errors.append("impact.delivery.base_commit must be a full 40-character Git commit SHA")


def normalized_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


@lru_cache(maxsize=1)
def _development_policy() -> Any:
    path = Path(__file__).resolve().parents[4] / "scripts" / "development_policy.py"
    spec = importlib.util.spec_from_file_location("omni_development_policy_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shared development policy: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def glob_pattern_to_regex(pattern: str) -> str:
    """Translate contract globs with segment-safe * and recursive ** semantics."""
    return str(_development_policy().glob_pattern_to_regex(pattern))


def path_matches(path: str, pattern: str) -> bool:
    return bool(_development_policy().path_matches(path, pattern))


def validate_contract_pattern(pattern: Any, field: str) -> list[str]:
    errors: list[str] = []
    if not is_text(pattern):
        return [f"{field} must be non-empty text"]
    normalized = normalized_path(pattern)
    first_segment = normalized.split("/", 1)[0]
    if normalized in {"**", "**/*"}:
        errors.append(f"{field} cannot cover the entire repository")
    if re.search(r"[*?\[]", first_segment):
        errors.append(f"{field} must start with a literal repository path segment")
    return errors


def validate_impact(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema_version = data.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("impact.schema_version must equal 1, 2, or 3")
    require_text(errors, data.get("change_id"), "impact.change_id")
    change_id = data.get("change_id")
    if is_text(change_id) and not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", change_id):
        errors.append("impact.change_id must use 3-64 lowercase letters, digits, or hyphens")
    require_text(errors, data.get("title"), "impact.title")
    state = data.get("state")
    if state not in STATES:
        errors.append(f"impact.state must be one of: {', '.join(STATES)}")
        return errors
    if schema_version == 3 and state == "COMPLETE":
        errors.append(
            "schema_version 3 repository contracts cannot self-declare COMPLETE; "
            "CI delivery attestation is the completion authority"
        )

    scope = data.get("scope")
    if not isinstance(scope, dict):
        errors.append("impact.scope must be a mapping")
    else:
        for key in SCOPE_KEYS:
            require_list(errors, scope.get(key), f"impact.scope.{key}")

    for field in ("planned_changes", "allowed_unplanned_paths", "risks", "out_of_scope", "verification_plan"):
        require_list(errors, data.get(field), f"impact.{field}")

    if not state_at_least(state, "IMPACT_LOCKED"):
        return errors

    if schema_version in {2, 3}:
        validate_feature_identity(errors, data, required=True)
    elif schema_version == 1:
        validate_feature_identity(
            errors,
            data,
            required=False,
        )
    if schema_version == 3:
        validate_risk_contract(errors, data, required=True)
        validate_delivery_intent(errors, data, required=True)

    intent = data.get("intent")
    if not isinstance(intent, dict):
        errors.append("impact.intent must be a mapping")
    else:
        require_text(errors, intent.get("problem"), "impact.intent.problem")
        require_text(errors, intent.get("expected_outcome"), "impact.intent.expected_outcome")

    current_chain = data.get("current_chain")
    if not isinstance(current_chain, dict):
        errors.append("impact.current_chain must be a mapping")
    else:
        evidence = current_chain.get("evidence")
        if not is_list(evidence) or not evidence:
            errors.append("impact.current_chain.evidence must contain at least one evidence item")

    if isinstance(scope, dict) and not any(scope.get(key) for key in SCOPE_KEYS):
        errors.append("impact.scope must declare at least one affected node")

    planned = data.get("planned_changes")
    verification_ids: set[str] = set()
    required_verification_ids: set[str] = set()
    verification_plan = data.get("verification_plan")
    if isinstance(verification_plan, list):
        for index, item in enumerate(verification_plan):
            prefix = f"impact.verification_plan[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            for field in ("id", "layer", "command", "proves"):
                require_text(errors, item.get(field), f"{prefix}.{field}")
            if item.get("required") not in (True, False):
                errors.append(f"{prefix}.required must be boolean")
            if is_text(item.get("id")):
                if item["id"] in verification_ids:
                    errors.append(f"duplicate verification id: {item['id']}")
                verification_ids.add(item["id"])
                if item.get("required") is True:
                    required_verification_ids.add(item["id"])
    if not verification_ids:
        errors.append("impact.verification_plan must contain at least one check")
    elif not required_verification_ids:
        errors.append("impact.verification_plan must contain at least one required check")

    for index, pattern in enumerate(data.get("allowed_unplanned_paths") or []):
        errors.extend(validate_contract_pattern(pattern, f"impact.allowed_unplanned_paths[{index}]"))

    planned_ids: set[str] = set()
    if not isinstance(planned, list) or not planned:
        errors.append("impact.planned_changes must contain at least one change")
    else:
        for index, item in enumerate(planned):
            prefix = f"impact.planned_changes[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            for field in ("id", "kind", "node_id"):
                require_text(errors, item.get(field), f"{prefix}.{field}")
            if item.get("action") not in ACTIONS:
                errors.append(f"{prefix}.action must be one of: {', '.join(sorted(ACTIONS))}")
            if item.get("contract_change") not in CONTRACT_CHANGES:
                errors.append(
                    f"{prefix}.contract_change must be one of: {', '.join(sorted(CONTRACT_CHANGES))}"
                )
            for field in ("paths", "upstream", "downstream", "verification_ids"):
                require_list(errors, item.get(field), f"{prefix}.{field}")
            if not item.get("paths"):
                errors.append(f"{prefix}.paths must contain at least one file path or glob")
            for path_index, pattern in enumerate(item.get("paths") or []):
                errors.extend(validate_contract_pattern(pattern, f"{prefix}.paths[{path_index}]"))
            if is_text(item.get("id")):
                if item["id"] in planned_ids:
                    errors.append(f"duplicate planned change id: {item['id']}")
                planned_ids.add(item["id"])
            for verification_id in item.get("verification_ids") or []:
                if verification_id not in verification_ids:
                    errors.append(f"{prefix} references unknown verification id: {verification_id}")
            if not item.get("verification_ids"):
                errors.append(f"{prefix}.verification_ids must contain at least one check")
            elif not any(
                verification_id in required_verification_ids
                for verification_id in item.get("verification_ids") or []
            ):
                errors.append(f"{prefix} must reference at least one required verification")

    compatibility = data.get("compatibility")
    if not isinstance(compatibility, dict):
        errors.append("impact.compatibility must be a mapping")
    else:
        for boundary in ("api", "database", "workflow", "data_source"):
            item = compatibility.get(boundary)
            if not isinstance(item, dict):
                errors.append(f"impact.compatibility.{boundary} must be a mapping")
                continue
            if item.get("status") not in {"not_applicable", "compatible", "breaking"}:
                errors.append(
                    f"impact.compatibility.{boundary}.status must be not_applicable, compatible, or breaking"
                )
            require_text(errors, item.get("strategy"), f"impact.compatibility.{boundary}.strategy")

    graph = data.get("graph_acceptance")
    if not isinstance(graph, dict):
        errors.append("impact.graph_acceptance must be a mapping")
    else:
        for field in ("required_edges", "allowed_unknowns", "forbidden_orphans"):
            require_list(errors, graph.get(field), f"impact.graph_acceptance.{field}")
        if not graph.get("required_edges"):
            errors.append("impact.graph_acceptance.required_edges must contain at least one edge")

    rollback = data.get("rollback")
    if not isinstance(rollback, dict):
        errors.append("impact.rollback must be a mapping")
    else:
        require_text(errors, rollback.get("strategy"), "impact.rollback.strategy")
        require_text(errors, rollback.get("data_recovery"), "impact.rollback.data_recovery")

    if not data.get("out_of_scope"):
        errors.append("impact.out_of_scope must name at least one deliberate boundary")

    lock = data.get("lock")
    if not isinstance(lock, dict):
        errors.append("impact.lock must be a mapping")
    else:
        require_text(errors, lock.get("locked_at"), "impact.lock.locked_at")
        require_text(errors, lock.get("locked_by"), "impact.lock.locked_by")
        require_text(errors, lock.get("rationale"), "impact.lock.rationale")

    return errors


def validate_completion(impact: dict[str, Any], completion: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    state = impact.get("state")
    impact_schema_version = impact.get("schema_version")
    completion_schema_version = completion.get("schema_version")
    if completion_schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("completion.schema_version must equal 1, 2, or 3")
    if (
        impact_schema_version in SUPPORTED_SCHEMA_VERSIONS
        and completion_schema_version in SUPPORTED_SCHEMA_VERSIONS
        and completion_schema_version != impact_schema_version
    ):
        errors.append("completion.schema_version must match impact.schema_version")
    if completion.get("change_id") != impact.get("change_id"):
        errors.append("completion.change_id must match impact.change_id")
    if completion.get("state") != state:
        errors.append("completion.state must match impact.state")
    for field in ("actual_changes", "contract_delta", "verification_results", "exceptions"):
        require_list(errors, completion.get(field), f"completion.{field}")

    if impact_schema_version == 3:
        delivery = completion.get("delivery")
        if not isinstance(delivery, dict):
            errors.append("completion.delivery must be a mapping")
        else:
            if "delivered_commit" in delivery:
                errors.append(
                    "completion.delivery.delivered_commit is forbidden for schema_version 3; "
                    "the CI attestation owns this fact"
                )
            if state_at_least(state, "GRAPH_DIFF_READY"):
                if delivery.get("status") != DELIVERY_READY_STATUS:
                    errors.append(
                        f"completion.delivery.status must equal {DELIVERY_READY_STATUS} "
                        "at GRAPH_DIFF_READY"
                    )
            elif delivery.get("status") not in {"pending", DELIVERY_READY_STATUS}:
                errors.append(
                    f"completion.delivery.status must be pending or {DELIVERY_READY_STATUS}"
                )
        final = completion.get("final")
        if isinstance(final, dict) and final.get("status") == "complete":
            errors.append(
                "completion.final.status cannot be complete for schema_version 3; "
                "only the CI attestation can declare completion"
            )

    if not state_at_least(state, "VERIFYING"):
        return errors

    planned_ids = {
        item.get("id")
        for item in impact.get("planned_changes", [])
        if isinstance(item, dict) and is_text(item.get("id"))
    }
    planned_by_id = {
        item.get("id"): item
        for item in impact.get("planned_changes", [])
        if isinstance(item, dict) and is_text(item.get("id"))
    }
    allowed_actual_patterns = [
        str(pattern) for pattern in impact.get("allowed_unplanned_paths") or []
    ]
    actual = completion.get("actual_changes")
    mapped_ids: set[str] = set()
    actual_ids: set[str] = set()
    if not isinstance(actual, list) or not actual:
        errors.append("completion.actual_changes must contain the real implementation diff")
    else:
        for index, item in enumerate(actual):
            prefix = f"completion.actual_changes[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            for field in ("id", "planned_change_id", "summary"):
                require_text(errors, item.get(field), f"{prefix}.{field}")
            actual_id = item.get("id")
            if is_text(actual_id):
                if actual_id in actual_ids:
                    errors.append(f"duplicate actual change id: {actual_id}")
                actual_ids.add(actual_id)
            require_list(errors, item.get("paths"), f"{prefix}.paths")
            if not item.get("paths"):
                errors.append(f"{prefix}.paths must contain at least one path")
            planned_id = item.get("planned_change_id")
            if planned_id not in planned_ids:
                errors.append(f"{prefix}.planned_change_id is not declared in impact: {planned_id}")
            else:
                mapped_ids.add(planned_id)
                patterns = [
                    str(pattern)
                    for pattern in (planned_by_id[planned_id].get("paths") or [])
                ]
                for path_index, path in enumerate(item.get("paths") or []):
                    path_field = f"{prefix}.paths[{path_index}]"
                    require_text(errors, path, path_field)
                    # `[` and `]` are literal filename characters in this contract
                    # grammar (for example Next.js dynamic route folders such as
                    # `[operation]`).  Only `*` and `?` are supported glob tokens.
                    if is_text(path) and re.search(r"[*?]", normalized_path(path)):
                        errors.append(f"{path_field} must be an exact path, not a glob: {path}")
                    if (
                        is_text(path)
                        and not any(path_matches(path, pattern) for pattern in patterns)
                        and not any(
                            path_matches(path, pattern) for pattern in allowed_actual_patterns
                        )
                    ):
                        errors.append(
                            f"{path_field} is outside planned change {planned_id}: {path}"
                        )

    if not state_at_least(state, "GRAPH_DIFF_READY"):
        return errors

    missing_mappings = sorted(planned_ids - mapped_ids)
    if missing_mappings:
        errors.append(f"planned changes without actual-change evidence: {', '.join(missing_mappings)}")

    for index, delta in enumerate(completion.get("contract_delta") or []):
        prefix = f"completion.contract_delta[{index}]"
        if not isinstance(delta, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        for field in ("description", "reason", "effect"):
            require_text(errors, delta.get(field), f"{prefix}.{field}")
        if delta.get("accepted") is not True:
            errors.append(f"{prefix}.accepted must be true")

    plan_by_id = {
        item.get("id"): item
        for item in impact.get("verification_plan", [])
        if isinstance(item, dict) and is_text(item.get("id"))
    }
    results_by_id: dict[str, dict[str, Any]] = {}
    for index, result in enumerate(completion.get("verification_results") or []):
        prefix = f"completion.verification_results[{index}]"
        if not isinstance(result, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        for field in ("id", "command", "status", "evidence"):
            require_text(errors, result.get(field), f"{prefix}.{field}")
        if not isinstance(result.get("exit_code"), int):
            errors.append(f"{prefix}.exit_code must be an integer")
        if is_text(result.get("id")):
            result_id = result["id"]
            if result_id in results_by_id:
                errors.append(f"duplicate verification result id: {result_id}")
            results_by_id[result_id] = result
            planned_verification = plan_by_id.get(result_id)
            if planned_verification is None:
                errors.append(f"{prefix}.id is not declared in verification_plan: {result_id}")
            elif result.get("command") != planned_verification.get("command"):
                errors.append(
                    f"{prefix}.command must exactly match verification_plan {result_id}"
                )
    for verification_id, plan in plan_by_id.items():
        if not plan.get("required"):
            continue
        result = results_by_id.get(verification_id)
        if result is None:
            errors.append(f"required verification has no result: {verification_id}")
        elif result.get("status") != "passed" or result.get("exit_code") != 0:
            errors.append(f"required verification did not pass: {verification_id}")

    graph = completion.get("graph_diff")
    if not isinstance(graph, dict):
        errors.append("completion.graph_diff must be a mapping")
    else:
        if graph.get("status") not in FINAL_GRAPH_STATUSES:
            errors.append("completion.graph_diff.status must be clean or accepted")
        require_text(errors, graph.get("snapshot_before"), "completion.graph_diff.snapshot_before")
        require_text(errors, graph.get("snapshot_after"), "completion.graph_diff.snapshot_after")
        if impact_schema_version in {2, 3}:
            before_snapshot = impact.get("before_snapshot")
            expected_before = (
                before_snapshot.get("ref") if isinstance(before_snapshot, dict) else None
            )
            if not is_text(expected_before):
                errors.append(
                    "impact.before_snapshot.ref must be non-empty text for schema_version 2 or 3"
                )
            elif graph.get("snapshot_before") != expected_before:
                errors.append(
                    "completion.graph_diff.snapshot_before must match impact.before_snapshot.ref"
                )
        for field in (
            "added_nodes",
            "modified_nodes",
            "removed_nodes",
            "added_edges",
            "removed_edges",
            "required_edges",
            "orphan_nodes",
            "unknowns",
        ):
            require_list(errors, graph.get(field), f"completion.graph_diff.{field}")
        if graph.get("orphan_nodes"):
            errors.append("completion.graph_diff.orphan_nodes must be empty")
        required_edges = graph.get("required_edges") or []
        expected_edges = {
            (edge.get("from"), edge.get("to"), edge.get("relation"))
            for edge in (impact.get("graph_acceptance") or {}).get("required_edges") or []
            if isinstance(edge, dict)
        }
        expected_edge_count = len(expected_edges)
        if len(required_edges) < expected_edge_count:
            errors.append("completion.graph_diff.required_edges does not cover every required impact edge")
        actual_edges: set[tuple[Any, Any, Any]] = set()
        for index, edge in enumerate(required_edges):
            prefix = f"completion.graph_diff.required_edges[{index}]"
            if not isinstance(edge, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            for field in ("from", "to", "relation", "status", "evidence"):
                require_text(errors, edge.get(field), f"{prefix}.{field}")
            if edge.get("status") != "present":
                errors.append(f"{prefix}.status must be present")
            actual_edges.add((edge.get("from"), edge.get("to"), edge.get("relation")))
        for missing_edge in sorted(expected_edges - actual_edges, key=str):
            errors.append(
                "completion.graph_diff.required_edges is missing required impact edge: "
                f"{missing_edge[0]} -> {missing_edge[1]} ({missing_edge[2]})"
            )
        for index, unknown in enumerate(graph.get("unknowns") or []):
            prefix = f"completion.graph_diff.unknowns[{index}]"
            if not isinstance(unknown, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            for field in ("node_or_edge", "reason", "owner", "expires_at"):
                require_text(errors, unknown.get(field), f"{prefix}.{field}")
            if unknown.get("accepted") is not True:
                errors.append(f"{prefix}.accepted must be true")

    rollback = completion.get("rollback")
    if not isinstance(rollback, dict):
        errors.append("completion.rollback must be a mapping")
    elif state == "COMPLETE":
        if rollback.get("verified") is not True:
            errors.append("completion.rollback.verified must be true at COMPLETE")
        require_text(errors, rollback.get("evidence"), "completion.rollback.evidence")

    if state == "COMPLETE":
        final = completion.get("final")
        if not isinstance(final, dict):
            errors.append("completion.final must be a mapping")
        else:
            if final.get("status") != "complete":
                errors.append("completion.final.status must be complete")
            for field in ("completed_at", "completed_by", "summary"):
                require_text(errors, final.get(field), f"completion.final.{field}")

    return errors


def validate_changed_files(impact: dict[str, Any], changed_file_path: Path) -> list[str]:
    if not changed_file_path.exists():
        return [f"changed-files list does not exist: {changed_file_path}"]
    changed = [
        normalized_path(line)
        for line in changed_file_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    patterns: list[str] = []
    for item in impact.get("planned_changes") or []:
        if isinstance(item, dict):
            patterns.extend(normalized_path(str(path)) for path in item.get("paths") or [])
    patterns.extend(normalized_path(str(path)) for path in impact.get("allowed_unplanned_paths") or [])
    change_id = impact.get("change_id", "")
    contract_prefix = normalized_path(f"docs/dev-changes/{change_id}/")
    uncovered = [
        path
        for path in changed
        if not path.startswith(contract_prefix) and not any(path_matches(path, pattern) for pattern in patterns)
    ]
    return [f"changed file is outside locked impact scope: {path}" for path in uncovered]


def impact_template(change_id: str, title: str, risk_level: str = "R1") -> dict[str, Any]:
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"risk_level must be one of: {', '.join(RISK_LEVELS)}")
    now = utc_now()
    return {
        "schema_version": 3,
        "change_id": change_id,
        "title": title,
        "state": "DISCOVERED",
        "created_at": now,
        "updated_at": now,
        "feature_refs": [],
        "before_snapshot": {"ref": ""},
        "delivery": {"authority": DELIVERY_AUTHORITY, "base_commit": ""},
        "risk": {
            "level": risk_level,
            "contract_profile": CONTRACT_PROFILES[risk_level],
            "reasons": [],
            "external_effects": [],
            "scope_deltas": [],
            "approval": {"required": risk_level == "R3", "gate_ref": ""},
        },
        "intent": {"problem": "", "expected_outcome": "", "user_visible_behavior": []},
        "current_chain": {"nodes": [], "edges": [], "evidence": []},
        "scope": {key: [] for key in SCOPE_KEYS},
        "planned_changes": [],
        "allowed_unplanned_paths": [],
        "compatibility": {
            boundary: {"status": "not_applicable", "strategy": ""}
            for boundary in ("api", "database", "workflow", "data_source")
        },
        "graph_acceptance": {"required_edges": [], "allowed_unknowns": [], "forbidden_orphans": []},
        "risks": [],
        "out_of_scope": [],
        "rollback": {"strategy": "", "data_recovery": ""},
        "verification_plan": [],
        "lock": {"locked_at": None, "locked_by": None, "rationale": ""},
    }


def completion_template(change_id: str) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "change_id": change_id,
        "state": "DISCOVERED",
        "actual_changes": [],
        "contract_delta": [],
        "verification_results": [],
        "graph_diff": {
            "status": "pending",
            "snapshot_before": "",
            "snapshot_after": "",
            "added_nodes": [],
            "modified_nodes": [],
            "removed_nodes": [],
            "added_edges": [],
            "removed_edges": [],
            "required_edges": [],
            "orphan_nodes": [],
            "unknowns": [],
        },
        "exceptions": [],
        "delivery": {"status": "pending"},
        "rollback": {"verified": False, "evidence": ""},
        "final": {"status": "pending", "completed_at": None, "completed_by": None, "summary": ""},
    }


def command_init(args: argparse.Namespace) -> int:
    directory = Path(args.change_dir)
    impact_path = directory / "impact.yaml"
    completion_path = directory / "completion.yaml"
    existing = [path for path in (impact_path, completion_path) if path.exists()]
    if existing and not args.force:
        print("ERROR: refusing to overwrite existing contract(s):", file=sys.stderr)
        for path in existing:
            print(f"  {path}", file=sys.stderr)
        return 2
    write_yaml(impact_path, impact_template(args.change_id, args.title, args.risk_level))
    write_yaml(completion_path, completion_template(args.change_id))
    print(f"Created {impact_path}")
    print(f"Created {completion_path}")
    print("State: DISCOVERED")
    return 0


def load_completion(path: Path | None, impact: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, []
    try:
        return read_yaml(path), []
    except ValueError as exc:
        return None, [str(exc)]


def run_validation(
    impact: dict[str, Any],
    completion: dict[str, Any] | None,
    expect_state: str | None,
    strict: bool,
    changed_files_file: Path | None,
) -> list[str]:
    errors = validate_impact(impact)
    state = impact.get("state")
    if expect_state and state != expect_state:
        errors.append(f"expected state {expect_state}, found {state}")
    if state in STATES and state_at_least(state, "VERIFYING"):
        if completion is None:
            errors.append("completion contract is required from VERIFYING onward")
        else:
            errors.extend(validate_completion(impact, completion))
    elif completion is not None:
        errors.extend(validate_completion(impact, completion))
    if changed_files_file is not None:
        errors.extend(validate_changed_files(impact, changed_files_file))
    if strict:
        schema_version = impact.get("schema_version")
        if schema_version == 3 and state != "GRAPH_DIFF_READY":
            errors.append(
                "strict schema_version 3 validation requires GRAPH_DIFF_READY; "
                "CI attestation supplies COMPLETE"
            )
        elif schema_version in {1, 2} and state != "COMPLETE":
            errors.append("strict validation requires COMPLETE state")
    return errors


def command_validate(args: argparse.Namespace) -> int:
    try:
        impact = read_yaml(Path(args.impact))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    completion, completion_errors = load_completion(
        Path(args.completion) if args.completion else None,
        impact,
    )
    errors = completion_errors + run_validation(
        impact,
        completion,
        args.expect_state,
        args.strict,
        Path(args.changed_files_file) if args.changed_files_file else None,
    )
    if errors:
        print(f"FAILED: {len(errors)} contract error(s)", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"OK: contracts valid at state {impact.get('state')}")
    return 0


def command_transition(args: argparse.Namespace) -> int:
    impact_path = Path(args.impact)
    completion_path = Path(args.completion) if args.completion else impact_path.with_name("completion.yaml")
    try:
        impact = read_yaml(impact_path)
        completion = read_yaml(completion_path)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    current = impact.get("state")
    expected = NEXT_STATE.get(current)
    if expected is None:
        print(f"ERROR: state {current!r} has no forward transition", file=sys.stderr)
        return 1
    if args.to != expected:
        print(f"ERROR: state {current} may transition only to {expected}, not {args.to}", file=sys.stderr)
        return 1

    candidate_impact = deepcopy(impact)
    candidate_completion = deepcopy(completion)
    candidate_impact["state"] = args.to
    candidate_impact["updated_at"] = utc_now()
    candidate_completion["state"] = args.to
    if args.to == "IMPACT_LOCKED":
        candidate_impact.setdefault("lock", {})["locked_at"] = utc_now()
        candidate_impact["lock"]["locked_by"] = args.actor
        candidate_impact["lock"]["rationale"] = args.rationale
    if args.to == "COMPLETE":
        candidate_completion.setdefault("final", {})["completed_at"] = utc_now()
        candidate_completion["final"]["completed_by"] = args.actor

    errors = run_validation(candidate_impact, candidate_completion, args.to, False, None)
    if errors:
        print(f"BLOCKED: cannot transition to {args.to}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    write_yaml(impact_path, candidate_impact)
    write_yaml(completion_path, candidate_completion)
    print(f"Transitioned {current} -> {args.to}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create impact and completion contracts")
    init_parser.add_argument("--change-dir", required=True)
    init_parser.add_argument("--change-id", required=True)
    init_parser.add_argument("--title", required=True)
    init_parser.add_argument("--risk-level", choices=RISK_LEVELS, default="R1")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=command_init)

    validate_parser = subparsers.add_parser("validate", help="validate one contract pair")
    validate_parser.add_argument("--impact", required=True)
    validate_parser.add_argument("--completion")
    validate_parser.add_argument("--expect-state", choices=STATES)
    validate_parser.add_argument("--changed-files-file")
    validate_parser.add_argument("--strict", action="store_true")
    validate_parser.set_defaults(func=command_validate)

    transition_parser = subparsers.add_parser("transition", help="advance exactly one state")
    transition_parser.add_argument("--impact", required=True)
    transition_parser.add_argument("--completion")
    transition_parser.add_argument("--to", required=True, choices=STATES)
    transition_parser.add_argument("--actor", required=True)
    transition_parser.add_argument(
        "--rationale",
        default="Impact reviewed against current code, contracts, data, and downstream consumers.",
    )
    transition_parser.set_defaults(func=command_transition)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
