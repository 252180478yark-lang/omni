"""S8/S9/S10 contracts for redacted, append-only runtime execution evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$"


class EventType(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"
    GAP = "gap"
    ANNOTATION = "annotation"


class SpanKind(StrEnum):
    HTTP = "http"
    WEBSOCKET = "websocket"
    TOOL = "tool"
    SERVICE = "service"
    DATABASE = "database"
    SOURCE = "source"
    HOST = "host"
    MODEL = "model"
    GAP = "gap"


class RuntimeStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ReadWrite(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


class RuntimeEventInput(StrictModel):
    source: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,99}$")
    event_id: str = Field(pattern=IDENTIFIER)
    trace_id: str = Field(pattern=IDENTIFIER)
    execution_id: str = Field(pattern=IDENTIFIER)
    span_id: str | None = Field(default=None, pattern=IDENTIFIER)
    parent_span_id: str | None = Field(default=None, pattern=IDENTIFIER)
    correlation_id: str | None = Field(default=None, pattern=IDENTIFIER)
    session_id: str | None = Field(default=None, pattern=IDENTIFIER)
    gate_id: str | None = Field(default=None, pattern=IDENTIFIER)
    sequence: int | None = Field(default=None, ge=0)
    event_type: EventType
    status: RuntimeStatus
    span_kind: SpanKind = SpanKind.SERVICE
    node_id: str | None = Field(default=None, max_length=300)
    read_write: ReadWrite = ReadWrite.NONE
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    retention_days: int = Field(default=30, ge=1, le=365)

    @field_validator("node_id")
    @classmethod
    def node_id_is_stable_or_absent(cls, value: str | None) -> str | None:
        if value is not None and (not value or "\n" in value or "\r" in value):
            raise ValueError("node_id must be a single-line stable identifier")
        return value

    @model_validator(mode="after")
    def parent_requires_span(self) -> "RuntimeEventInput":
        if self.parent_span_id and not self.span_id:
            raise ValueError("parent_span_id requires span_id")
        expected = {
            EventType.STARTED: RuntimeStatus.RUNNING,
            EventType.COMPLETED: RuntimeStatus.COMPLETED,
            EventType.FAILED: RuntimeStatus.FAILED,
            EventType.CANCELLED: RuntimeStatus.CANCELLED,
        }.get(self.event_type)
        if expected is not None and self.status is not expected:
            raise ValueError(f"{self.event_type.value} event requires {expected.value} status")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        self.observed_at = self.observed_at.astimezone(timezone.utc)
        return self


class RuntimeEvent(StrictModel):
    cursor: int = Field(ge=1)
    source: str
    event_id: str
    trace_id: str
    execution_id: str
    span_id: str | None = None
    parent_span_id: str | None = None
    correlation_id: str | None = None
    session_id: str | None = None
    gate_id: str | None = None
    sequence: int | None = None
    event_type: EventType
    status: RuntimeStatus
    span_kind: SpanKind
    node_id: str | None = None
    read_write: ReadWrite
    payload_schema: list[str] = Field(default_factory=list)
    payload_summary: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    received_at: datetime
    retention_until: datetime
    ordering: Literal["known", "ordering_unknown"] = "known"


class RuntimeEventAppendResponse(StrictModel):
    event: RuntimeEvent
    duplicate: bool = False


class RuntimeEventPage(StrictModel):
    trace_id: str
    events: list[RuntimeEvent]
    next_cursor: int | None = Field(default=None, ge=1)
    replay_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    partial: bool = False
    has_more: bool = False
    dropped_count: int = Field(default=0, ge=0)
    redacted_count: int = Field(default=0, ge=0)


class RuntimeExecutionSummary(StrictModel):
    trace_id: str
    execution_id: str
    session_id: str | None = None
    gate_id: str | None = None
    status: RuntimeStatus
    event_count: int = Field(ge=1)
    last_cursor: int = Field(ge=1)
    updated_at: datetime


class RuntimeExecutionPage(StrictModel):
    runs: list[RuntimeExecutionSummary]


class FindingClassification(StrEnum):
    OBSERVED_FACT = "observed_fact"
    HYPOTHESIS = "hypothesis"


class FindingState(StrEnum):
    OPEN = "open"
    STALE = "stale"
    RESOLVED = "resolved"


class RuntimeFinding(StrictModel):
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    detector_version: str
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    severity: Literal["blocking", "warning", "info"]
    classification: FindingClassification
    state: FindingState
    layers: list[Literal["planned", "fact", "runtime", "delivery"]]
    trace_id: str
    message_zh: str
    evidence: list[str] = Field(default_factory=list)
    repair_hint: str
    verification: str
    impact_path: list[str] = Field(default_factory=list)
    possible_fix_locations: list[str] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)


class RuntimeFindingPage(StrictModel):
    trace_id: str
    findings: list[RuntimeFinding]
    source_status: Literal["success", "partial", "unknown"]


class RuntimePlanDraftCreate(StrictModel):
    finding_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trace_id: str = Field(pattern=IDENTIFIER)
    base_snapshot_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_version: int | None = Field(default=None, ge=1)


class RuntimePlanDraft(StrictModel):
    draft_id: str = Field(pattern=r"^plan:[0-9a-f]{32}$")
    finding_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trace_id: str = Field(pattern=IDENTIFIER)
    base_snapshot_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    title: str
    status: Literal["active", "frozen", "stale"] = "active"
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    reused: bool = False


class HostBuildIdentity(StrictModel):
    build_commit: str | None = Field(default=None, max_length=64)
    image_digest: str | None = Field(default=None, max_length=200)
    worktree_id: str | None = Field(default=None, max_length=128)
    allocation_id: str | None = Field(default=None, max_length=128)
    config_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    migration_head: str | None = Field(default=None, max_length=160)


class HostHealth(StrictModel):
    state: Literal["healthy", "degraded", "stale", "unavailable", "unknown"]
    instance_id: str = Field(pattern=IDENTIFIER)
    capabilities: list[str] = Field(default_factory=list)
    build_identity: HostBuildIdentity = Field(default_factory=HostBuildIdentity)
    reason_codes: list[str] = Field(default_factory=list)
    started_at: datetime | None = None


class ProviderSessionContract(StrictModel):
    session_id: str = Field(pattern=IDENTIFIER)
    runner_provider: Literal["codex", "claude"]
    runner_session_id: str | None = Field(default=None, pattern=IDENTIFIER)
    project_dir: str = Field(min_length=1, max_length=1024)
    model: str | None = Field(default=None, max_length=160)
    effort: str | None = Field(default=None, max_length=40)
    trace_id: str | None = Field(default=None, pattern=IDENTIFIER)
    status: Literal["active", "completed", "failed", "cancelled", "archived"] = "active"


class AgentSessionContractRecord(StrictModel):
    session_id: str = Field(pattern=IDENTIFIER)
    runner_provider: Literal["codex", "claude"]
    runner_session_id: str | None = Field(default=None, pattern=IDENTIFIER)
    project_dir_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model: str | None = None
    effort: str | None = None
    status: Literal["active", "completed", "failed", "cancelled", "archived"]
    trace_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AttachmentContract(StrictModel):
    attachment_id: str = Field(pattern=r"^attachment:[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    content_type: str = Field(min_length=1, max_length=200)
    storage_key: str = Field(pattern=r"^sha256/[0-9a-f]{64}(?:\.[a-z0-9]{1,10})?$")


class AgentAttachmentInput(AttachmentContract):
    session_id: str = Field(pattern=IDENTIFIER)


class AgentAttachmentRecord(AgentAttachmentInput):
    created_at: datetime
