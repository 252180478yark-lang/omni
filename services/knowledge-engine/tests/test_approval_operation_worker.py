from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
import uuid

import httpx
import pytest
from fastapi import FastAPI

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.approval_operations import (
    ApprovalDecision,
    ApprovalOperationCreate,
    ApprovalOperationState,
    IdempotencyStrategy,
)
from app.services.approval_operations import (
    ApprovalOperationService,
    ApprovalPrincipal,
    InMemoryApprovalRepository,
    knowledge_engine_requester_principal,
    StaticApprovalAuthorizationVerifier,
)
from app.routers import human_gates as human_gate_router
from app.workers.approval_operations import (
    ApprovalOperationWorker,
    HandlerRegistration,
    approval_worker_enabled,
)


OWNER = ApprovalPrincipal(
    "user:owner",
    roles=frozenset({"owner"}),
    scopes=frozenset({"approval:request", "approval:execute"}),
)
ALLOW = StaticApprovalAuthorizationVerifier(OWNER)


def service_headers(secret: bytes, method: str, path: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    actor_id = "admin@example.com"
    actor_role = "admin"
    canonical = "\n".join(
        ("frontend", timestamp, nonce, method, path, body_hash, actor_id, actor_role)
    ).encode()
    return {
        "Content-Type": "application/json",
        "X-Omni-Service-Id": "frontend",
        "X-Omni-Timestamp": timestamp,
        "X-Omni-Nonce": nonce,
        "X-Omni-Body-SHA256": body_hash,
        "X-Omni-Signature": hmac.new(secret, canonical, hashlib.sha256).hexdigest(),
        "X-Omni-Actor-Id": actor_id,
        "X-Omni-Actor-Role": actor_role,
    }


class Clock:
    def __init__(self):
        self.value = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds: int):
        self.value += timedelta(seconds=seconds)


def test_worker_requires_explicit_enablement_and_database_ownership():
    canonical_owner = {"canonical": True, "cron_owner": True}
    canonical_follower = {"canonical": True, "cron_owner": False}
    isolated = {"canonical": False, "cron_owner": False}
    assert approval_worker_enabled(canonical_owner, {}) is False
    assert approval_worker_enabled(
        canonical_owner, {"OMNI_APPROVAL_WORKER_ENABLED": "true"}
    ) is True
    assert approval_worker_enabled(
        canonical_follower, {"OMNI_APPROVAL_WORKER_ENABLED": "true"}
    ) is False
    assert approval_worker_enabled(
        isolated, {"OMNI_APPROVAL_WORKER_ENABLED": "true"}
    ) is True
    assert approval_worker_enabled(
        isolated, {"OMNI_APPROVAL_WORKER_ENABLED": "false"}
    ) is False


async def approved(repository, clock, *, strategy=IdempotencyStrategy.PROVIDER_IDEMPOTENCY):
    service = ApprovalOperationService(repository, now=clock, principal=OWNER)
    accepted = await service.create(
        ApprovalOperationCreate(
            request_id=f"request-{len(repository.operations):04d}",
            requested_by="user:owner",
            permission_snapshot={"roles": ["owner"], "scopes": ["external:write"]},
            handler="fixture.effect",
            summary="fixture",
            payload={"value": 1},
            target={"provider": "fixture"},
            idempotency_strategy=strategy,
            expires_in_seconds=120,
        )
    )
    await repository.decide(
        accepted.gate_id, ApprovalDecision.APPROVED, "ok", OWNER.principal_id, clock()
    )
    return accepted


@pytest.mark.asyncio
async def test_two_workers_have_one_cas_claim_and_effect_runs_once():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)
    calls = []

    async def effect(payload, target, operation_id):
        calls.append((payload, target, operation_id))
        return {"provider_id": "external-1"}

    handlers = {
        "fixture.effect": HandlerRegistration(effect, IdempotencyStrategy.PROVIDER_IDEMPOTENCY)
    }
    first = ApprovalOperationWorker(
        repository, worker_id="w1", handlers=handlers, now=clock,
        authorization_verifier=ALLOW,
    )
    second = ApprovalOperationWorker(
        repository, worker_id="w2", handlers=handlers, now=clock,
        authorization_verifier=ALLOW,
    )
    results = await __import__("asyncio").gather(first.run_once(), second.run_once())

    final = await repository.get(accepted.operation_id)
    assert sum(result is not None for result in results) == 1
    assert len(calls) == 1
    assert final is not None and final.state is ApprovalOperationState.SUCCEEDED
    assert final.result == {"provider_id": "external-1"}


@pytest.mark.asyncio
async def test_restart_before_effect_resets_claim_and_can_resume():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)
    claimed = await repository.claim("dead-worker", "dead-token", clock(), clock() + timedelta(seconds=5))
    assert claimed is not None
    clock.advance(6)
    reset, manual = await repository.recover_abandoned(clock())
    assert (reset, manual) == (1, 0)
    record = await repository.get(accepted.operation_id)
    assert record is not None and record.state is ApprovalOperationState.PENDING


@pytest.mark.asyncio
async def test_restart_after_effect_never_replays_and_requires_manual_reconciliation():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)
    await repository.claim("dead-worker", "dead-token", clock(), clock() + timedelta(seconds=5))
    await repository.mark_effect_started(accepted.operation_id, "dead-token", clock())
    clock.advance(6)

    reset, manual = await repository.recover_abandoned(clock())
    record = await repository.get(accepted.operation_id)
    assert (reset, manual) == (0, 1)
    assert record is not None and record.state is ApprovalOperationState.MANUAL_RECONCILIATION
    assert record.error["code"] == "effect_outcome_unknown"


@pytest.mark.asyncio
async def test_handler_exception_after_effect_boundary_is_not_retried(caplog):
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)

    async def broken(*_args):
        raise RuntimeError("provider outcome uncertain SECRET-MUST-NOT-LEAK")

    worker = ApprovalOperationWorker(
        repository,
        handlers={
            "fixture.effect": HandlerRegistration(broken, IdempotencyStrategy.PROVIDER_IDEMPOTENCY)
        },
        authorization_verifier=ALLOW,
        now=clock,
    )
    result = await worker.run_once()
    assert result is not None
    assert result.operation_id == accepted.operation_id
    assert result.state is ApprovalOperationState.MANUAL_RECONCILIATION
    assert result.error["code"] == "effect_outcome_unknown"
    assert "SECRET-MUST-NOT-LEAK" not in str(result.error)
    assert "SECRET-MUST-NOT-LEAK" not in caplog.text


@pytest.mark.asyncio
async def test_secret_ref_resolves_only_in_memory_and_result_is_redacted():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    service = ApprovalOperationService(repository, now=clock, principal=OWNER)
    accepted = await service.create(
        ApprovalOperationCreate(
            request_id="request-secret-ref",
            requested_by="user:owner",
            permission_snapshot={"roles": ["owner"], "scopes": ["external:write"]},
            handler="fixture.effect",
            summary="fixture",
            payload={"api_token": {"$secret_ref": "vault/token"}},
            target={"provider": "fixture"},
            idempotency_strategy=IdempotencyStrategy.PROVIDER_IDEMPOTENCY,
            expires_in_seconds=120,
        )
    )
    await repository.decide(
        accepted.gate_id, ApprovalDecision.APPROVED, "ok", OWNER.principal_id, clock()
    )
    seen = []

    async def effect(payload, _target, _operation_id):
        seen.append(payload["api_token"])
        return {
            "api_token": "RESULT-SECRET",
            "provider_id": "ok",
            "echo": "prefix-RUNTIME-SECRET-suffix",
        }

    worker = ApprovalOperationWorker(
        repository,
        handlers={
            "fixture.effect": HandlerRegistration(effect, IdempotencyStrategy.PROVIDER_IDEMPOTENCY)
        },
        secret_resolver=lambda ref: "RUNTIME-SECRET" if ref == "vault/token" else "",
        authorization_verifier=ALLOW,
        now=clock,
    )
    result = await worker.run_once()
    persisted = await repository.get(accepted.operation_id)
    assert seen == ["RUNTIME-SECRET"]
    assert result is not None and result.state is ApprovalOperationState.SUCCEEDED
    assert persisted is not None
    assert "RUNTIME-SECRET" not in str(persisted)
    assert "RESULT-SECRET" not in str(persisted.result)
    assert persisted.result["api_token"] == {"$redacted": True}
    assert persisted.result["echo"] == "prefix-[REDACTED]-suffix"


@pytest.mark.asyncio
async def test_strategy_mismatch_fails_before_effect_started():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock, strategy=IdempotencyStrategy.TRANSACTIONAL)

    async def effect(*_args):
        raise AssertionError("must not run")

    worker = ApprovalOperationWorker(
        repository,
        handlers={
            "fixture.effect": HandlerRegistration(effect, IdempotencyStrategy.PROVIDER_IDEMPOTENCY)
        },
        authorization_verifier=ALLOW,
        now=clock,
    )
    result = await worker.run_once()
    record = await repository.get(accepted.operation_id)
    assert result is not None and result.state is ApprovalOperationState.FAILED
    assert record is not None and record.effect_started_at is None
    assert record.error["code"] == "idempotency_strategy_mismatch"
    assert record.next_attempt_at is None


@pytest.mark.asyncio
async def test_secret_resolution_failure_retries_same_operation_then_succeeds():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)
    record = await repository.get(accepted.operation_id)
    assert record is not None
    repository.operations[accepted.operation_id] = __import__("dataclasses").replace(
        record, redacted_payload={"api_token": {"$secret_ref": "vault/token"}}
    )
    calls = []

    async def effect(payload, _target, operation_id):
        calls.append((payload, operation_id))
        return {"ok": True}

    handlers = {
        "fixture.effect": HandlerRegistration(effect, IdempotencyStrategy.PROVIDER_IDEMPOTENCY)
    }
    first = ApprovalOperationWorker(
        repository,
        handlers=handlers,
        secret_resolver=lambda _ref: (_ for _ in ()).throw(ConnectionError("vault down")),
        authorization_verifier=ALLOW,
        now=clock,
    )
    pending = await first.run_once()
    assert pending is not None and pending.operation_id == accepted.operation_id
    assert pending.state is ApprovalOperationState.PENDING
    assert calls == []

    clock.advance(5)
    second = ApprovalOperationWorker(
        repository,
        handlers=handlers,
        secret_resolver=lambda _ref: "RECOVERED-SECRET",
        authorization_verifier=ALLOW,
        now=clock,
    )
    succeeded = await second.run_once()
    assert succeeded is not None and succeeded.operation_id == accepted.operation_id
    assert succeeded.state is ApprovalOperationState.SUCCEEDED
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_transient_pre_effect_failures_use_bounded_backoff_then_fail_terminally():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)
    record = await repository.get(accepted.operation_id)
    assert record is not None
    repository.operations[accepted.operation_id] = __import__("dataclasses").replace(
        record,
        redacted_payload={"api_token": {"$secret_ref": "vault/token"}},
        expires_at=clock() + timedelta(hours=2),
    )
    worker = ApprovalOperationWorker(
        repository,
        handlers={
            "fixture.effect": HandlerRegistration(
                lambda *_args: {"must": "not run"},
                IdempotencyStrategy.PROVIDER_IDEMPOTENCY,
            )
        },
        secret_resolver=lambda _ref: (_ for _ in ()).throw(
            ConnectionError("vault unavailable")
        ),
        authorization_verifier=ALLOW,
        now=clock,
    )

    expected_delays = [5, 10, 20, 40, 80, 160, 300]
    for attempt, delay in enumerate(expected_delays, start=1):
        pending = await worker.run_once()
        assert pending is not None
        assert pending.state is ApprovalOperationState.PENDING
        assert pending.attempt_count == attempt
        assert pending.next_attempt_at == clock() + timedelta(seconds=delay)
        clock.advance(delay)

    terminal = await worker.run_once()
    assert terminal is not None
    assert terminal.state is ApprovalOperationState.FAILED
    assert terminal.attempt_count == 8
    assert terminal.next_attempt_at is None
    assert terminal.error["retry_exhausted"] is True
    assert terminal.completed_at == clock()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolved",
    [None, "", "short", "x" * 65537],
    ids=["none", "empty", "short", "oversize"],
)
async def test_invalid_secret_resolver_values_fail_before_effect(resolved):
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)
    record = await repository.get(accepted.operation_id)
    assert record is not None
    repository.operations[accepted.operation_id] = __import__("dataclasses").replace(
        record, redacted_payload={"api_token": {"$secret_ref": "vault/token"}}
    )
    called = False

    async def effect(*_args):
        nonlocal called
        called = True
        return {"ok": True}

    worker = ApprovalOperationWorker(
        repository,
        handlers={
            "fixture.effect": HandlerRegistration(effect, IdempotencyStrategy.PROVIDER_IDEMPOTENCY)
        },
        secret_resolver=lambda _ref: resolved,
        authorization_verifier=ALLOW,
        now=clock,
    )
    result = await worker.run_once()
    assert result is not None and result.state is ApprovalOperationState.FAILED
    assert result.error["code"] == "secret_resolution_failed"
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["deep-persisted", "expanded-oversize"])
async def test_worker_enforces_input_envelope_before_effect(case):
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)
    record = await repository.get(accepted.operation_id)
    assert record is not None
    if case == "deep-persisted":
        payload: object = "leaf"
        for _ in range(40):
            payload = [payload]
        frozen = {"value": payload}
        resolver = None
    else:
        frozen = {
            f"part{index}": {"$secret_ref": f"vault/part{index}"}
            for index in range(5)
        }
        def resolver(_ref):
            return "s" * 65536
    repository.operations[accepted.operation_id] = __import__("dataclasses").replace(
        record, redacted_payload=frozen
    )
    calls = []

    async def effect(*_args):
        calls.append(True)
        return {"ok": True}

    worker = ApprovalOperationWorker(
        repository,
        handlers={
            "fixture.effect": HandlerRegistration(
                effect, IdempotencyStrategy.PROVIDER_IDEMPOTENCY
            )
        },
        secret_resolver=resolver,
        authorization_verifier=ALLOW,
        now=clock,
    )
    result = await worker.run_once()
    assert result is not None and result.state is ApprovalOperationState.FAILED
    assert result.error["code"] == "secret_resolution_failed"
    assert calls == []


@pytest.mark.asyncio
async def test_effect_boundary_rechecks_expiry_lease_and_revoke():
    async def scenario(kind: str):
        repository = InMemoryApprovalRepository()
        clock = Clock()
        accepted = await approved(repository, clock)
        record = await repository.get(accepted.operation_id)
        assert record is not None
        repository.operations[accepted.operation_id] = __import__("dataclasses").replace(
            record, redacted_payload={"api_token": {"$secret_ref": "vault/token"}}
        )
        calls = []

        async def resolve(_ref):
            if kind == "expiry":
                clock.advance(121)
            elif kind == "lease":
                clock.advance(6)
            else:
                await repository.revoke(
                    accepted.operation_id, "stop", OWNER.principal_id, clock()
                )
            return "BOUNDARY-SECRET"

        async def effect(*_args):
            calls.append(True)
            return {"ok": True}

        worker = ApprovalOperationWorker(
            repository,
            handlers={
                "fixture.effect": HandlerRegistration(effect, IdempotencyStrategy.PROVIDER_IDEMPOTENCY)
            },
            secret_resolver=resolve,
            authorization_verifier=ALLOW,
            lease_seconds=5,
            now=clock,
        )
        result = await worker.run_once()
        assert calls == []
        assert result is not None
        if kind == "revoke":
            assert result.state is ApprovalOperationState.REVOKED
        else:
            assert result.state is ApprovalOperationState.FAILED

    for kind in ("expiry", "lease", "revoke"):
        await scenario(kind)


def nested_value(depth: int):
    value = "x"
    for _ in range(depth):
        value = [value]
    return {"deep": value}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result_value",
    [
        {"blob": b"not-json"},
        {"oversize": "x" * (256 * 1024 + 1)},
        nested_value(30),
    ],
)
async def test_non_persistable_handler_result_moves_to_reconciliation(result_value):
    repository = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await approved(repository, clock)

    async def effect(*_args):
        return result_value

    worker = ApprovalOperationWorker(
        repository,
        handlers={
            "fixture.effect": HandlerRegistration(effect, IdempotencyStrategy.PROVIDER_IDEMPOTENCY)
        },
        authorization_verifier=ALLOW,
        now=clock,
    )
    result = await worker.run_once()
    assert result is not None and result.operation_id == accepted.operation_id
    assert result.state is ApprovalOperationState.MANUAL_RECONCILIATION
    assert result.error["code"] == "handler_result_not_persistable"


@pytest.mark.asyncio
async def test_hmac_create_approve_worker_status_chain_and_audit(tmp_path, monkeypatch):
    secret = b"fixture-hmac-secret-longer-than-thirty-two-bytes"
    secret_path = tmp_path / "approval-secret"
    secret_path.write_bytes(secret)
    monkeypatch.setenv("OMNI_APPROVAL_SERVICE_SECRET_FILE", str(secret_path))
    repository = InMemoryApprovalRepository()
    clock = Clock()
    requester = knowledge_engine_requester_principal()
    assert requester is not None
    service = ApprovalOperationService(repository, now=clock, principal=requester)

    async def approve_bridge(gate_id: str, note: str, *, actor_id: str):
        record = await repository.decide(
            gate_id, ApprovalDecision.APPROVED, note, actor_id, clock()
        )
        assert record is not None
        return {
            "ok": True,
            "result": {
                "id": gate_id,
                "operation_id": record.operation_id,
                "decision": record.decision.value,
                "state": record.state.value,
                "note": record.decision_note,
            },
        }

    monkeypatch.setattr(human_gate_router, "approve_gate", approve_bridge)
    app = FastAPI()
    app.include_router(human_gate_router.router)
    transport = httpx.ASGITransport(app=app)
    create_payload = ApprovalOperationCreate(
        request_id="request-hmac-chain",
        requested_by="caller:untrusted",
        permission_snapshot={"roles": ["admin"], "scopes": ["anything"]},
        handler="system.noop-audit",
        summary="No-side-effect chain fixture",
        payload={"value": 1},
        target={"kind": "fixture"},
        idempotency_strategy=IdempotencyStrategy.TRANSACTIONAL,
        expires_in_seconds=120,
    )
    created = await service.create(create_payload)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        gate_id = created.gate_id
        approve_path = f"/api/v1/mcp/human-gates/{gate_id}/approve"
        approve_body = b'{"note":"approved in UI"}'
        approved_response = await client.post(
            approve_path,
            content=approve_body,
            headers=service_headers(secret, "POST", approve_path, approve_body),
        )
    assert approved_response.status_code == 200

    worker = ApprovalOperationWorker(repository, now=clock)
    completed = await worker.run_once()
    assert completed is not None and completed.state is ApprovalOperationState.SUCCEEDED
    assert completed.requested_by == "service:knowledge-engine"
    assert completed.decision_actor == "identity:admin@example.com"
    actions = [event["action"] for event in repository.audit_events]
    assert actions == ["created", "approved", "claimed", "effect_started", "succeeded"]
    assert all("secret" not in json.dumps(event, default=str).lower() for event in repository.audit_events)
