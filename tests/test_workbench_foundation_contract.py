from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ENGINE_ROOT = REPOSITORY_ROOT / "services" / "knowledge-engine"
sys.path.insert(0, str(KNOWLEDGE_ENGINE_ROOT))

from app.schemas.workbench_foundation import (  # noqa: E402
    AgentArtifactProjection,
    FrontendAgentBinding,
    OpaqueProjectIdentity,
    ResolvedAgentProvider,
    RunEventProjection,
    RunOperationProjection,
    WORKBENCH_CONTRACT_FIELDS,
    WORKBENCH_CONTRACT_MODELS,
    WorkbenchContextSnapshot,
    WorkbenchIAProjection,
)


SCHEMA_PATH = REPOSITORY_ROOT / "config" / "schemas" / "workbench-foundation.v1.schema.json"
MIGRATION_PATH = REPOSITORY_ROOT / "migrations" / "104_workbench_context_and_agent_binding.sql"
CONSUMER_MATRIX_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "dev-changes"
    / "2026-08-02-omni-unified-ai-workbench-g1-foundation"
    / "consumer-matrix.yaml"
)
CONTRACT_NAMES = (
    "WorkbenchContextSnapshot",
    "FrontendAgentBinding",
    "ResolvedAgentProvider",
    "OpaqueProjectIdentity",
    "HostCapabilityManifest",
    "AgentArtifactProjection",
    "RunOperationProjection",
    "RunEventProjection",
    "WorkbenchIAProjection",
    "WorkbenchExtensionSlot",
)


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _provider(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "requested_provider": "codex",
        "resolved_provider": "codex",
        "runner_mode": "host",
        "fallback_reason_code": None,
        "status": "active",
        "accepted_at": datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
        "capabilities": ["provider:codex", "resume"],
    }
    payload.update(overrides)
    return payload


def test_json_schema_is_draft_2020_12_and_matches_every_python_model_field() -> None:
    schema = _schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert set(CONTRACT_NAMES) <= set(schema["$defs"])
    assert set(WORKBENCH_CONTRACT_MODELS) == set(CONTRACT_NAMES)

    for contract_name in CONTRACT_NAMES:
        definition = schema["$defs"][contract_name]
        schema_fields = set(definition["properties"])
        schema_required = set(definition["required"])
        python_fields = set(WORKBENCH_CONTRACT_MODELS[contract_name].model_fields)

        assert definition["type"] == "object"
        assert definition["additionalProperties"] is False
        assert definition["properties"]["schema_version"] == {"const": 1}
        assert schema_fields == python_fields
        assert schema_required <= schema_fields
        expected_optional = (
            {"context_snapshot_id", "context_revision"}
            if contract_name == "RunOperationProjection"
            else set()
        )
        assert schema_fields - schema_required == expected_optional
        assert WORKBENCH_CONTRACT_FIELDS[contract_name] == {
            "required": frozenset(schema_required),
            "optional": frozenset(expected_optional),
        }
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", field_name) for field_name in schema_fields)


def test_surface_ref_is_current_binding_while_origin_surface_is_context_provenance() -> None:
    definitions = _schema()["$defs"]
    context_fields = set(definitions["WorkbenchContextSnapshot"]["properties"])
    binding_fields = set(definitions["FrontendAgentBinding"]["properties"])

    assert "origin_surface_ref" in context_fields
    assert "surface_ref" not in context_fields
    assert "surface_ref" in binding_fields
    assert "origin_surface_ref" not in binding_fields


def test_context_binding_semantics_separate_session_anchor_host_head_and_operation_target() -> None:
    schema = _schema()
    definitions = schema["$defs"]
    binding = definitions["FrontendAgentBinding"]
    operation = definitions["RunOperationProjection"]
    python_binding = FrontendAgentBinding.model_json_schema()
    python_operation = RunOperationProjection.model_json_schema()
    matrix = yaml.safe_load(CONSUMER_MATRIX_PATH.read_text(encoding="utf-8"))
    semantics = matrix["context_binding_semantics"]
    operation_contract = next(
        contract for contract in matrix["contracts"] if contract["name"] == "RunOperationProjection"
    )

    assert "accepted agent-session security anchor" in schema["description"]
    assert "Host-owned current head" in schema["description"]
    assert "immutable snapshot/revision target pair" in schema["description"]

    assert "Host-owned current context head" in binding["description"]
    assert "Host-owned current context head" in binding["properties"]["context_snapshot_id"]["description"]
    assert "successful compare-and-swap" in binding["properties"]["context_snapshot_id"]["description"]
    assert "expected snapshot and revision" in binding["properties"]["context_revision"]["description"]
    assert "may differ" in binding["properties"]["operation_id"]["description"]

    assert "immutable target pair selected" in operation["description"]
    assert "mcp.runtime_executions.context_snapshot_id" in operation["properties"]["context_snapshot_id"]["description"]
    assert "never retargeted" in operation["properties"]["context_snapshot_id"]["description"]
    assert "context_snapshot_id" not in operation["required"]
    assert "context_revision" not in operation["required"]
    assert operation["properties"]["context_revision"]["type"] == ["integer", "null"]
    assert operation["properties"]["context_revision"]["minimum"] == 1
    assert operation["oneOf"] == [
        {
            "not": {
                "anyOf": [
                    {"required": ["context_snapshot_id"]},
                    {"required": ["context_revision"]},
                ]
            }
        },
        {
            "required": ["context_snapshot_id", "context_revision"],
            "properties": {
                "context_snapshot_id": {"type": "null"},
                "context_revision": {"type": "null"},
            }
        },
        {
            "required": ["context_snapshot_id", "context_revision"],
            "properties": {
                "context_snapshot_id": {"$ref": "#/$defs/Identifier"},
                "context_revision": {"type": "integer", "minimum": 1},
            }
        },
    ]
    assert "Legacy operations may omit both pair fields" in operation["properties"]["context_revision"]["description"]
    assert "new W5 operation" in operation["properties"]["context_revision"]["description"]

    assert "accepted agent-session security anchor" in python_binding["description"]
    assert "Host-owned current context head" in python_binding["properties"]["context_snapshot_id"]["description"]
    assert "expected snapshot and revision" in python_binding["properties"]["context_revision"]["description"]
    assert "snapshot/revision pair frozen" in python_operation["description"]
    assert "mcp.runtime_executions.context_snapshot_id" in python_operation["properties"]["context_snapshot_id"]["description"]
    python_operation_revision = python_operation["properties"]["context_revision"]
    assert {"minimum": 1, "type": "integer"} in python_operation_revision["anyOf"]
    assert {"type": "null"} in python_operation_revision["anyOf"]
    assert "legacy omission normalizes to None" in python_operation_revision["description"]

    assert "Raw legacy wire may omit both fields or emit both explicit null" in operation_contract["rule"]
    assert "normalization produces (None, None)" in operation_contract["rule"]
    assert "new W5 operation requires both a non-null snapshot and positive persisted revision" in operation_contract["rule"]
    assert "half-bound pair is rejected" in operation_contract["rule"]

    assert semantics["session_security_anchor"] == {
        "authority": "mcp.agent_session_contracts.context_snapshot_id",
        "purpose": "Provider-acceptance and security anchor for the logical session.",
        "writer": "Agent session provider-acceptance owner.",
        "mutation": "Immutable once non-null; provider acceptance rechecks and freezes the same value.",
        "prohibited_use": "Do not mutate this column to represent a later page or business-object rebind.",
    }
    assert semantics["host_current_head"]["authority"] == (
        "FrontendAgentBinding.context_snapshot_id+context_revision"
    )
    assert semantics["host_current_head"]["writer"].startswith("Host single writer only")
    assert "expected context_snapshot_id and context_revision" in semantics["host_current_head"]["mutation"]
    assert semantics["operation_frozen_target"]["authority"] == (
        "mcp.runtime_executions.context_snapshot_id"
    )
    assert semantics["operation_frozen_target"]["projection"] == (
        "RunOperationProjection.context_snapshot_id"
    )
    assert semantics["operation_frozen_target"]["revision_projection"] == (
        "RunOperationProjection.context_revision"
    )
    assert (
        "may omit both context_snapshot_id and context_revision or emit both as explicit null"
        in semantics["operation_frozen_target"]["legacy_rule"]
    )
    assert any(
        "context_snapshot_id and context_revision" in invariant
        and "both absent or both null" in invariant
        and "both non-null" in invariant
        for invariant in semantics["invariants"]
    )
    assert semantics["operation_frozen_target"]["revision_source"] == "W5 HostRun.context_revision"
    assert "retain both original values" in semantics["operation_frozen_target"]["mutation"]
    assert "may omit both context_snapshot_id and context_revision" in semantics["operation_frozen_target"]["legacy_rule"]
    assert "positive context_revision" in semantics["operation_frozen_target"]["new_w5_rule"]

    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "agent session context snapshot binding is immutable" in migration
    assert "runtime execution context snapshot binding is immutable" in migration


def test_identifier_rejects_raw_absolute_paths_but_keeps_namespaced_refs() -> None:
    identifier = _schema()["$defs"]["Identifier"]

    def schema_accepts(value: str) -> bool:
        return bool(re.fullmatch(identifier["pattern"], value)) and (
            bool(re.search(identifier["anyOf"][0]["pattern"], value))
            or not re.search(identifier["anyOf"][1]["not"]["pattern"], value)
        )

    assert schema_accepts("ui_route:/chat")
    assert schema_accepts("workspace:omni")
    assert not schema_accepts("C:/Users/owner/omni")
    assert not schema_accepts("project:C:/Users/owner/omni")
    assert not schema_accepts("file:///tmp/private")
    assert not schema_accepts("evidence:file:///tmp/private")
    assert not schema_accepts("ui_route:/chat/C:/Users/owner")

    base = {
        "schema_version": 1,
        "snapshot_id": "context:snapshot-one",
        "context_ref": "context:one",
        "revision": 1,
        "workspace_ref": "workspace:omni",
        "shop_ref": None,
        "sku_ref": None,
        "project_ref": "ui_route:/chat",
        "environment_ref": None,
        "task_ref": None,
        "evidence_refs": ["evidence:one"],
        "origin_surface_ref": "ui_route:/chat",
        "permission_scope_hash": "sha256:" + "a" * 64,
        "availability": "available",
        "rebind_reason": None,
        "created_at": "2026-08-02T10:00:00Z",
    }
    assert WorkbenchContextSnapshot.model_validate(base).project_ref == "ui_route:/chat"
    with pytest.raises(ValidationError):
        WorkbenchContextSnapshot.model_validate({**base, "project_ref": "C:/Users/owner/omni"})
    with pytest.raises(ValidationError):
        WorkbenchContextSnapshot.model_validate({**base, "evidence_refs": ["file:///tmp/private"]})
    with pytest.raises(ValidationError):
        WorkbenchContextSnapshot.model_validate({**base, "project_ref": "project:C:/Users/owner/omni"})
    with pytest.raises(ValidationError):
        WorkbenchContextSnapshot.model_validate({**base, "evidence_refs": ["evidence:file:///tmp/private"]})
    with pytest.raises(ValidationError):
        WorkbenchContextSnapshot.model_validate({**base, "origin_surface_ref": "ui_route:/chat/C:/Users/owner"})


def test_standard_rfc3339_strings_parse_for_all_four_request_datetime_fields() -> None:
    timestamp = "2026-08-02T10:00:00.123Z"
    context = WorkbenchContextSnapshot.model_validate(
        {
            "schema_version": 1,
            "snapshot_id": "context:snapshot-one",
            "context_ref": "context:one",
            "revision": 1,
            "workspace_ref": "workspace:one",
            "shop_ref": None,
            "sku_ref": "sku:one",
            "project_ref": None,
            "environment_ref": None,
            "task_ref": "task:one",
            "evidence_refs": [],
            "origin_surface_ref": "ui_route:/chat",
            "permission_scope_hash": "sha256:" + "a" * 64,
            "availability": "available",
            "rebind_reason": None,
            "created_at": timestamp,
        }
    )
    provider = ResolvedAgentProvider.model_validate(_provider(accepted_at=timestamp))
    operation = RunOperationProjection.model_validate(
        {
            "schema_version": 1,
            "operation_id": "operation:one",
            "session_id": "session:one",
            "context_snapshot_id": "context:snapshot-one",
            "context_revision": 1,
            "attempt": 1,
            "risk_level": "R2",
            "state": "running",
            "idempotency_key_hash": "sha256:" + "b" * 64,
            "trace_id": "trace:one",
            "checkpoint": None,
            "updated_at": timestamp,
        }
    )
    event = RunEventProjection.model_validate(
        {
            "schema_version": 1,
            "event_id": "event:one",
            "operation_id": "operation:one",
            "attempt": 1,
            "cursor": 1,
            "type": "tool.completed",
            "raw_type": "item.completed",
            "status": "completed",
            "safe_summary": "candidate created",
            "checkpoint": None,
            "observed_at": timestamp,
        }
    )

    for value in (context.created_at, provider.accepted_at, operation.updated_at, event.observed_at):
        assert value is not None
        assert value.tzinfo is timezone.utc
        assert value.microsecond == 123000


def test_datetime_parsing_keeps_timezone_and_other_scalar_validation_strict() -> None:
    with pytest.raises(ValidationError, match="RFC 3339"):
        ResolvedAgentProvider.model_validate(_provider(accepted_at="2026-08-02T10:00:00"))

    with pytest.raises(ValidationError, match="must include a timezone"):
        ResolvedAgentProvider.model_validate(_provider(accepted_at=datetime(2026, 8, 2, 10, 0)))

    with pytest.raises(ValidationError):
        ResolvedAgentProvider.model_validate(_provider(schema_version="1"))

    operation_payload = {
        "schema_version": 1,
        "operation_id": "operation:one",
        "session_id": None,
        "context_snapshot_id": None,
        "context_revision": None,
        "attempt": "1",
        "risk_level": "R0",
        "state": "pending",
        "idempotency_key_hash": "sha256:" + "c" * 64,
        "trace_id": None,
        "checkpoint": None,
        "updated_at": "2026-08-02T10:00:00+00:00",
    }
    with pytest.raises(ValidationError):
        RunOperationProjection.model_validate(operation_payload)


def test_provider_contract_accepts_pre_acceptance_and_locked_states() -> None:
    pending = ResolvedAgentProvider(
        **_provider(
            status="pending",
            resolved_provider=None,
            runner_mode=None,
            accepted_at=None,
            capabilities=[],
        )
    )
    resolved = ResolvedAgentProvider(**_provider(status="resolved", accepted_at=None))
    active = ResolvedAgentProvider(**_provider())
    unavailable = ResolvedAgentProvider(
        **_provider(
            status="unavailable",
            resolved_provider=None,
            runner_mode=None,
            accepted_at=None,
            fallback_reason_code="provider_unavailable",
            capabilities=[],
        )
    )

    assert pending.status == "pending"
    assert resolved.status == "resolved"
    assert active.status == "active" and active.accepted_at is not None
    assert unavailable.status == "unavailable" and unavailable.resolved_provider is None

    with pytest.raises(ValidationError, match="frozen"):
        active.runner_mode = "local"  # type: ignore[misc]


@pytest.mark.parametrize("status", ["active", "paused", "failed"])
def test_accepted_provider_states_require_provider_mode_and_acceptance(status: str) -> None:
    for missing in ("resolved_provider", "runner_mode", "accepted_at"):
        changes = {"status": status, missing: None}
        with pytest.raises(ValidationError, match="requires provider, runner mode, and accepted_at"):
            ResolvedAgentProvider(**_provider(**changes))


def test_unavailable_provider_cannot_claim_resolution_or_acceptance() -> None:
    with pytest.raises(ValidationError, match="must not claim"):
        ResolvedAgentProvider(
            **_provider(
                status="unavailable",
                resolved_provider="codex",
                runner_mode=None,
                accepted_at=None,
            )
        )


def test_non_auto_provider_switch_requires_disclosed_fallback_reason() -> None:
    with pytest.raises(ValidationError, match="fallback_reason_code"):
        ResolvedAgentProvider(
            **_provider(
                status="resolved",
                requested_provider="codex",
                resolved_provider="claude",
                accepted_at=None,
                fallback_reason_code=None,
            )
        )

    disclosed = ResolvedAgentProvider(
        **_provider(
            status="resolved",
            requested_provider="codex",
            resolved_provider="claude",
            accepted_at=None,
            fallback_reason_code="host_unavailable",
        )
    )
    assert disclosed.resolved_provider == "claude"
    assert disclosed.fallback_reason_code == "host_unavailable"


def test_json_schema_declares_the_same_provider_state_and_fallback_rules() -> None:
    provider = _schema()["$defs"]["ResolvedAgentProvider"]
    rules = provider["allOf"]

    status_rules = {
        rule["if"]["properties"]["status"].get("const", tuple(rule["if"]["properties"]["status"].get("enum", []))): rule["then"]["properties"]
        for rule in rules
        if "status" in rule.get("if", {}).get("properties", {})
    }
    assert status_rules["pending"] == {
        "resolved_provider": {"const": None},
        "runner_mode": {"const": None},
        "accepted_at": {"const": None},
    }
    assert status_rules["resolved"] == {
        "resolved_provider": {"enum": ["codex", "claude"]},
        "runner_mode": {"enum": ["host", "local"]},
        "accepted_at": {"const": None},
    }
    assert status_rules[("active", "paused", "failed")]["accepted_at"]["type"] == "string"
    assert status_rules["unavailable"] == {
        "resolved_provider": {"const": None},
        "runner_mode": {"const": None},
        "accepted_at": {"const": None},
    }

    fallback_pairs = {
        (
            rule["if"]["properties"]["requested_provider"].get("const"),
            rule["if"]["properties"]["resolved_provider"].get("const"),
        )
        for rule in rules
        if "requested_provider" in rule.get("if", {}).get("properties", {})
        and rule.get("then", {}).get("properties", {}).get("fallback_reason_code") == {
            "$ref": "#/$defs/ReasonCode"
        }
    }
    assert fallback_pairs == {("codex", "claude"), ("claude", "codex")}


@pytest.mark.parametrize(
    "raw_name",
    [
        r"E:\\agent\\omni",
        r"C:/Users/owner/project",
        r"\\\\server\\share\\project",
        "/home/owner/project",
        "file:///tmp/project",
        "src/secret.txt",
        "..",
        " omni",
        "omni ",
    ],
)
def test_opaque_project_identity_rejects_path_shaped_display_names(raw_name: str) -> None:
    with pytest.raises(ValidationError):
        OpaqueProjectIdentity(
            schema_version=1,
            project_handle="project:opaque-one",
            project_hash="sha256:" + "a" * 64,
            display_name=raw_name,
        )


def test_public_projection_summaries_reject_embedded_absolute_paths() -> None:
    with pytest.raises(ValidationError, match="raw project path"):
        AgentArtifactProjection(
            schema_version=1,
            cursor=1,
            artifact_ref="artifact:one",
            session_id="session:one",
            operation_id="operation:one",
            context_snapshot_id="context:one",
            kind="candidate_file",
            display_name="candidate.py",
            sha256="a" * 64,
            size_bytes=12,
            status="available",
            safe_diff_summary=r"created C:\\Users\\owner\\candidate.py",
            local_handle="artifact-handle:one",
            source_ref="runtime:event-one",
        )


def test_json_safe_text_rules_match_python_path_and_name_guards() -> None:
    definitions = _schema()["$defs"]
    display_pattern = re.compile(definitions["SafeDisplayName"]["pattern"])
    summary_pattern = re.compile(definitions["SafeSummary"]["pattern"])
    forbidden_summary_patterns = [
        re.compile(rule["not"]["pattern"])
        for rule in definitions["SafeSummary"]["allOf"]
    ]

    assert display_pattern.fullmatch("omni-workbench")
    for unsafe_name in ("..", " omni", "omni ", "src/app.py", r"C:\\repo"):
        assert display_pattern.fullmatch(unsafe_name) is None

    assert summary_pattern.fullmatch("candidate created")
    assert summary_pattern.fullmatch(" candidate created") is None
    assert summary_pattern.fullmatch("candidate created ") is None
    for raw_summary in (
        r"created C:\\Users\\owner\\candidate.py",
        r"opened \\\\server\\share\\candidate.py",
        "saved /home/owner/candidate.py",
        "saved /srv/private/candidate.py",
        "loaded file:///tmp/candidate.py",
        "encoded %2Fhome%2Fowner",
    ):
        assert any(pattern.search(raw_summary) for pattern in forbidden_summary_patterns)

    ia_properties = definitions["WorkbenchIAProjection"]["properties"]
    assert ia_properties["owner"]["$ref"] == "#/$defs/SafeSummary"
    assert ia_properties["renderer"]["$ref"] == "#/$defs/SafeSummary"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("candidate created", True),
        ("profile://metadata", True),
        ("relative src/app.py", True),
        (" candidate created", False),
        ("candidate created ", False),
        (r"created C:\\Users\\owner\\candidate.py", False),
        (r"opened \\\\server\\share\\candidate.py", False),
        ("saved /srv/private/candidate.py", False),
        ("project_dir=/srv/private/omni", False),
        ('{"project_dir":"/srv/private/omni"}', False),
        ("loaded file:///tmp/candidate.py", False),
        ("中文file:///tmp/private", False),
        ("encoded %2Fhome%2Fowner", False),
    ],
)
def test_safe_summary_json_and_python_accept_the_same_examples(value: str, expected: bool) -> None:
    definition = _schema()["$defs"]["SafeSummary"]
    schema_accepts = (
        definition["minLength"] <= len(value) <= definition["maxLength"]
        and re.fullmatch(definition["pattern"], value) is not None
        and not any(re.search(rule["not"]["pattern"], value) for rule in definition["allOf"])
    )
    try:
        RunEventProjection(
            schema_version=1,
            event_id="event:parity",
            operation_id="operation:parity",
            attempt=1,
            cursor=1,
            type="tool.completed",
            raw_type=None,
            status="completed",
            safe_summary=value,
            checkpoint=None,
            observed_at="2026-08-02T10:00:00Z",
        )
        python_accepts = True
    except ValidationError:
        python_accepts = False
    assert schema_accepts is expected
    assert python_accepts is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Omni Workspace", True),
        ("omni-workbench", True),
        ("..", False),
        ("~repo", False),
        (" omni", False),
        ("omni ", False),
        ("src/app.py", False),
        (r"C:\\repo", False),
        ("encoded%2Froot", False),
    ],
)
def test_safe_display_name_json_and_python_accept_the_same_examples(value: str, expected: bool) -> None:
    definition = _schema()["$defs"]["SafeDisplayName"]
    schema_accepts = (
        definition["minLength"] <= len(value) <= definition["maxLength"]
        and re.fullmatch(definition["pattern"], value) is not None
    )
    try:
        OpaqueProjectIdentity(
            schema_version=1,
            project_handle="project-handle:parity",
            project_hash="sha256:" + "a" * 64,
            display_name=value,
        )
        python_accepts = True
    except ValidationError:
        python_accepts = False
    assert schema_accepts is expected
    assert python_accepts is expected


def test_aliases_have_the_same_300_character_limit_in_schema_and_python() -> None:
    alias_schema = _schema()["$defs"]["WorkbenchIAProjection"]["properties"]["aliases"]["items"]
    assert alias_schema["maxLength"] == 300

    with pytest.raises(ValidationError, match="at most 300"):
        WorkbenchIAProjection(
            schema_version=1,
            feature_id="feature:one",
            owner="workbench",
            renderer="web",
            canonical_route="/workbench",
            aliases=["/" + "a" * 300],
            mode="both",
            primary_group="group:work",
            contextual_groups=[],
            phase="active",
            feature_flag=None,
        )


def test_artifact_uses_prd_safe_diff_summary_name() -> None:
    artifact_fields = _schema()["$defs"]["AgentArtifactProjection"]["properties"]
    assert "safe_diff_summary" in artifact_fields
    assert "safe_summary" not in artifact_fields
    assert "safe_diff_summary" in AgentArtifactProjection.model_fields
    assert "safe_summary" not in AgentArtifactProjection.model_fields


def test_operation_accepts_legacy_missing_or_null_pair_and_rejects_half_bindings() -> None:
    payload = {
        "schema_version": 1,
        "operation_id": "operation:legacy",
        "session_id": None,
        "context_snapshot_id": None,
        "context_revision": None,
        "attempt": 1,
        "risk_level": "R0",
        "state": "unknown",
        "idempotency_key_hash": None,
        "trace_id": None,
        "checkpoint": None,
        "updated_at": "2026-08-02T10:00:00Z",
    }
    operation = RunOperationProjection.model_validate(payload)
    assert operation.context_revision is None
    assert operation.idempotency_key_hash is None

    missing_pair = dict(payload)
    missing_pair.pop("context_snapshot_id")
    missing_pair.pop("context_revision")
    normalized_legacy = RunOperationProjection.model_validate(missing_pair)
    assert (normalized_legacy.context_snapshot_id, normalized_legacy.context_revision) == (None, None)

    new_operation = RunOperationProjection.model_validate(
        {
            **payload,
            "operation_id": "operation:w5-new",
            "session_id": "session:w5-new",
            "context_snapshot_id": "context:w5-revision-two",
            "context_revision": 2,
            "state": "running",
        }
    )
    assert (new_operation.context_snapshot_id, new_operation.context_revision) == (
        "context:w5-revision-two",
        2,
    )

    with pytest.raises(ValidationError, match="both omitted/null.*both non-null"):
        RunOperationProjection.model_validate(
            {**missing_pair, "context_snapshot_id": "context:partial"}
        )
    with pytest.raises(ValidationError, match="both omitted/null.*both non-null"):
        RunOperationProjection.model_validate({**missing_pair, "context_revision": 2})

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        RunOperationProjection.model_validate({**payload, "context_revision": 0})

    payload.pop("idempotency_key_hash")
    with pytest.raises(ValidationError, match="idempotency_key_hash"):
        RunOperationProjection.model_validate(payload)


@pytest.mark.parametrize("route", ["/workbench?mode=dev", "/workbench#artifact"])
def test_canonical_routes_and_aliases_reject_query_or_fragment(route: str) -> None:
    common = {
        "schema_version": 1,
        "feature_id": "feature:one",
        "owner": "workbench",
        "renderer": "web",
        "mode": "both",
        "primary_group": "group:work",
        "contextual_groups": [],
        "phase": "active",
        "feature_flag": None,
    }
    with pytest.raises(ValidationError):
        WorkbenchIAProjection(canonical_route=route, aliases=[], **common)
    with pytest.raises(ValidationError, match="absolute application routes"):
        WorkbenchIAProjection(canonical_route="/workbench", aliases=[route], **common)

    with pytest.raises(ValidationError, match="raw project path"):
        RunEventProjection(
            schema_version=1,
            event_id="event:one",
            operation_id="operation:one",
            attempt=1,
            cursor=1,
            type="tool.completed",
            raw_type="item.completed",
            status="completed",
            safe_summary="saved /home/owner/private.txt",
            checkpoint=None,
            observed_at=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
        )


def test_public_foundation_schema_has_no_raw_project_dir_field() -> None:
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    python_fields = {
        field_name
        for contract in WORKBENCH_CONTRACT_FIELDS.values()
        for field_set in contract.values()
        for field_name in field_set
    }
    assert "project_dir" not in schema_text
    assert "project_dir" not in python_fields


def test_migration_104_is_additive_and_binds_existing_truth_sources() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", migration).lower()

    assert re.search(r"\bdrop\s+(?:table|column)\b", normalized) is None
    assert len(re.findall(r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?mcp\.", normalized)) == 1

    required_fragments = (
        "create table if not exists mcp.workbench_context_snapshots",
        "mcp.is_safe_workbench_ref",
        "mcp.are_safe_workbench_refs",
        "text_value = any(seen)",
        "constraint uq_workbench_context_snapshots_context_revision",
        "trg_workbench_context_snapshots_append_only",
        "alter table mcp.agent_session_contracts",
        "context_snapshot_id",
        "requested_provider",
        "resolved_runner_mode",
        "and runner_session_id is not null",
        "fallback_reason_code",
        "provider_accepted_at",
        "parent_session_id",
        "project_handle",
        "project_display_name",
        "rebind_reason ~ '^[a-z][a-z0-9_.-]{0,99}$'",
        "project_display_name !~ '^[[:space:]]'",
        "guard_agent_session_provider_acceptance",
        "trg_agent_session_contracts_provider_acceptance_lock",
        "alter table mcp.runtime_executions",
        "alter table mcp.approval_operations",
        "approval_operations_agent_session_fkey",
    )
    for fragment in required_fragments:
        assert fragment in normalized

    assert "create table if not exists mcp.agent_session" not in normalized
    assert "create table if not exists mcp.runtime_event" not in normalized
    assert "create table if not exists mcp.approval_operation" not in normalized
    assert "create table if not exists mcp.agent_artifact" not in normalized
