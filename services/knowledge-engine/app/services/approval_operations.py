"""Durable approval-operation state machine and PostgreSQL adapter.

Only redacted payloads are persisted.  A worker records ``effect_started``
before invoking a handler; an expired lease after that boundary is never
blindly replayed and moves to manual reconciliation.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

from app.database import get_pool
from app.schemas.approval_operations import (
    ApprovalDecision,
    ApprovalOperationAccepted,
    ApprovalOperationCreate,
    ApprovalOperationState,
    ApprovalOperationStatus,
    IdempotencyStrategy,
)


logger = logging.getLogger(__name__)


FINAL_STATES = {
    ApprovalOperationState.SUCCEEDED,
    ApprovalOperationState.FAILED,
    ApprovalOperationState.CANCELLED,
    ApprovalOperationState.EXPIRED,
    ApprovalOperationState.REVOKED,
    ApprovalOperationState.MANUAL_RECONCILIATION,
}
_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|authorization|cookie|credential|private[_-]?key)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_DSN_PASSWORD = re.compile(r"(?P<prefix>://[^:/\s]+:)[^@/\s]+(?=@)")
_API_KEY = re.compile(r"(?i)\b(?:sk|pk|api|key|token)[-_][A-Za-z0-9_-]{12,}\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_URL = re.compile(r"https?://[^\s<>'\"]+", re.I)
_SECRET_QUERY = re.compile(
    r"(?i)(?:^|[?&])(?:token|access_token|api[_-]?key|signature|sig|credential|x-amz-signature)="
)
_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SAFE_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
MAX_PERSISTED_JSON_BYTES = 256 * 1024
MAX_PERSISTED_DEPTH = 24
MAX_PRE_EFFECT_ATTEMPTS = 8
MAX_PRE_EFFECT_BACKOFF_SECONDS = 300


def _pre_effect_retry_delay(attempt_count: int) -> timedelta:
    seconds = min(
        MAX_PRE_EFFECT_BACKOFF_SECONDS,
        5 * (2 ** max(0, min(attempt_count - 1, 16))),
    )
    return timedelta(seconds=seconds)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[REDACTED_URL]"
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return "[REDACTED_URL]"
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return "[REDACTED_URL]"
    if port:
        host = f"{host}:{port}"
    path = _API_KEY.sub("[REDACTED]", _JWT.sub("[REDACTED]", parsed.path or "/"))
    return urlunsplit((parsed.scheme.lower(), host, path, "", ""))


def _freeze_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ApprovalOperationException(
            "invalid_target_url", "Target URL is invalid.", status=422
        ) from exc
    del port
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ApprovalOperationException(
            "invalid_target_url", "Target URL must use http or https.", status=422
        )
    if parsed.username is not None or parsed.password is not None:
        raise ApprovalOperationException(
            "raw_secret_forbidden", "Target URL userinfo must use a structured $secret_ref.", status=422
        )
    if (
        _SECRET_QUERY.search("?" + parsed.query)
        or _contains_raw_secret(parsed.path)
        or _contains_raw_secret(parsed.fragment)
    ):
        raise ApprovalOperationException(
            "raw_secret_forbidden", "Signed or credential-bearing target URLs must use $secret_ref.", status=422
        )
    return value


def sanitize_text(value: str) -> str:
    value = _DSN_PASSWORD.sub(r"\g<prefix>[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value))
    value = _API_KEY.sub("[REDACTED]", _JWT.sub("[REDACTED]", value))
    return _URL.sub(lambda match: _safe_url(match.group(0)), value)


def _contains_raw_secret(value: str) -> bool:
    if _BEARER.search(value) or _DSN_PASSWORD.search(value) or _API_KEY.search(value) or _JWT.search(value):
        return True
    return any(_SECRET_QUERY.search(match.group(0)) or "@" in urlsplit(match.group(0)).netloc for match in _URL.finditer(value))


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_PERSISTED_DEPTH:
        raise ApprovalOperationException(
            "persisted_value_too_deep", "Persisted result exceeds the nesting limit.", status=422
        )
    if value is None or isinstance(value, (bool, int, float, str)):
        bounded = value
    elif isinstance(value, dict):
        bounded = {str(key): _bounded_json(item, depth=depth + 1) for key, item in value.items()}
    elif isinstance(value, (list, tuple)):
        bounded = [_bounded_json(item, depth=depth + 1) for item in value]
    else:
        raise ApprovalOperationException(
            "persisted_value_not_json", "Persisted result must contain JSON-compatible values.", status=422
        )
    encoded = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"), default=None)
    if len(encoded.encode("utf-8")) > MAX_PERSISTED_JSON_BYTES:
        raise ApprovalOperationException(
            "persisted_value_too_large", "Persisted result exceeds the size limit.", status=422
        )
    return bounded


def redact_payload(value: Any, *, key: str = "") -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return {"$redacted": True}
    if isinstance(value, dict):
        return {str(k): redact_payload(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return copy.deepcopy(value)


def freeze_input(
    value: Any,
    *,
    key: str = "",
    _depth: int = 0,
    _validated: bool = False,
) -> Any:
    """Freeze executable input while refusing unrecoverable raw credentials."""

    # Validate the complete caller-controlled envelope before the credential
    # walk.  Without this preflight an adversarially deep value can raise a raw
    # RecursionError, and a very large value can consume work before the API
    # returns its documented 422 validation response.
    if not _validated:
        value = _bounded_json(value)
        _validated = True
    if _depth > MAX_PERSISTED_DEPTH:
        raise ApprovalOperationException(
            "persisted_value_too_deep", "Persisted input exceeds the nesting limit.", status=422
        )

    if key and _SENSITIVE_KEY.search(key):
        if (
            isinstance(value, dict)
            and set(value) == {"$secret_ref"}
            and isinstance(value["$secret_ref"], str)
            and _SAFE_REFERENCE.fullmatch(value["$secret_ref"].strip())
        ):
            return {"$secret_ref": value["$secret_ref"].strip()}
        raise ApprovalOperationException(
            "raw_secret_forbidden",
            f"Credential field '{key}' must use a structured $secret_ref.",
            status=422,
        )
    if isinstance(value, dict):
        if "$secret_ref" in value:
            if (
                set(value) != {"$secret_ref"}
                or not isinstance(value["$secret_ref"], str)
                or not _SAFE_REFERENCE.fullmatch(value["$secret_ref"].strip())
            ):
                raise ApprovalOperationException(
                    "invalid_secret_ref",
                    "$secret_ref must be the only non-empty string field.",
                    status=422,
                )
            return {"$secret_ref": value["$secret_ref"].strip()}
        return {
            str(k): freeze_input(
                v, key=str(k), _depth=_depth + 1, _validated=_validated
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            freeze_input(item, _depth=_depth + 1, _validated=_validated)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            freeze_input(item, _depth=_depth + 1, _validated=_validated)
            for item in value
        ]
    if isinstance(value, str):
        if _URL.fullmatch(value):
            return _freeze_url(value)
        if _contains_raw_secret(value):
            raise ApprovalOperationException(
                "raw_secret_forbidden",
                "Inline credentials and signed URLs must use $secret_ref.",
                status=422,
            )
    return copy.deepcopy(value)


@dataclass(frozen=True)
class ApprovalPrincipal:
    principal_id: str
    roles: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()
    verifier_version: str = "v1"

    def __post_init__(self) -> None:
        if not _SAFE_PRINCIPAL.fullmatch(self.principal_id) or _contains_raw_secret(self.principal_id):
            raise ValueError("principal_id must be a non-secret stable identifier")

    def can(self, scope: str) -> bool:
        return bool({"owner", "admin"}.intersection(self.roles)) or scope in self.scopes

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(
            {
                "principal_id": self.principal_id,
                "roles": sorted(self.roles),
                "scopes": sorted(self.scopes),
                "verifier_version": self.verifier_version,
            }
        )


def trusted_local_principal(environ: dict[str, str] | None = None) -> ApprovalPrincipal | None:
    env = environ if environ is not None else os.environ
    if env.get("OMNI_APPROVAL_AUTH_MODE", "").strip().lower() != "trusted-local":
        return None
    principal_id = env.get("OMNI_TRUSTED_LOCAL_PRINCIPAL", "").strip()
    if not principal_id:
        return None
    def split(name: str) -> frozenset[str]:
        return frozenset(
            item.strip() for item in env.get(name, "").split(",") if item.strip()
        )

    return ApprovalPrincipal(
        principal_id=principal_id,
        roles=split("OMNI_TRUSTED_LOCAL_ROLES"),
        scopes=split("OMNI_TRUSTED_LOCAL_SCOPES"),
        verifier_version=env.get("OMNI_APPROVAL_VERIFIER_VERSION", "local-v1"),
    )


def _approval_secret_configured(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    secret_path = env.get("OMNI_APPROVAL_SERVICE_SECRET_FILE", "").strip()
    if not secret_path:
        return False
    try:
        if len(Path(secret_path).read_bytes()) < 32:
            return False
    except OSError:
        return False
    return True


def identity_approver_principal(actor_id: str, role: str) -> ApprovalPrincipal | None:
    normalized_role = role.strip().lower()
    if normalized_role not in {"admin", "owner"} or not _SAFE_PRINCIPAL.fullmatch(actor_id):
        return None
    return ApprovalPrincipal(
        principal_id=f"identity:{actor_id}",
        roles=frozenset({normalized_role}),
        scopes=frozenset({"approval:read:any", "approval:decide"}),
        verifier_version="service-hmac-v1",
    )


def knowledge_engine_requester_principal(
    environ: dict[str, str] | None = None,
) -> ApprovalPrincipal | None:
    if not _approval_secret_configured(environ):
        return None
    return ApprovalPrincipal(
        principal_id="service:knowledge-engine",
        roles=frozenset({"approval-requester"}),
        scopes=frozenset({"approval:request", "approval:execute"}),
        verifier_version="internal-requester-v1",
    )


class ApprovalAuthorizationVerifier(Protocol):
    async def revalidate(self, record: "OperationRecord") -> bool: ...


class DenyApprovalAuthorizationVerifier:
    async def revalidate(self, record: "OperationRecord") -> bool:
        del record
        return False


class EnvironmentApprovalAuthorizationVerifier:
    async def revalidate(self, record: "OperationRecord") -> bool:
        principals = (trusted_local_principal(), knowledge_engine_requester_principal())
        return any(
            principal is not None
            and principal.principal_id == record.requested_by
            and principal.snapshot_hash == record.permission_snapshot_hash
            and principal.can("approval:execute")
            and record.decision is ApprovalDecision.APPROVED
            and bool(record.decision_actor and record.decision_actor.startswith("identity:"))
            for principal in principals
        )


class StaticApprovalAuthorizationVerifier:
    def __init__(self, principal: ApprovalPrincipal | None = None, *, allowed: bool = True) -> None:
        self.principal = principal
        self.allowed = allowed

    async def revalidate(self, record: "OperationRecord") -> bool:
        if not self.allowed:
            return False
        return self.principal is None or (
            self.principal.principal_id == record.requested_by
            and self.principal.snapshot_hash == record.permission_snapshot_hash
        )


class ApprovalOperationException(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int,
        retryable: bool = False,
        operation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable
        self.operation_id = operation_id


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    gate_id: str
    request_id: str
    requested_by: str
    permission_snapshot_hash: str
    trace_id: str | None
    handler: str
    summary: str
    risk: str
    idempotency_strategy: IdempotencyStrategy
    request_hash: str
    payload_hash: str
    redacted_payload: dict[str, Any]
    target: dict[str, Any]
    state: ApprovalOperationState
    decision: ApprovalDecision | None
    decision_note: str | None
    decision_actor: str | None
    expires_at: datetime
    worker_id: str | None
    worker_token: str | None
    lease_expires_at: datetime | None
    next_attempt_at: datetime | None
    effect_started_at: datetime | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ApprovalRepository(Protocol):
    async def create(self, record: OperationRecord) -> tuple[OperationRecord, bool]: ...
    async def get(self, operation_id: str) -> OperationRecord | None: ...
    async def get_by_gate(self, gate_id: str) -> OperationRecord | None: ...
    async def settle_expired(self, now: datetime) -> int: ...
    async def decide(
        self, gate_id: str, decision: ApprovalDecision, note: str, actor_id: str, now: datetime
    ) -> OperationRecord | None: ...
    async def revoke(
        self, operation_id: str, note: str, actor_id: str, now: datetime
    ) -> OperationRecord | None: ...
    async def recover_abandoned(self, now: datetime) -> tuple[int, int]: ...
    async def claim(
        self, worker_id: str, token: str, now: datetime, lease_until: datetime
    ) -> OperationRecord | None: ...
    async def mark_effect_started(self, operation_id: str, token: str, now: datetime) -> OperationRecord | None: ...
    async def release_before_effect(
        self, operation_id: str, token: str, error: dict[str, Any], now: datetime
    ) -> OperationRecord | None: ...
    async def finish(
        self,
        operation_id: str,
        token: str,
        state: ApprovalOperationState,
        result: dict[str, Any] | None,
        error: dict[str, Any] | None,
        now: datetime,
    ) -> OperationRecord | None: ...
    async def record_notification_failure(
        self, operation_id: str, now: datetime
    ) -> None: ...


class InMemoryApprovalRepository:
    """Deterministic adapter used by unit tests and local state-machine probes."""

    def __init__(self) -> None:
        self.operations: dict[str, OperationRecord] = {}
        self.requests: dict[str, str] = {}
        self.gates: dict[str, str] = {}
        self.audit_events: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def _audit(
        self,
        record: OperationRecord,
        action: str,
        actor_id: str,
        now: datetime,
        *,
        from_state: ApprovalOperationState | None,
        to_state: ApprovalOperationState,
        token: str | None = None,
    ) -> None:
        self.audit_events.append(
            {
                "operation_id": record.operation_id,
                "gate_id": record.gate_id,
                "request_id": record.request_id,
                "trace_id": record.trace_id,
                "actor_id": actor_id,
                "action": action,
                "from_state": from_state.value if from_state else None,
                "to_state": to_state.value,
                "worker_token_fingerprint": (
                    "sha256:" + hashlib.sha256(token.encode()).hexdigest()[:16] if token else None
                ),
                "created_at": now,
            }
        )

    async def create(self, record: OperationRecord) -> tuple[OperationRecord, bool]:
        async with self._lock:
            existing_id = self.requests.get(record.request_id)
            if existing_id:
                existing = self.operations[existing_id]
                if existing.request_hash != record.request_hash:
                    raise ApprovalOperationException(
                        "request_id_conflict",
                        "request_id already exists with different frozen input.",
                        status=409,
                        operation_id=existing.operation_id,
                    )
                return copy.deepcopy(existing), True
            self.operations[record.operation_id] = copy.deepcopy(record)
            self.requests[record.request_id] = record.operation_id
            self.gates[record.gate_id] = record.operation_id
            self._audit(
                record, "created", record.requested_by, record.created_at,
                from_state=None, to_state=ApprovalOperationState.PENDING,
            )
            return copy.deepcopy(record), False

    async def get(self, operation_id: str) -> OperationRecord | None:
        record = self.operations.get(operation_id)
        return copy.deepcopy(record) if record else None

    async def get_by_gate(self, gate_id: str) -> OperationRecord | None:
        operation_id = self.gates.get(gate_id)
        return await self.get(operation_id) if operation_id else None

    async def settle_expired(self, now: datetime) -> int:
        count = 0
        async with self._lock:
            for operation_id, record in list(self.operations.items()):
                if record.state is ApprovalOperationState.PENDING and record.expires_at <= now:
                    expired = replace(
                        record,
                        state=ApprovalOperationState.EXPIRED,
                        decision=ApprovalDecision.EXPIRED,
                        decision_note=record.decision_note or "approval expired",
                        updated_at=now,
                        completed_at=now,
                    )
                    self.operations[operation_id] = expired
                    self._audit(
                        expired, "expired", "system:expiry", now,
                        from_state=record.state, to_state=expired.state,
                    )
                    count += 1
        return count

    async def decide(
        self, gate_id: str, decision: ApprovalDecision, note: str, actor_id: str, now: datetime
    ) -> OperationRecord | None:
        note = sanitize_text(note)
        async with self._lock:
            operation_id = self.gates.get(gate_id)
            if not operation_id:
                return None
            record = self.operations[operation_id]
            if record.expires_at <= now and record.state is ApprovalOperationState.PENDING:
                record = replace(
                    record,
                    state=ApprovalOperationState.EXPIRED,
                    decision=ApprovalDecision.EXPIRED,
                    decision_note="approval expired",
                    updated_at=now,
                    completed_at=now,
                )
                self._audit(
                    record, "expired", "system:expiry", now,
                    from_state=ApprovalOperationState.PENDING, to_state=record.state,
                )
            elif record.decision is None and record.state is ApprovalOperationState.PENDING:
                state = (
                    ApprovalOperationState.PENDING
                    if decision is ApprovalDecision.APPROVED
                    else ApprovalOperationState.CANCELLED
                )
                record = replace(
                    record,
                    decision=decision,
                    decision_note=note,
                    decision_actor=actor_id,
                    state=state,
                    updated_at=now,
                    completed_at=now if state is ApprovalOperationState.CANCELLED else None,
                    error={"code": "rejected_by_user", "message": note} if state is ApprovalOperationState.CANCELLED else None,
                )
                self._audit(
                    record, decision.value, actor_id, now,
                    from_state=ApprovalOperationState.PENDING, to_state=record.state,
                )
            self.operations[operation_id] = record
            return copy.deepcopy(record)

    async def revoke(
        self, operation_id: str, note: str, actor_id: str, now: datetime
    ) -> OperationRecord | None:
        note = sanitize_text(note)
        async with self._lock:
            record = self.operations.get(operation_id)
            if record is None:
                return None
            if record.state in FINAL_STATES:
                return copy.deepcopy(record)
            if record.effect_started_at is not None:
                raise ApprovalOperationException(
                    "effect_already_started",
                    "The operation can no longer be safely revoked.",
                    status=409,
                    operation_id=operation_id,
                )
            record = replace(
                record,
                state=ApprovalOperationState.REVOKED,
                decision=ApprovalDecision.REVOKED,
                decision_note=note,
                decision_actor=actor_id,
                worker_id=None,
                worker_token=None,
                lease_expires_at=None,
                updated_at=now,
                completed_at=now,
            )
            self.operations[operation_id] = record
            self._audit(
                record, "revoked", actor_id, now,
                from_state=ApprovalOperationState.RESUMING if record.attempt_count else ApprovalOperationState.PENDING,
                to_state=record.state,
            )
            return copy.deepcopy(record)

    async def recover_abandoned(self, now: datetime) -> tuple[int, int]:
        reset = manual = 0
        async with self._lock:
            for operation_id, record in list(self.operations.items()):
                if (
                    record.state is ApprovalOperationState.RESUMING
                    and record.lease_expires_at is not None
                    and record.lease_expires_at <= now
                ):
                    if record.effect_started_at is not None:
                        record = replace(
                            record,
                            state=ApprovalOperationState.MANUAL_RECONCILIATION,
                            error={
                                "code": "effect_outcome_unknown",
                                "message": "Worker lease expired after effect_started; automatic replay is forbidden.",
                            },
                            worker_id=None,
                            worker_token=None,
                            lease_expires_at=None,
                            updated_at=now,
                            completed_at=now,
                        )
                        manual += 1
                        self._audit(
                            record, "manual_reconciliation", "system:recovery", now,
                            from_state=ApprovalOperationState.RESUMING, to_state=record.state,
                        )
                    else:
                        exhausted = record.attempt_count >= MAX_PRE_EFFECT_ATTEMPTS
                        record = replace(
                            record,
                            state=(
                                ApprovalOperationState.FAILED
                                if exhausted
                                else ApprovalOperationState.PENDING
                            ),
                            worker_id=None,
                            worker_token=None,
                            lease_expires_at=None,
                            next_attempt_at=(
                                None
                                if exhausted
                                else now + _pre_effect_retry_delay(record.attempt_count)
                            ),
                            error=(
                                {
                                    "code": "pre_effect_retry_exhausted",
                                    "retryable": False,
                                }
                                if exhausted
                                else record.error
                            ),
                            updated_at=now,
                            completed_at=now if exhausted else None,
                        )
                        reset += 1
                        self._audit(
                            record,
                            "failed" if exhausted else "recovered_pending",
                            "system:recovery", now,
                            from_state=ApprovalOperationState.RESUMING, to_state=record.state,
                        )
                    self.operations[operation_id] = record
        return reset, manual

    async def claim(
        self, worker_id: str, token: str, now: datetime, lease_until: datetime
    ) -> OperationRecord | None:
        async with self._lock:
            candidates = sorted(self.operations.values(), key=lambda item: item.created_at)
            for record in candidates:
                if (
                    record.state is ApprovalOperationState.PENDING
                    and record.decision is ApprovalDecision.APPROVED
                    and record.expires_at > now
                    and (record.next_attempt_at is None or record.next_attempt_at <= now)
                ):
                    claimed = replace(
                        record,
                        state=ApprovalOperationState.RESUMING,
                        worker_id=worker_id,
                        worker_token=token,
                        lease_expires_at=lease_until,
                        next_attempt_at=None,
                        attempt_count=record.attempt_count + 1,
                        updated_at=now,
                    )
                    self.operations[record.operation_id] = claimed
                    self._audit(
                        claimed, "claimed", worker_id, now,
                        from_state=ApprovalOperationState.PENDING, to_state=claimed.state, token=token,
                    )
                    return copy.deepcopy(claimed)
        return None

    async def mark_effect_started(self, operation_id: str, token: str, now: datetime) -> OperationRecord | None:
        async with self._lock:
            record = self.operations.get(operation_id)
            if (
                record is None
                or record.state is not ApprovalOperationState.RESUMING
                or record.worker_token != token
                or record.decision is not ApprovalDecision.APPROVED
                or record.expires_at <= now
                or (record.lease_expires_at is not None and record.lease_expires_at <= now)
                or record.effect_started_at is not None
            ):
                return None
            record = replace(record, effect_started_at=now, updated_at=now)
            self.operations[operation_id] = record
            self._audit(
                record, "effect_started", record.worker_id or "system:worker", now,
                from_state=ApprovalOperationState.RESUMING, to_state=record.state, token=token,
            )
            return copy.deepcopy(record)

    async def release_before_effect(
        self, operation_id: str, token: str, error: dict[str, Any], now: datetime
    ) -> OperationRecord | None:
        async with self._lock:
            record = self.operations.get(operation_id)
            if (
                record is None
                or record.state is not ApprovalOperationState.RESUMING
                or record.worker_token != token
                or record.effect_started_at is not None
                or record.decision is not ApprovalDecision.APPROVED
                or record.expires_at <= now
            ):
                return None
            retryable = bool(error.get("retryable") is True)
            exhausted = record.attempt_count >= MAX_PRE_EFFECT_ATTEMPTS
            will_retry = retryable and not exhausted
            safe_error = redact_payload(_bounded_json(error))
            if retryable and exhausted:
                safe_error = {**safe_error, "retryable": False, "retry_exhausted": True}
            record = replace(
                record,
                state=(
                    ApprovalOperationState.PENDING
                    if will_retry
                    else ApprovalOperationState.FAILED
                ),
                worker_id=None,
                worker_token=None,
                lease_expires_at=None,
                next_attempt_at=(
                    now + _pre_effect_retry_delay(record.attempt_count)
                    if will_retry
                    else None
                ),
                error=safe_error,
                updated_at=now,
                completed_at=None if will_retry else now,
            )
            self.operations[operation_id] = record
            self._audit(
                record, "retry_scheduled" if will_retry else "failed", "system:worker", now,
                from_state=ApprovalOperationState.RESUMING, to_state=record.state, token=token,
            )
            return copy.deepcopy(record)

    async def finish(
        self,
        operation_id: str,
        token: str,
        state: ApprovalOperationState,
        result: dict[str, Any] | None,
        error: dict[str, Any] | None,
        now: datetime,
    ) -> OperationRecord | None:
        async with self._lock:
            record = self.operations.get(operation_id)
            if record is None or record.state is not ApprovalOperationState.RESUMING or record.worker_token != token:
                return None
            record = replace(
                record,
                state=state,
                result=redact_payload(_bounded_json(result)) if result is not None else None,
                error=redact_payload(_bounded_json(error)) if error is not None else None,
                worker_id=None,
                worker_token=None,
                lease_expires_at=None,
                next_attempt_at=None,
                updated_at=now,
                completed_at=now,
            )
            self.operations[operation_id] = record
            self._audit(
                record, state.value, "system:worker", now,
                from_state=ApprovalOperationState.RESUMING, to_state=record.state, token=token,
            )
            return copy.deepcopy(record)

    async def record_notification_failure(
        self, operation_id: str, now: datetime
    ) -> None:
        async with self._lock:
            record = self.operations.get(operation_id)
            if record is None:
                return
            self._audit(
                record,
                "notification_failed",
                "system:notifier",
                now,
                from_state=record.state,
                to_state=record.state,
            )


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _record(row: Any) -> OperationRecord:
    return OperationRecord(
        operation_id=str(row["id"]),
        gate_id=str(row["gate_id"]),
        request_id=row["request_id"],
        requested_by=row["requested_by"],
        permission_snapshot_hash=row["permission_snapshot_hash"],
        trace_id=row["trace_id"],
        handler=row["handler"],
        summary=row.get("summary", "") if hasattr(row, "get") else row["summary"],
        risk=row["risk"],
        idempotency_strategy=IdempotencyStrategy(row["idempotency_strategy"]),
        request_hash=row["request_hash"],
        payload_hash=row["payload_hash"],
        redacted_payload=_json_value(row["redacted_payload"]),
        target=_json_value(row["target"]),
        state=ApprovalOperationState(row["state"]),
        decision=ApprovalDecision(row["decision"]) if row["decision"] else None,
        decision_note=row["decision_note"],
        decision_actor=row["decision_actor"],
        expires_at=row["expires_at"],
        worker_id=row["worker_id"],
        worker_token=str(row["worker_lease_token"]) if row["worker_lease_token"] else None,
        lease_expires_at=row["worker_lease_expires_at"],
        next_attempt_at=row["next_attempt_at"],
        effect_started_at=row["effect_started_at"],
        result=_json_value(row["result"]),
        error=_json_value(row["error"]),
        attempt_count=row["attempt_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


class PostgresApprovalRepository:
    SELECT = """
        SELECT o.*, g.id AS gate_id, g.summary
          FROM mcp.approval_operations o
          JOIN mcp.human_gates g ON g.operation_id = o.id
    """

    def __init__(self, pool: Any | None = None) -> None:
        self.pool = pool or get_pool()

    async def create(self, record: OperationRecord) -> tuple[OperationRecord, bool]:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                inserted = await connection.fetchval(
                    """
                    INSERT INTO mcp.approval_operations
                      (id, request_id, requested_by, permission_snapshot_hash,
                       trace_id, handler, risk, idempotency_strategy,
                       request_hash, payload_hash, redacted_payload, target, state, expires_at,
                       created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12::jsonb,$13,$14,$15,$15)
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING id
                    """,
                    uuid.UUID(record.operation_id), record.request_id, record.requested_by,
                    record.permission_snapshot_hash, record.trace_id, record.handler,
                    record.risk, record.idempotency_strategy.value, record.request_hash,
                    record.payload_hash,
                    json.dumps(record.redacted_payload, ensure_ascii=False),
                    json.dumps(record.target, ensure_ascii=False), record.state.value,
                    record.expires_at, record.created_at,
                )
                if inserted:
                    timeout = max(30, int((record.expires_at - record.created_at).total_seconds()))
                    await connection.execute(
                        """
                        INSERT INTO mcp.human_gates
                          (id, tool_call_id, operation_id, summary, timeout_seconds, decision, created_at)
                        VALUES ($1, NULL, $2, $3, $4, NULL, $5)
                        """,
                        uuid.UUID(record.gate_id), uuid.UUID(record.operation_id), record.summary,
                        timeout, record.created_at,
                    )
                    await connection.execute(
                        """INSERT INTO mcp.approval_operation_audit
                                  (operation_id, actor_id, action, created_at)
                               VALUES ($1,$2,'created',$3)""",
                        uuid.UUID(record.operation_id), record.requested_by, record.created_at,
                    )
                row = await connection.fetchrow(
                    self.SELECT + " WHERE o.request_id=$1", record.request_id
                )
        if row is None:
            raise ApprovalOperationException(
                "operation_create_race", "Operation could not be read after atomic create.",
                status=503, retryable=True,
            )
        current = _record(row)
        if current.request_hash != record.request_hash:
            raise ApprovalOperationException(
                "request_id_conflict", "request_id already exists with different frozen input.",
                status=409, operation_id=current.operation_id,
            )
        return current, not bool(inserted)

    async def get(self, operation_id: str) -> OperationRecord | None:
        try:
            value = uuid.UUID(operation_id)
        except ValueError:
            return None
        row = await self.pool.fetchrow(self.SELECT + " WHERE o.id=$1", value)
        return _record(row) if row else None

    async def get_by_gate(self, gate_id: str) -> OperationRecord | None:
        try:
            value = uuid.UUID(gate_id)
        except ValueError:
            return None
        row = await self.pool.fetchrow(self.SELECT + " WHERE g.id=$1", value)
        return _record(row) if row else None

    async def settle_expired(self, now: datetime) -> int:
        result = await self.pool.execute(
            """
            WITH expired AS (
              UPDATE mcp.approval_operations
                 SET state='expired', decision='expired', decision_note=COALESCE(decision_note,'approval expired'),
                     updated_at=$1, completed_at=$1, version=version+1
               WHERE state='pending' AND expires_at <= $1
               RETURNING id, request_id, trace_id
            ), gates AS (
              UPDATE mcp.human_gates g
               SET decision='expired', decision_note=COALESCE(g.decision_note,'approval expired'), decided_at=$1
              FROM expired e WHERE g.operation_id=e.id AND g.decision IS NULL
              RETURNING g.operation_id
            )
            INSERT INTO mcp.approval_operation_audit
              (operation_id, actor_id, action, details, created_at)
            SELECT id, 'system:expiry', 'expired',
                   jsonb_build_object('from','pending','to','expired','request_id',request_id,'trace_id',trace_id),
                   $1
              FROM expired
            """,
            now,
        )
        try:
            return int(result.rsplit(" ", 1)[-1])
        except (ValueError, AttributeError):
            return 0

    async def decide(
        self, gate_id: str, decision: ApprovalDecision, note: str, actor_id: str, now: datetime
    ) -> OperationRecord | None:
        note = sanitize_text(note)
        try:
            gate_uuid = uuid.UUID(gate_id)
        except ValueError:
            return None
        operation_id: str | None = None
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    self.SELECT + " WHERE g.id=$1 FOR UPDATE OF o, g", gate_uuid
                )
                if row is None:
                    return None
                current = _record(row)
                operation_id = current.operation_id
                if current.expires_at <= now and current.state is ApprovalOperationState.PENDING:
                    await connection.execute(
                        """UPDATE mcp.approval_operations
                              SET state='expired', decision='expired',
                                  decision_note=COALESCE(decision_note,'approval expired'),
                                  updated_at=$1, completed_at=$1, version=version+1
                            WHERE id=$2 AND state='pending'""",
                        now, uuid.UUID(operation_id),
                    )
                    await connection.execute(
                        """UPDATE mcp.human_gates
                              SET decision='expired', decision_note=COALESCE(decision_note,'approval expired'),
                                  decided_at=$1
                            WHERE operation_id=$2 AND decision IS NULL""",
                        now, uuid.UUID(operation_id),
                    )
                    await connection.execute(
                        """INSERT INTO mcp.approval_operation_audit
                                  (operation_id, actor_id, action, details, created_at)
                               VALUES ($1,'system:expiry','expired',
                                       jsonb_build_object('from','pending','to','expired'),$2)""",
                        uuid.UUID(operation_id), now,
                    )
                elif current.decision is None and current.state is ApprovalOperationState.PENDING:
                    state = "pending" if decision is ApprovalDecision.APPROVED else "cancelled"
                    error = None if state == "pending" else json.dumps(
                        redact_payload({"code": "rejected_by_user", "message": note})
                    )
                    await connection.execute(
                        """UPDATE mcp.approval_operations
                              SET decision=$1, decision_note=$2, state=$3, error=$4::jsonb,
                                  decision_actor=$5, updated_at=$6,
                                  completed_at=CASE
                                      WHEN $3='cancelled' THEN $6::timestamptz
                                      ELSE NULL
                                  END,
                                  version=version+1
                            WHERE id=$7 AND decision IS NULL AND state='pending'""",
                        decision.value, note, state, error, actor_id, now, uuid.UUID(operation_id),
                    )
                    await connection.execute(
                        """UPDATE mcp.human_gates
                              SET decision=$1, decision_note=$2, decided_by=$3, decided_at=$4
                            WHERE operation_id=$5 AND decision IS NULL""",
                        decision.value, note, actor_id, now, uuid.UUID(operation_id),
                    )
                    await connection.execute(
                        """INSERT INTO mcp.approval_operation_audit
                                  (operation_id, actor_id, action, created_at)
                               VALUES ($1,$2,$3,$4)""",
                        uuid.UUID(operation_id), actor_id, decision.value, now,
                    )
        return await self.get(operation_id) if operation_id else None

    async def revoke(
        self, operation_id: str, note: str, actor_id: str, now: datetime
    ) -> OperationRecord | None:
        note = sanitize_text(note)
        try:
            operation_uuid = uuid.UUID(operation_id)
        except ValueError:
            return None
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    self.SELECT + " WHERE o.id=$1 FOR UPDATE OF o, g", operation_uuid
                )
                if row is None:
                    return None
                current = _record(row)
                if current.state in FINAL_STATES:
                    return current
                if current.effect_started_at:
                    raise ApprovalOperationException(
                        "effect_already_started", "The operation can no longer be safely revoked.",
                        status=409, operation_id=operation_id,
                    )
                await connection.execute(
                    """UPDATE mcp.approval_operations
                          SET state='revoked', decision='revoked', decision_note=$1,
                              decision_actor=$2, worker_id=NULL, worker_lease_token=NULL,
                              worker_lease_expires_at=NULL, updated_at=$3, completed_at=$3,
                              version=version+1
                        WHERE id=$4 AND state IN ('pending','resuming') AND effect_started_at IS NULL""",
                    note, actor_id, now, operation_uuid,
                )
                await connection.execute(
                    """UPDATE mcp.human_gates
                          SET decision='revoked', decision_note=$1, decided_by=$2, decided_at=$3
                        WHERE operation_id=$4 AND decision IS NULL""",
                    note, actor_id, now, operation_uuid,
                )
                await connection.execute(
                    """INSERT INTO mcp.approval_operation_audit
                              (operation_id, actor_id, action, created_at)
                           VALUES ($1,$2,'revoked',$3)""",
                    operation_uuid, actor_id, now,
                )
        return await self.get(operation_id)

    async def recover_abandoned(self, now: datetime) -> tuple[int, int]:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                manual = await connection.fetch(
                    """WITH recovered AS (
                        UPDATE mcp.approval_operations
                           SET state='manual_reconciliation', worker_id=NULL, worker_lease_token=NULL,
                               worker_lease_expires_at=NULL,
                               error='{"code":"effect_outcome_unknown","message":"lease expired after effect_started"}'::jsonb,
                               updated_at=$1, completed_at=$1, version=version+1
                         WHERE state='resuming' AND worker_lease_expires_at <= $1
                           AND effect_started_at IS NOT NULL
                         RETURNING id, request_id, trace_id
                      ), audit AS (
                        INSERT INTO mcp.approval_operation_audit
                          (operation_id, actor_id, action, details, created_at)
                        SELECT id, 'system:recovery', 'manual_reconciliation',
                               jsonb_build_object('from','resuming','to','manual_reconciliation','request_id',request_id,'trace_id',trace_id),
                               $1 FROM recovered
                        RETURNING operation_id
                      ) SELECT id FROM recovered""",
                    now,
                )
                reset = await connection.fetch(
                    """WITH recovered AS (
                        UPDATE mcp.approval_operations
                           SET state=CASE WHEN attempt_count >= $2 THEN 'failed' ELSE 'pending' END,
                               worker_id=NULL, worker_lease_token=NULL,
                               worker_lease_expires_at=NULL,
                               next_attempt_at=CASE
                                 WHEN attempt_count >= $2 THEN NULL
                                 ELSE $1 + LEAST(
                                   300,
                                   5 * CAST(power(2, GREATEST(attempt_count - 1, 0)) AS integer)
                                 ) * INTERVAL '1 second'
                               END,
                               error=CASE WHEN attempt_count >= $2
                                 THEN '{"code":"pre_effect_retry_exhausted","retryable":false}'::jsonb
                                 ELSE error END,
                               updated_at=$1,
                               completed_at=CASE WHEN attempt_count >= $2 THEN $1 ELSE NULL END,
                               version=version+1
                         WHERE state='resuming' AND worker_lease_expires_at <= $1
                           AND effect_started_at IS NULL
                         RETURNING id, request_id, trace_id, state
                      ), audit AS (
                        INSERT INTO mcp.approval_operation_audit
                          (operation_id, actor_id, action, details, created_at)
                        SELECT id, 'system:recovery',
                               CASE WHEN state='failed' THEN 'failed' ELSE 'recovered_pending' END,
                               jsonb_build_object('from','resuming','to',state,'request_id',request_id,'trace_id',trace_id),
                               $1 FROM recovered
                        RETURNING operation_id
                      ) SELECT id FROM recovered""",
                    now,
                    MAX_PRE_EFFECT_ATTEMPTS,
                )
        return len(reset), len(manual)

    async def claim(
        self, worker_id: str, token: str, now: datetime, lease_until: datetime
    ) -> OperationRecord | None:
        row = await self.pool.fetchrow(
            """
            WITH candidate AS (
              SELECT id FROM mcp.approval_operations
               WHERE state='pending' AND decision='approved' AND expires_at > $1
                 AND (next_attempt_at IS NULL OR next_attempt_at <= $1)
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
            )
            , claimed AS (
            UPDATE mcp.approval_operations o
               SET state='resuming', worker_id=$2, worker_lease_token=$3,
                   worker_lease_expires_at=$4, attempt_count=attempt_count+1,
                   updated_at=$1, version=version+1
              FROM candidate c WHERE o.id=c.id
            RETURNING o.id, o.worker_id, o.request_id, o.trace_id
            ), audit AS (
              INSERT INTO mcp.approval_operation_audit
                (operation_id, actor_id, action, details, created_at)
              SELECT id, worker_id, 'claimed',
                     jsonb_build_object('from','pending','to','resuming','request_id',request_id,'trace_id',trace_id),
                     $1 FROM claimed
              RETURNING operation_id
            )
            SELECT id FROM claimed
            """,
            now, worker_id, uuid.UUID(token), lease_until,
        )
        return await self.get(str(row["id"])) if row else None

    async def mark_effect_started(self, operation_id: str, token: str, now: datetime) -> OperationRecord | None:
        row = await self.pool.fetchrow(
            """WITH started AS (
                UPDATE mcp.approval_operations SET effect_started_at=$1, updated_at=$1, version=version+1
                WHERE id=$2 AND state='resuming' AND worker_lease_token=$3
                  AND worker_lease_expires_at > $1 AND decision='approved'
                  AND expires_at > $1 AND effect_started_at IS NULL
                RETURNING id, worker_id, request_id, trace_id
              ), audit AS (
                INSERT INTO mcp.approval_operation_audit
                  (operation_id, actor_id, action, details, created_at)
                SELECT id, COALESCE(worker_id,'system:worker'), 'effect_started',
                       jsonb_build_object('from','resuming','to','resuming','request_id',request_id,'trace_id',trace_id),
                       $1 FROM started
                RETURNING operation_id
              )
              SELECT id FROM started""",
            now, uuid.UUID(operation_id), uuid.UUID(token),
        )
        return await self.get(operation_id) if row else None

    async def release_before_effect(
        self, operation_id: str, token: str, error: dict[str, Any], now: datetime
    ) -> OperationRecord | None:
        current = await self.get(operation_id)
        retryable = bool(error.get("retryable") is True)
        exhausted = bool(current and current.attempt_count >= MAX_PRE_EFFECT_ATTEMPTS)
        will_retry = retryable and not exhausted
        safe_error = redact_payload(_bounded_json(error))
        if retryable and exhausted:
            safe_error = {**safe_error, "retryable": False, "retry_exhausted": True}
        next_attempt_at = (
            now + _pre_effect_retry_delay(current.attempt_count)
            if will_retry and current is not None
            else None
        )
        row = await self.pool.fetchrow(
            """WITH released AS (
                UPDATE mcp.approval_operations
                  SET state=$1, worker_id=NULL, worker_lease_token=NULL,
                      worker_lease_expires_at=NULL, next_attempt_at=$2,
                      error=$3::jsonb, updated_at=$4,
                      completed_at=CASE WHEN $1='failed' THEN $4 ELSE NULL END,
                      version=version+1
                WHERE id=$5 AND state='resuming' AND worker_lease_token=$6
                  AND effect_started_at IS NULL AND decision='approved' AND expires_at > $4
                RETURNING id, request_id, trace_id
              ), audit AS (
                INSERT INTO mcp.approval_operation_audit
                  (operation_id, actor_id, action, details, created_at)
                SELECT id, 'system:worker', $7,
                       jsonb_build_object('from','resuming','to',$1,'request_id',request_id,'trace_id',trace_id),
                       $4 FROM released
                RETURNING operation_id
              )
              SELECT id FROM released""",
            "pending" if will_retry else "failed",
            next_attempt_at,
            json.dumps(safe_error, ensure_ascii=False),
            now,
            uuid.UUID(operation_id),
            uuid.UUID(token),
            "retry_scheduled" if will_retry else "failed",
        )
        return await self.get(operation_id) if row else None

    async def finish(
        self, operation_id: str, token: str, state: ApprovalOperationState,
        result: dict[str, Any] | None, error: dict[str, Any] | None, now: datetime,
    ) -> OperationRecord | None:
        safe_result = redact_payload(_bounded_json(result)) if result is not None else None
        safe_error = redact_payload(_bounded_json(error)) if error is not None else None
        row = await self.pool.fetchrow(
            """WITH finished AS (
                UPDATE mcp.approval_operations
                  SET state=$1, result=$2::jsonb, error=$3::jsonb, worker_id=NULL,
                      worker_lease_token=NULL, worker_lease_expires_at=NULL,
                      next_attempt_at=NULL, updated_at=$4, completed_at=$4, version=version+1
                WHERE id=$5 AND state='resuming' AND worker_lease_token=$6
                RETURNING id, request_id, trace_id
              ), audit AS (
                INSERT INTO mcp.approval_operation_audit
                  (operation_id, actor_id, action, details, created_at)
                SELECT id, 'system:worker', $1,
                       jsonb_build_object('from','resuming','to',$1,'request_id',request_id,'trace_id',trace_id),
                       $4 FROM finished
                RETURNING operation_id
              )
              SELECT id FROM finished""",
            state.value,
            json.dumps(safe_result, ensure_ascii=False) if safe_result is not None else None,
            json.dumps(safe_error, ensure_ascii=False) if safe_error is not None else None,
            now, uuid.UUID(operation_id), uuid.UUID(token),
        )
        return await self.get(operation_id) if row else None

    async def record_notification_failure(
        self, operation_id: str, now: datetime
    ) -> None:
        await self.pool.execute(
            """INSERT INTO mcp.approval_operation_audit
                     (operation_id, actor_id, action, details, created_at)
                 SELECT id, 'system:notifier', 'notification_failed',
                        jsonb_build_object('state',state,'request_id',request_id,'trace_id',trace_id),
                        $1
                   FROM mcp.approval_operations
                  WHERE id=$2""",
            now,
            uuid.UUID(operation_id),
        )


def to_status(record: OperationRecord) -> ApprovalOperationStatus:
    return ApprovalOperationStatus(
        operation_id=record.operation_id,
        gate_id=record.gate_id,
        request_id=record.request_id,
        requested_by=record.requested_by,
        permission_snapshot_hash=record.permission_snapshot_hash,
        trace_id=record.trace_id,
        handler=record.handler,
        risk="R3",
        state=record.state,
        decision=record.decision,
        decision_note=sanitize_text(record.decision_note) if record.decision_note else None,
        decision_actor=record.decision_actor,
        payload_hash=record.payload_hash,
        target=redact_payload(record.target),
        expires_at=record.expires_at,
        worker_id=record.worker_id,
        lease_expires_at=record.lease_expires_at,
        next_attempt_at=record.next_attempt_at,
        effect_started_at=record.effect_started_at,
        result=redact_payload(record.result) if record.result is not None else None,
        error=redact_payload(record.error) if record.error is not None else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


class ApprovalOperationService:
    def __init__(
        self,
        repository: ApprovalRepository | None = None,
        *,
        now=utc_now,
        principal: ApprovalPrincipal | None = None,
        notify_gate: Callable[[str, str, str], Awaitable[None]] | None = None,
    ) -> None:
        self.repository = repository or PostgresApprovalRepository()
        self.now = now
        self.principal = principal
        self.notify_gate = notify_gate

    def _principal(self, principal: ApprovalPrincipal | None) -> ApprovalPrincipal:
        resolved = principal or self.principal
        if resolved is None:
            raise ApprovalOperationException(
                "authentication_required", "Trusted approval authentication is required.", status=401
            )
        return resolved

    async def create(
        self,
        request: ApprovalOperationCreate,
        principal: ApprovalPrincipal | None = None,
    ) -> ApprovalOperationAccepted:
        actor = self._principal(principal)
        if actor.principal_id.startswith("identity:"):
            raise ApprovalOperationException(
                "approval_requester_type_forbidden",
                "Human approver identities cannot create executable approval operations.",
                status=403,
            )
        if not actor.can("approval:request"):
            raise ApprovalOperationException(
                "approval_request_forbidden", "Principal cannot request approval operations.", status=403
            )
        now = self.now()
        operation_id = str(uuid.uuid4())
        gate_id = str(uuid.uuid4())
        frozen_payload = freeze_input(request.payload)
        frozen_target = freeze_input(request.target)
        summary = sanitize_text(request.summary)
        intent = {
            "requested_by": actor.principal_id,
            "permission_snapshot_hash": actor.snapshot_hash,
            "trace_id": request.trace_id,
            "handler": request.handler,
            "summary": summary,
            "payload": frozen_payload,
            "target": frozen_target,
            "risk": request.risk,
            "idempotency_strategy": request.idempotency_strategy.value,
            "expires_in_seconds": request.expires_in_seconds,
        }
        record = OperationRecord(
            operation_id=operation_id,
            gate_id=gate_id,
            request_id=request.request_id,
            requested_by=actor.principal_id,
            permission_snapshot_hash=actor.snapshot_hash,
            trace_id=request.trace_id,
            handler=request.handler,
            summary=summary,
            risk=request.risk,
            idempotency_strategy=request.idempotency_strategy,
            request_hash=canonical_hash(intent),
            payload_hash=canonical_hash(frozen_payload),
            redacted_payload=frozen_payload,
            target=frozen_target,
            state=ApprovalOperationState.PENDING,
            decision=None,
            decision_note=None,
            decision_actor=None,
            expires_at=now + timedelta(seconds=request.expires_in_seconds),
            worker_id=None,
            worker_token=None,
            lease_expires_at=None,
            next_attempt_at=None,
            effect_started_at=None,
            result=None,
            error=None,
            attempt_count=0,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        stored, duplicate = await self.repository.create(record)
        if not duplicate:
            notifier = self.notify_gate
            if notifier is None and isinstance(self.repository, PostgresApprovalRepository):
                from app.mcp.human_gate import _notify_human_gate

                async def notify_required(
                    short_id: str, handler: str, summary: str
                ) -> None:
                    await _notify_human_gate(
                        short_id, handler, summary, required=True
                    )

                notifier = notify_required
            if notifier is not None:
                try:
                    await notifier(
                        stored.gate_id[:8], stored.handler, sanitize_text(stored.summary)
                    )
                except Exception as exc:
                    logger.warning(
                        "approval notification delivery failed exception_type=%s",
                        type(exc).__name__,
                    )
                    try:
                        await self.repository.record_notification_failure(
                            stored.operation_id, self.now()
                        )
                    except Exception as audit_exc:
                        logger.error(
                            "approval notification failure audit unavailable exception_type=%s",
                            type(audit_exc).__name__,
                        )
        return ApprovalOperationAccepted(
            operation_id=stored.operation_id,
            gate_id=stored.gate_id,
            request_id=stored.request_id,
            state=stored.state,
            payload_hash=stored.payload_hash,
            permission_snapshot_hash=stored.permission_snapshot_hash,
            expires_at=stored.expires_at,
            status_url=f"/api/v1/approval-operations/{stored.operation_id}",
            duplicate=duplicate,
        )

    async def status(
        self,
        operation_id: str,
        principal: ApprovalPrincipal | None = None,
    ) -> ApprovalOperationStatus:
        actor = self._principal(principal)
        await self.repository.settle_expired(self.now())
        record = await self.repository.get(operation_id)
        if record is None:
            raise ApprovalOperationException("operation_not_found", "Approval operation was not found.", status=404)
        if record.requested_by != actor.principal_id and not actor.can("approval:read:any"):
            raise ApprovalOperationException(
                "approval_read_forbidden", "Principal cannot read this approval operation.", status=403
            )
        return to_status(record)

    async def revoke(
        self,
        operation_id: str,
        note: str,
        principal: ApprovalPrincipal | None = None,
    ) -> ApprovalOperationStatus:
        actor = self._principal(principal)
        existing = await self.repository.get(operation_id)
        if existing is None:
            raise ApprovalOperationException("operation_not_found", "Approval operation was not found.", status=404)
        allowed = actor.can("approval:revoke:any") or (
            existing.requested_by == actor.principal_id and actor.can("approval:revoke:self")
        )
        if not allowed:
            raise ApprovalOperationException(
                "approval_revoke_forbidden", "Principal cannot revoke this approval operation.", status=403
            )
        record = await self.repository.revoke(
            operation_id, sanitize_text(note), actor.principal_id, self.now()
        )
        if record is None:
            raise ApprovalOperationException("operation_not_found", "Approval operation was not found.", status=404)
        return to_status(record)


async def settle_expired_operations(repository: ApprovalRepository | None = None) -> int:
    return await (repository or PostgresApprovalRepository()).settle_expired(utc_now())


async def decide_gate_if_operation(
    gate_id: str,
    decision: ApprovalDecision,
    note: str = "",
    actor_id: str = "system:legacy",
    repository: ApprovalRepository | None = None,
) -> OperationRecord | None:
    repo = repository or PostgresApprovalRepository()
    try:
        if await repo.get_by_gate(gate_id) is None:
            return None
        return await repo.decide(gate_id, decision, sanitize_text(note), actor_id, utc_now())
    except Exception as exc:
        # Migration 098 compatibility only.  Connectivity and permission
        # failures must still surface instead of silently falling back.
        if getattr(exc, "sqlstate", None) in {"42P01", "42703"}:
            return None
        raise
