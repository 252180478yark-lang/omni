"""Strict Python mirror of the G1 Workbench Foundation v1 wire contract."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = 1
IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$"
OPAQUE_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:@-]{1,199}$"
SHA256_REF = r"^sha256:[0-9a-f]{64}$"
SHA256_DIGEST = r"^[0-9a-f]{64}$"
REASON_CODE = r"^[a-z][a-z0-9_.-]{0,99}$"
ROUTE = r"^/[^?#\r\n\x00\\]*$"
RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)

CONTEXT_AVAILABILITY = ("available", "unavailable")
PRESENTATION_LEVELS = ("summary", "development")
REBIND_STATES = ("bound", "stale", "rebind_required")
REQUESTED_PROVIDERS = ("auto", "codex", "claude")
RESOLVED_PROVIDERS = ("codex", "claude")
RUNNER_MODES = ("host", "local")
PROVIDER_STATUSES = ("pending", "resolved", "active", "paused", "failed", "unavailable")
HOST_STATES = ("healthy", "degraded", "stale", "unavailable", "unknown")
ARTIFACT_KINDS = ("input_attachment", "candidate_file", "output_asset", "formal_asset")
ARTIFACT_STATUSES = ("available", "stale", "unavailable", "rejected")
RISK_LEVELS = ("R0", "R1", "R2", "R3")
OPERATION_STATES = (
    "pending",
    "running",
    "paused",
    "awaiting_approval",
    "succeeded",
    "failed",
    "partial_failed",
    "cancelled",
    "unknown",
)
EVENT_STATUSES = ("running", "completed", "failed", "cancelled", "partial", "unknown")
IA_MODES = ("work", "development", "both")
IA_PHASES = ("active", "visible", "hidden", "retirement_candidate")
EXTENSION_SLOTS = ("assistant", "blueprint", "run-center", "approval", "artifact-drawer")


class StrictWireModel(BaseModel):
    """Reject coercion and unknown wire keys."""

    model_config = ConfigDict(extra="forbid", strict=True)

    _identifier_field_names: ClassVar[frozenset[str]] = frozenset({
        "snapshot_id", "context_ref", "workspace_ref", "shop_ref", "sku_ref",
        "project_ref", "environment_ref", "task_ref", "evidence_refs",
        "origin_surface_ref", "session_id", "operation_id", "context_snapshot_id",
        "surface_ref", "capabilities", "artifact_ref", "source_ref", "trace_id",
        "checkpoint", "event_id", "feature_id", "primary_group",
        "contextual_groups", "feature_flag",
    })

    @model_validator(mode="after")
    def identifiers_do_not_encode_raw_paths(self) -> "StrictWireModel":
        for field_name in self._identifier_field_names.intersection(type(self).model_fields):
            value = getattr(self, field_name)
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, str) and (":/" in item or ":\\" in item):
                    if re.fullmatch(r"(?:ui_route|api_route):/[A-Za-z0-9._/-]*", item) is None:
                        raise ValueError(f"{field_name} must be a stable reference, not a raw path")
        return self


class FrozenStrictWireModel(StrictWireModel):
    """An immutable value object; updates require a new contract instance."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _as_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


def _parse_rfc3339_datetime(value: object) -> object:
    """Parse request JSON timestamps without relaxing strict scalar validation."""

    if not isinstance(value, str):
        return value
    if RFC3339_DATETIME.fullmatch(value) is None:
        raise ValueError("datetime string must use RFC 3339 with an explicit timezone")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("datetime string must be a valid RFC 3339 timestamp") from exc


Rfc3339Datetime = Annotated[datetime, BeforeValidator(_parse_rfc3339_datetime)]


_RAW_PATH_PATTERNS = (
    re.compile(r"(?:^|[^A-Za-z0-9])[A-Za-z]:[\\/]"),
    re.compile(r"\\\\[^\\]+[\\/]"),
    re.compile(r"(?:^|[^A-Za-z0-9_])(?i:file://)"),
    re.compile(r'''(?:^|[\s=(\["'])/\S+'''),
    re.compile(r"(?i)%2f|%5c"),
)


def _ensure_safe_text(value: str, *, field_name: str, display_name: bool = False) -> str:
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain leading or trailing whitespace")
    if not value or any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{field_name} must be a non-empty single-line safe value")
    if any(pattern.search(value) for pattern in _RAW_PATH_PATTERNS):
        raise ValueError(f"{field_name} must not expose a raw project path")
    if display_name and ("/" in value or "\\" in value or value in {".", ".."} or value.startswith("~")):
        raise ValueError(f"{field_name} must be a display name, not a path")
    return value


class WorkbenchContextSnapshot(FrozenStrictWireModel):
    schema_version: Literal[1]
    snapshot_id: str = Field(pattern=IDENTIFIER)
    context_ref: str = Field(pattern=IDENTIFIER)
    revision: int = Field(ge=1)
    workspace_ref: str = Field(pattern=IDENTIFIER)
    shop_ref: str | None = Field(pattern=IDENTIFIER)
    sku_ref: str | None = Field(pattern=IDENTIFIER)
    project_ref: str | None = Field(pattern=IDENTIFIER)
    environment_ref: str | None = Field(pattern=IDENTIFIER)
    task_ref: str | None = Field(pattern=IDENTIFIER)
    evidence_refs: list[str]
    origin_surface_ref: str = Field(pattern=IDENTIFIER)
    permission_scope_hash: str = Field(pattern=SHA256_REF)
    availability: Literal["available", "unavailable"]
    rebind_reason: str | None = Field(pattern=REASON_CODE)
    created_at: Rfc3339Datetime

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_are_unique_identifiers(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_refs must be unique")
        invalid = [ref for ref in value if re.fullmatch(IDENTIFIER, ref) is None]
        if invalid:
            raise ValueError("evidence_refs must contain stable identifiers")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value, field_name="created_at")


class FrontendAgentBinding(FrozenStrictWireModel):
    """Host current-head projection kept separate from the accepted agent-session security anchor.

    Only the Host single writer advances this head by compare-and-swap.
    """

    schema_version: Literal[1]
    session_id: str = Field(pattern=IDENTIFIER)
    operation_id: str | None = Field(
        pattern=IDENTIFIER,
        description=(
            "Optional surface-selected operation; its frozen RunOperationProjection target may "
            "differ from the Host current head after a later rebind."
        ),
    )
    context_snapshot_id: str = Field(
        pattern=IDENTIFIER,
        description=(
            "Host-owned current context head; it is neither the accepted agent-session security "
            "anchor nor an existing operation target, and only the Host single writer may replace "
            "it after a successful compare-and-swap."
        ),
    )
    context_revision: int = Field(
        ge=1,
        description=(
            "Monotonic compare-and-swap token paired with context_snapshot_id; rebind supplies the "
            "expected snapshot and revision and advances to the canonical next revision."
        ),
    )
    surface_ref: str = Field(pattern=IDENTIFIER)
    event_cursor: int | None = Field(ge=0)
    presentation_level: Literal["summary", "development"]
    rebind_state: Literal["bound", "stale", "rebind_required"]


class ResolvedAgentProvider(FrozenStrictWireModel):
    schema_version: Literal[1]
    requested_provider: Literal["auto", "codex", "claude"]
    resolved_provider: Literal["codex", "claude"] | None
    runner_mode: Literal["host", "local"] | None
    fallback_reason_code: str | None = Field(pattern=REASON_CODE)
    status: Literal["pending", "resolved", "active", "paused", "failed", "unavailable"]
    accepted_at: Rfc3339Datetime | None
    capabilities: list[str]

    _accepted_statuses: ClassVar[frozenset[str]] = frozenset({"active", "paused", "failed"})

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_unique_identifiers(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        if any(re.fullmatch(IDENTIFIER, item) is None for item in value):
            raise ValueError("capabilities must contain stable identifiers")
        return value

    @field_validator("accepted_at")
    @classmethod
    def accepted_at_is_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _as_utc(value, field_name="accepted_at")

    @model_validator(mode="after")
    def provider_resolution_is_coherent(self) -> "ResolvedAgentProvider":
        resolved = self.resolved_provider is not None
        mode = self.runner_mode is not None
        accepted = self.accepted_at is not None

        if self.status in {"pending", "unavailable"} and (resolved or mode or accepted):
            raise ValueError(f"{self.status} provider must not claim a provider, runner mode, or acceptance")
        if self.status == "resolved" and (not resolved or not mode or accepted):
            raise ValueError("resolved provider requires provider and runner mode before acceptance")
        if self.status in self._accepted_statuses and (not resolved or not mode or not accepted):
            raise ValueError(f"{self.status} provider requires provider, runner mode, and accepted_at")
        if (
            self.requested_provider != "auto"
            and self.resolved_provider is not None
            and self.resolved_provider != self.requested_provider
            and self.fallback_reason_code is None
        ):
            raise ValueError("a non-auto provider fallback requires fallback_reason_code")
        return self


class OpaqueProjectIdentity(FrozenStrictWireModel):
    schema_version: Literal[1]
    project_handle: str = Field(pattern=OPAQUE_IDENTIFIER)
    project_hash: str = Field(pattern=SHA256_REF)
    display_name: str = Field(min_length=1, max_length=160)

    @field_validator("display_name")
    @classmethod
    def display_name_is_not_a_path(cls, value: str) -> str:
        return _ensure_safe_text(value, field_name="display_name", display_name=True)


class HostCapabilityManifest(FrozenStrictWireModel):
    schema_version: Literal[1]
    protocol_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
    state: Literal["healthy", "degraded", "stale", "unavailable", "unknown"]
    build_commit: str | None = Field(pattern=r"^[0-9a-f]{40}$")
    capabilities: list[str]
    providers: list[Literal["codex", "claude"]]
    project: OpaqueProjectIdentity | None
    reason_codes: list[str]

    @field_validator("capabilities")
    @classmethod
    def manifest_capabilities_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(re.fullmatch(IDENTIFIER, item) is None for item in value):
            raise ValueError("capabilities must contain unique stable identifiers")
        return value

    @field_validator("providers", "reason_codes")
    @classmethod
    def manifest_lists_are_unique(cls, value: list[str], info: object) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError(f"{getattr(info, 'field_name', 'manifest list')} must be unique")
        return value

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_are_valid(cls, value: list[str]) -> list[str]:
        if any(re.fullmatch(REASON_CODE, item) is None for item in value):
            raise ValueError("reason_codes must contain stable reason codes")
        return value


class AgentArtifactProjection(FrozenStrictWireModel):
    schema_version: Literal[1]
    cursor: int = Field(ge=1)
    artifact_ref: str = Field(pattern=IDENTIFIER)
    session_id: str = Field(pattern=IDENTIFIER)
    operation_id: str | None = Field(pattern=IDENTIFIER)
    context_snapshot_id: str = Field(pattern=IDENTIFIER)
    kind: Literal["input_attachment", "candidate_file", "output_asset", "formal_asset"]
    display_name: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=SHA256_DIGEST)
    size_bytes: int = Field(ge=0)
    status: Literal["available", "stale", "unavailable", "rejected"]
    safe_diff_summary: str | None = Field(min_length=1, max_length=2000)
    local_handle: str | None = Field(pattern=OPAQUE_IDENTIFIER)
    source_ref: str = Field(pattern=IDENTIFIER)

    @field_validator("display_name")
    @classmethod
    def artifact_display_name_is_not_a_path(cls, value: str) -> str:
        return _ensure_safe_text(value, field_name="display_name", display_name=True)

    @field_validator("safe_diff_summary")
    @classmethod
    def artifact_summary_is_redacted(cls, value: str | None) -> str | None:
        return None if value is None else _ensure_safe_text(value, field_name="safe_diff_summary")


class RunOperationProjection(FrozenStrictWireModel):
    """Existing operation projection with a complete snapshot/revision pair frozen across rebinds."""

    schema_version: Literal[1]
    operation_id: str = Field(pattern=IDENTIFIER)
    session_id: str | None = Field(pattern=IDENTIFIER)
    context_snapshot_id: str | None = Field(
        pattern=IDENTIFIER,
        description=(
            "Immutable per-operation target backed by mcp.runtime_executions.context_snapshot_id; "
            "nullable only for legacy operations and never retargeted from a later Host current head."
        ),
    )
    context_revision: int | None = Field(
        ge=1,
        description=(
            "Immutable revision paired with context_snapshot_id; legacy operations emit explicit "
            "null, while every new W5 operation emits the positive revision persisted by HostRun."
        ),
    )
    attempt: int = Field(ge=1)
    risk_level: Literal["R0", "R1", "R2", "R3"]
    state: Literal[
        "pending",
        "running",
        "paused",
        "awaiting_approval",
        "succeeded",
        "failed",
        "partial_failed",
        "cancelled",
        "unknown",
    ]
    idempotency_key_hash: str | None = Field(pattern=SHA256_REF)
    trace_id: str | None = Field(pattern=IDENTIFIER)
    checkpoint: str | None = Field(pattern=IDENTIFIER)
    updated_at: Rfc3339Datetime

    @field_validator("updated_at")
    @classmethod
    def updated_at_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value, field_name="updated_at")

    @model_validator(mode="after")
    def frozen_context_binding_is_complete(self) -> "RunOperationProjection":
        if (self.context_snapshot_id is None) != (self.context_revision is None):
            raise ValueError(
                "context_snapshot_id and context_revision must be both null for legacy "
                "operations or both non-null for new W5 operations"
            )
        return self


class RunEventProjection(FrozenStrictWireModel):
    schema_version: Literal[1]
    event_id: str = Field(pattern=IDENTIFIER)
    operation_id: str = Field(pattern=IDENTIFIER)
    attempt: int = Field(ge=1)
    cursor: int = Field(ge=1)
    type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    raw_type: str | None = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
    status: Literal["running", "completed", "failed", "cancelled", "partial", "unknown"]
    safe_summary: str = Field(min_length=1, max_length=2000)
    checkpoint: str | None = Field(pattern=IDENTIFIER)
    observed_at: Rfc3339Datetime

    @field_validator("safe_summary")
    @classmethod
    def event_summary_is_redacted(cls, value: str) -> str:
        return _ensure_safe_text(value, field_name="safe_summary")

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value, field_name="observed_at")


class WorkbenchIAProjection(FrozenStrictWireModel):
    schema_version: Literal[1]
    feature_id: str = Field(pattern=IDENTIFIER)
    owner: str = Field(min_length=1, max_length=200)
    renderer: str = Field(min_length=1, max_length=200)
    canonical_route: str = Field(pattern=ROUTE, max_length=300)
    aliases: list[str]
    mode: Literal["work", "development", "both"]
    primary_group: str = Field(pattern=IDENTIFIER)
    contextual_groups: list[str]
    phase: Literal["active", "visible", "hidden", "retirement_candidate"]
    feature_flag: str | None = Field(pattern=IDENTIFIER)

    @field_validator("owner", "renderer")
    @classmethod
    def ia_text_is_single_line(cls, value: str, info: object) -> str:
        return _ensure_safe_text(value, field_name=getattr(info, "field_name", "IA field"))

    @field_validator("aliases")
    @classmethod
    def aliases_are_unique_routes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("aliases must be unique")
        if any(re.fullmatch(ROUTE, route) is None or len(route) > 300 for route in value):
            raise ValueError("aliases must be absolute application routes of at most 300 characters")
        return value

    @field_validator("contextual_groups")
    @classmethod
    def contextual_groups_are_unique_identifiers(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("contextual_groups must be unique")
        if any(re.fullmatch(IDENTIFIER, group) is None for group in value):
            raise ValueError("contextual_groups must contain stable identifiers")
        return value


class WorkbenchExtensionSlot(FrozenStrictWireModel):
    schema_version: Literal[1]
    slot: Literal["assistant", "blueprint", "run-center", "approval", "artifact-drawer"]
    feature_id: str = Field(pattern=IDENTIFIER)
    order: int = Field(ge=0)


WORKBENCH_CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    model.__name__: model
    for model in (
        WorkbenchContextSnapshot,
        FrontendAgentBinding,
        ResolvedAgentProvider,
        OpaqueProjectIdentity,
        HostCapabilityManifest,
        AgentArtifactProjection,
        RunOperationProjection,
        RunEventProjection,
        WorkbenchIAProjection,
        WorkbenchExtensionSlot,
    )
}

WORKBENCH_CONTRACT_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    name: {
        "required": frozenset(field_name for field_name, field in model.model_fields.items() if field.is_required()),
        "optional": frozenset(field_name for field_name, field in model.model_fields.items() if not field.is_required()),
    }
    for name, model in WORKBENCH_CONTRACT_MODELS.items()
}

__all__ = [
    "AgentArtifactProjection",
    "FrontendAgentBinding",
    "HostCapabilityManifest",
    "OpaqueProjectIdentity",
    "ResolvedAgentProvider",
    "RunEventProjection",
    "RunOperationProjection",
    "WorkbenchContextSnapshot",
    "WorkbenchExtensionSlot",
    "WorkbenchIAProjection",
    "WORKBENCH_CONTRACT_FIELDS",
    "WORKBENCH_CONTRACT_MODELS",
]
