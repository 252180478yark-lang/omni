"""CAS/lease worker for approved operations."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.schemas.approval_operations import ApprovalOperationState, IdempotencyStrategy
from app.services.approval_operations import (
    MAX_PERSISTED_DEPTH,
    ApprovalOperationException,
    ApprovalAuthorizationVerifier,
    ApprovalRepository,
    EnvironmentApprovalAuthorizationVerifier,
    OperationRecord,
    PostgresApprovalRepository,
    _bounded_json,
    utc_now,
)


logger = logging.getLogger(__name__)
Handler = Callable[[dict[str, Any], dict[str, Any], str], Awaitable[dict[str, Any]] | dict[str, Any]]
SecretResolver = Callable[[str], Awaitable[str] | str]


@dataclass(frozen=True)
class HandlerRegistration:
    function: Handler
    idempotency_strategy: IdempotencyStrategy


HANDLERS: dict[str, HandlerRegistration] = {}


@dataclass
class ApprovalWorkerRuntimeState:
    running: bool = False
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    last_error_fingerprint: str | None = None
    consecutive_failures: int = 0


APPROVAL_WORKER_RUNTIME = ApprovalWorkerRuntimeState()


def approval_worker_enabled(
    allocation: Mapping[str, Any],
    environ: dict[str, str] | None = None,
) -> bool:
    """Enable only for an explicitly selected owner of this allocation's DB."""

    env = environ if environ is not None else os.environ
    configured = env.get("OMNI_APPROVAL_WORKER_ENABLED", "false").strip().lower()
    if configured not in {"1", "true", "yes", "on"}:
        return False
    canonical = allocation.get("canonical")
    if canonical is True:
        return allocation.get("cron_owner") is True
    if canonical is False:
        # RuntimeAllocation guarantees an isolated database for noncanonical
        # worktrees; unlike cron ownership, its approval queue must be resumable.
        return True
    return False


async def _resolve_secret_refs(
    value: Any,
    resolver: SecretResolver | None,
    resolved_secrets: set[str],
    *,
    depth: int = 0,
) -> Any:
    if depth > MAX_PERSISTED_DEPTH:
        raise ValueError("approval input exceeds the nesting limit")
    if isinstance(value, dict) and set(value) == {"$secret_ref"}:
        if resolver is None:
            raise LookupError("secret resolver is not configured")
        resolved = resolver(str(value["$secret_ref"]))
        result = await resolved if inspect.isawaitable(resolved) else resolved
        if isinstance(result, bytes):
            try:
                result = result.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("secret resolver returned non-UTF8 bytes") from exc
        if not isinstance(result, str) or not (8 <= len(result) <= 65536):
            raise ValueError("secret resolver must return 8..65536 characters")
        resolved_secrets.add(result)
        return result
    if isinstance(value, dict):
        return {
            key: await _resolve_secret_refs(
                item, resolver, resolved_secrets, depth=depth + 1
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            await _resolve_secret_refs(
                item, resolver, resolved_secrets, depth=depth + 1
            )
            for item in value
        ]
    return value


def _redact_resolved_secrets(value: Any, resolved_secrets: set[str]) -> Any:
    if isinstance(value, dict):
        return {key: _redact_resolved_secrets(item, resolved_secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_resolved_secrets(item, resolved_secrets) for item in value]
    if isinstance(value, tuple):
        return [_redact_resolved_secrets(item, resolved_secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in sorted(resolved_secrets, key=len, reverse=True):
            redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    return value


def _exception_fingerprint(exc: Exception) -> str:
    raw = f"{type(exc).__module__}.{type(exc).__qualname__}:{exc}"
    return "sha256:" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def register_handler(
    name: str,
    function: Handler,
    *,
    idempotency_strategy: IdempotencyStrategy,
) -> None:
    if not name or name in HANDLERS:
        raise ValueError(f"approval handler already registered or invalid: {name}")
    HANDLERS[name] = HandlerRegistration(function, idempotency_strategy)


class ApprovalOperationWorker:
    def __init__(
        self,
        repository: ApprovalRepository | None = None,
        *,
        worker_id: str | None = None,
        handlers: dict[str, HandlerRegistration] | None = None,
        secret_resolver: SecretResolver | None = None,
        authorization_verifier: ApprovalAuthorizationVerifier | None = None,
        lease_seconds: int = 60,
        now=utc_now,
    ) -> None:
        self.repository = repository or PostgresApprovalRepository()
        self.worker_id = worker_id or f"approval-worker-{uuid.uuid4()}"
        self.handlers = handlers if handlers is not None else HANDLERS
        self.secret_resolver = secret_resolver
        self.authorization_verifier = (
            authorization_verifier or EnvironmentApprovalAuthorizationVerifier()
        )
        self.lease_seconds = lease_seconds
        self.now = now

    async def recover(self) -> tuple[int, int]:
        return await self.repository.recover_abandoned(self.now())

    async def run_once(self) -> OperationRecord | None:
        now = self.now()
        await self.repository.settle_expired(now)
        await self.repository.recover_abandoned(now)
        token = str(uuid.uuid4())
        record = await self.repository.claim(
            self.worker_id,
            token,
            now,
            now + timedelta(seconds=self.lease_seconds),
        )
        if record is None:
            return None
        registration = self.handlers.get(record.handler)
        if registration is None:
            return await self.repository.release_before_effect(
                record.operation_id,
                token,
                {
                    "code": "handler_not_registered",
                    "message": record.handler,
                    "retryable": False,
                },
                self.now(),
            )
        if registration.idempotency_strategy is not record.idempotency_strategy:
            return await self.repository.release_before_effect(
                record.operation_id,
                token,
                {
                    "code": "idempotency_strategy_mismatch",
                    "message": (
                        f"frozen={record.idempotency_strategy.value}, "
                        f"registered={registration.idempotency_strategy.value}"
                    ),
                    "retryable": False,
                },
                self.now(),
            )

        if not await self.authorization_verifier.revalidate(record):
            return await self.repository.release_before_effect(
                record.operation_id,
                token,
                {"code": "authorization_revalidation_failed", "retryable": False},
                self.now(),
            )

        try:
            resolved_secrets: set[str] = set()
            # Treat persisted storage as untrusted at the worker boundary too.
            bounded_payload = _bounded_json(record.redacted_payload)
            bounded_target = _bounded_json(record.target)
            resolved_payload = await _resolve_secret_refs(
                bounded_payload, self.secret_resolver, resolved_secrets
            )
            resolved_target = await _resolve_secret_refs(
                bounded_target, self.secret_resolver, resolved_secrets
            )
            # Secret substitution can expand a small reference into a much
            # larger value, so enforce the same aggregate envelope afterwards.
            resolved_payload = _bounded_json(resolved_payload)
            resolved_target = _bounded_json(resolved_target)
        except Exception as exc:
            fingerprint = _exception_fingerprint(exc)
            retryable = isinstance(exc, (ConnectionError, TimeoutError, OSError))
            logger.error(
                "approval secret resolution failed handler=%s exception_type=%s fingerprint=%s",
                record.handler,
                type(exc).__name__,
                fingerprint,
            )
            return await self.repository.release_before_effect(
                record.operation_id,
                token,
                {
                    "code": "secret_resolution_failed",
                    "exception_type": type(exc).__name__,
                    "fingerprint": fingerprint,
                    "retryable": retryable,
                },
                self.now(),
            )

        if not await self.authorization_verifier.revalidate(record):
            return await self.repository.release_before_effect(
                record.operation_id,
                token,
                {"code": "authorization_revalidation_failed", "retryable": False},
                self.now(),
            )

        started = await self.repository.mark_effect_started(record.operation_id, token, self.now())
        if started is None:
            failed = await self.repository.finish(
                record.operation_id,
                token,
                ApprovalOperationState.FAILED,
                None,
                {"code": "effect_boundary_revalidation_failed", "retryable": False},
                self.now(),
            )
            return failed or await self.repository.get(record.operation_id)
        try:
            result = registration.function(
                resolved_payload,
                resolved_target,
                started.operation_id,
            )
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                result = {"value": result}
            result = _redact_resolved_secrets(result, resolved_secrets)
        except asyncio.CancelledError:
            # Persisting an outcome is impossible while cancellation propagates.
            # Recovery will see effect_started and require reconciliation.
            raise
        except Exception as exc:
            fingerprint = _exception_fingerprint(exc)
            logger.error(
                "approval handler failed after effect_started handler=%s exception_type=%s fingerprint=%s",
                record.handler,
                type(exc).__name__,
                fingerprint,
            )
            return await self.repository.finish(
                record.operation_id,
                token,
                ApprovalOperationState.MANUAL_RECONCILIATION,
                None,
                {
                    "code": "effect_outcome_unknown",
                    "message": "Handler failed after the effect boundary; outcome requires reconciliation.",
                    "exception_type": type(exc).__name__,
                    "fingerprint": fingerprint,
                    "retryable": False,
                },
                self.now(),
            )
        try:
            return await self.repository.finish(
                record.operation_id,
                token,
                ApprovalOperationState.SUCCEEDED,
                result,
                None,
                self.now(),
            )
        except ApprovalOperationException as exc:
            return await self.repository.finish(
                record.operation_id,
                token,
                ApprovalOperationState.MANUAL_RECONCILIATION,
                None,
                {
                    "code": "handler_result_not_persistable",
                    "validation_code": exc.code,
                    "retryable": False,
                },
                self.now(),
            )


async def approval_operation_loop(
    *,
    poll_seconds: float = 1.0,
    repository: ApprovalRepository | None = None,
) -> None:
    worker = ApprovalOperationWorker(repository)
    backoff_seconds = max(0.1, poll_seconds)
    APPROVAL_WORKER_RUNTIME.running = True
    while True:
        try:
            await worker.recover()
            result = await worker.run_once()
            APPROVAL_WORKER_RUNTIME.last_success_at = datetime.now(timezone.utc)
            APPROVAL_WORKER_RUNTIME.last_error_code = None
            APPROVAL_WORKER_RUNTIME.last_error_fingerprint = None
            APPROVAL_WORKER_RUNTIME.consecutive_failures = 0
            backoff_seconds = max(0.1, poll_seconds)
            if result is None:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            APPROVAL_WORKER_RUNTIME.running = False
            raise
        except Exception as exc:
            fingerprint = _exception_fingerprint(exc)
            APPROVAL_WORKER_RUNTIME.last_error_code = "approval_worker_iteration_failed"
            APPROVAL_WORKER_RUNTIME.last_error_fingerprint = fingerprint
            APPROVAL_WORKER_RUNTIME.consecutive_failures += 1
            logger.error(
                "approval operation worker iteration failed exception_type=%s fingerprint=%s",
                type(exc).__name__,
                fingerprint,
            )
            await asyncio.sleep(min(backoff_seconds, 30.0))
            backoff_seconds = min(backoff_seconds * 2, 30.0)


async def _audit_fixture_handler(
    payload: dict[str, Any], target: dict[str, Any], operation_id: str
) -> dict[str, Any]:
    """No-side-effect R3 fixture proving the complete async approval path."""

    return {
        "receipt": "no_side_effect",
        "operation_id": operation_id,
        "payload_keys": sorted(str(key) for key in payload),
        "target_kind": str(target.get("kind", "fixture")),
    }


HANDLERS.setdefault(
    "system.noop-audit",
    HandlerRegistration(_audit_fixture_handler, IdempotencyStrategy.TRANSACTIONAL),
)
