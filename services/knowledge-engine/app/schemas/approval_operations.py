"""Public contracts for asynchronous, explicitly approved operations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SECRET_IDENTIFIER = re.compile(
    r"(?i)(?:\bBearer\b|(?:sk|pk|api|key|token)[-_][A-Za-z0-9_-]{12,}|"
    r"postgres(?:ql)?://[^\s]+:[^@\s]+@|[?&](?:token|signature|sig|key|credential)=)"
)


def _safe_identifier(value: str, field: str) -> str:
    value = value.strip()
    if not _IDENTIFIER.fullmatch(value) or _SECRET_IDENTIFIER.search(value):
        raise ValueError(f"{field} must be a non-secret stable identifier")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApprovalOperationState(StrEnum):
    PENDING = "pending"
    RESUMING = "resuming"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REVOKED = "revoked"
    MANUAL_RECONCILIATION = "manual_reconciliation"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class IdempotencyStrategy(StrEnum):
    TRANSACTIONAL = "transactional"
    PROVIDER_IDEMPOTENCY = "provider_idempotency"
    MANUAL_RECONCILIATION = "manual_reconciliation"


class PermissionSnapshot(StrictModel):
    roles: list[str] = Field(default_factory=list, max_length=100)
    scopes: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("roles", "scopes")
    @classmethod
    def normalize_permissions(cls, values: list[str]) -> list[str]:
        normalized = sorted({value.strip() for value in values if value.strip()})
        if any(
            len(value) > 200
            or not _IDENTIFIER.fullmatch(value)
            or _SECRET_IDENTIFIER.search(value)
            for value in normalized
        ):
            raise ValueError("permission name must be a non-secret stable identifier")
        return normalized


class ApprovalOperationCreate(StrictModel):
    request_id: str = Field(min_length=8, max_length=200)
    requested_by: str = Field(min_length=1, max_length=200)
    permission_snapshot: PermissionSnapshot
    trace_id: str | None = Field(default=None, max_length=200)
    handler: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    payload: dict[str, Any]
    target: dict[str, Any] = Field(default_factory=dict)
    risk: Literal["R3"] = "R3"
    idempotency_strategy: IdempotencyStrategy
    expires_in_seconds: int = Field(default=21600, ge=30, le=604800)

    @field_validator("request_id", "requested_by")
    @classmethod
    def identifiers_are_stable(cls, value: str, info) -> str:
        return _safe_identifier(value, info.field_name)

    @field_validator("trace_id")
    @classmethod
    def trace_id_is_stable(cls, value: str | None) -> str | None:
        return _safe_identifier(value, "trace_id") if value is not None else None


class ApprovalOperationAccepted(StrictModel):
    operation_id: str
    gate_id: str
    request_id: str
    state: ApprovalOperationState
    payload_hash: str
    permission_snapshot_hash: str
    expires_at: datetime
    status_url: str
    duplicate: bool = False


class ApprovalOperationStatus(StrictModel):
    operation_id: str
    gate_id: str
    request_id: str
    requested_by: str
    permission_snapshot_hash: str
    trace_id: str | None = None
    handler: str
    risk: Literal["R3"] = "R3"
    state: ApprovalOperationState
    decision: ApprovalDecision | None = None
    decision_note: str | None = None
    decision_actor: str | None = None
    payload_hash: str
    target: dict[str, Any]
    expires_at: datetime
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    next_attempt_at: datetime | None = None
    effect_started_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class RevokeRequest(StrictModel):
    note: str = Field(default="", max_length=500)


class ApprovalOperationError(StrictModel):
    code: str
    message: str
    status: int
    retryable: bool = False
    operation_id: str | None = None
