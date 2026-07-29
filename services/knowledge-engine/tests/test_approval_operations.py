from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.approval_operations import (
    get_approval_operation_service,
    get_approval_principal,
    router,
)
from app.schemas.approval_operations import (
    ApprovalDecision,
    ApprovalOperationCreate,
    ApprovalOperationState,
    IdempotencyStrategy,
)
from app.services.approval_operations import (
    ApprovalOperationException,
    ApprovalOperationService,
    ApprovalPrincipal,
    InMemoryApprovalRepository,
    PostgresApprovalRepository,
    canonical_hash,
)


OWNER = ApprovalPrincipal(
    "user:owner",
    roles=frozenset({"owner"}),
    scopes=frozenset({"approval:request", "approval:execute"}),
)
OTHER = ApprovalPrincipal("user:other", scopes=frozenset({"approval:request"}))


class Clock:
    def __init__(self):
        self.value = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds: int):
        self.value += timedelta(seconds=seconds)


def request(**changes) -> ApprovalOperationCreate:
    values = {
        "request_id": "request-0001",
        "requested_by": "user:owner",
        "permission_snapshot": {"roles": ["owner"], "scopes": ["external:write"]},
        "trace_id": "trace-1",
        "handler": "test.safe-effect",
        "summary": "Write one external record after approval",
        "payload": {
            "sku": "SKU-1",
            "api_token": {"$secret_ref": "vault/provider-token"},
            "nested": {"password": {"$secret_ref": "vault/provider-password"}},
        },
        "target": {"provider": "fixture"},
        "idempotency_strategy": IdempotencyStrategy.PROVIDER_IDEMPOTENCY,
        "expires_in_seconds": 60,
    }
    values.update(changes)
    return ApprovalOperationCreate(**values)


@pytest.mark.asyncio
async def test_create_returns_pending_immediately_and_persists_only_redacted_payload():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    service = ApprovalOperationService(repository, now=clock, principal=OWNER)

    accepted = await service.create(request())
    record = await repository.get(accepted.operation_id)

    assert accepted.state is ApprovalOperationState.PENDING
    assert accepted.status_url.endswith(accepted.operation_id)
    assert record is not None
    persisted = str(record.redacted_payload)
    assert "secret-value" not in persisted
    assert record.redacted_payload["api_token"] == {"$secret_ref": "vault/provider-token"}
    assert record.payload_hash == canonical_hash(record.redacted_payload)
    assert len(record.permission_snapshot_hash) == 64


@pytest.mark.asyncio
async def test_notification_failure_does_not_rollback_or_change_accepted_response():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    notifications = 0

    async def unavailable(*_args):
        nonlocal notifications
        notifications += 1
        raise ConnectionError("notification transport unavailable")

    service = ApprovalOperationService(
        repository, now=clock, principal=OWNER, notify_gate=unavailable
    )
    accepted = await service.create(request())
    duplicate = await service.create(request())
    assert accepted.state is ApprovalOperationState.PENDING
    assert duplicate.operation_id == accepted.operation_id
    assert duplicate.duplicate is True
    assert notifications == 1
    assert len(repository.operations) == 1
    assert [event["action"] for event in repository.audit_events] == [
        "created",
        "notification_failed",
    ]


@pytest.mark.asyncio
async def test_request_id_is_idempotent_but_conflicting_payload_is_rejected():
    repository = InMemoryApprovalRepository()
    service = ApprovalOperationService(repository, now=Clock(), principal=OWNER)
    first = await service.create(request())
    duplicate = await service.create(request())
    assert duplicate.operation_id == first.operation_id
    assert duplicate.duplicate is True

    with pytest.raises(ApprovalOperationException) as caught:
        await service.create(request(payload={"sku": "different"}))
    assert caught.value.code == "request_id_conflict"
    assert caught.value.status == 409

    claimed_elevation = await service.create(
        request(permission_snapshot={"roles": ["admin"], "scopes": ["approval:decide"]})
    )
    assert claimed_elevation.duplicate is True
    assert claimed_elevation.permission_snapshot_hash == OWNER.snapshot_hash

    for changed in (
        {"trace_id": "trace-2"},
        {"summary": "different audit meaning"},
        {"expires_in_seconds": 120},
    ):
        with pytest.raises(ApprovalOperationException) as intent_conflict:
            await service.create(request(**changed))
        assert intent_conflict.value.code == "request_id_conflict"


@pytest.mark.asyncio
async def test_concurrent_same_request_id_creates_one_operation():
    repository = InMemoryApprovalRepository()
    service = ApprovalOperationService(repository, now=Clock(), principal=OWNER)
    results = await asyncio.gather(*(service.create(request()) for _ in range(12)))
    assert len({item.operation_id for item in results}) == 1
    assert sum(not item.duplicate for item in results) == 1
    source = (SERVICE_ROOT / "app" / "services" / "approval_operations.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (request_id) DO NOTHING" in source


@pytest.mark.asyncio
async def test_raw_secret_is_rejected_but_structured_secret_ref_is_frozen():
    repository = InMemoryApprovalRepository()
    service = ApprovalOperationService(repository, now=Clock(), principal=OWNER)
    with pytest.raises(ApprovalOperationException) as caught:
        await service.create(request(payload={"api_token": "never-persist-this"}))
    assert caught.value.code == "raw_secret_forbidden"
    assert repository.operations == {}


@pytest.mark.asyncio
async def test_input_depth_and_size_are_typed_422_before_freezing():
    repository = InMemoryApprovalRepository()
    service = ApprovalOperationService(repository, now=Clock(), principal=OWNER)
    deep: object = "leaf"
    for _ in range(40):
        deep = [deep]

    for payload, expected_code in (
        ({"deep": deep}, "persisted_value_too_deep"),
        ({"oversize": "x" * (256 * 1024 + 1)}, "persisted_value_too_large"),
    ):
        with pytest.raises(ApprovalOperationException) as caught:
            await service.create(request(payload=payload))
        assert caught.value.code == expected_code
        assert caught.value.status == 422

    assert repository.operations == {}


@pytest.mark.asyncio
async def test_duplicate_gate_decision_returns_original_and_never_overwrites():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    service = ApprovalOperationService(repository, now=clock, principal=OWNER)
    accepted = await service.create(request())

    approved = await repository.decide(
        accepted.gate_id, ApprovalDecision.APPROVED, "ok", OWNER.principal_id, clock()
    )
    repeated = await repository.decide(
        accepted.gate_id, ApprovalDecision.REJECTED, "late reject", OWNER.principal_id, clock()
    )
    assert approved is not None and repeated is not None
    assert repeated.decision is ApprovalDecision.APPROVED
    assert repeated.decision_note == "ok"


@pytest.mark.asyncio
async def test_pending_read_settles_expiry_and_revoke_is_idempotent():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    service = ApprovalOperationService(repository, now=clock, principal=OWNER)
    expiring = await service.create(request())
    clock.advance(61)
    status = await service.status(expiring.operation_id)
    assert status.state is ApprovalOperationState.EXPIRED
    assert status.decision is ApprovalDecision.EXPIRED

    second = await service.create(request(request_id="request-0002"))
    revoked = await service.revoke(second.operation_id, "cancel")
    repeated = await service.revoke(second.operation_id, "different note")
    assert revoked.state is ApprovalOperationState.REVOKED
    assert repeated.decision_note == "cancel"


@pytest.mark.asyncio
async def test_api_returns_202_location_and_typed_status_without_running_effect():
    repository = InMemoryApprovalRepository()
    service = ApprovalOperationService(repository, now=Clock(), principal=OWNER)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_approval_operation_service] = lambda: service
    app.dependency_overrides[get_approval_principal] = lambda: OWNER
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/approval-operations",
            json=request().model_dump(mode="json"),
        )
        status = await client.get(response.json()["status_url"])

    assert response.status_code == 202
    assert response.headers["location"] == response.json()["status_url"]
    assert status.status_code == 200
    assert status.json()["state"] == "pending"
    assert status.json()["effect_started_at"] is None


@pytest.mark.asyncio
async def test_inbox_bridge_uses_operation_decision_and_preserves_legacy_fallback(monkeypatch):
    from app.services import inbox_service

    repository = InMemoryApprovalRepository()
    clock = Clock()
    service = ApprovalOperationService(repository, now=clock, principal=OWNER)
    accepted = await service.create(request())
    await repository.decide(
        accepted.gate_id, ApprovalDecision.APPROVED, "approved", OWNER.principal_id, clock()
    )
    operation = await repository.get(accepted.operation_id)
    assert operation is not None

    async def resolved(_gate_id):
        return {"ok": True, "id": accepted.gate_id}

    async def operation_decision(*_args, **_kwargs):
        return operation

    monkeypatch.setattr(inbox_service, "_resolve_gate_id", resolved)
    monkeypatch.setattr(inbox_service, "decide_gate_if_operation", operation_decision)
    bridged = await inbox_service.approve_gate(
        accepted.gate_id, "duplicate", actor_id=OWNER.principal_id
    )
    assert bridged["ok"] is True
    assert bridged["result"]["operation_id"] == accepted.operation_id
    assert bridged["result"]["decision"] == "approved"
    rejected_after_approve = await inbox_service.reject_gate(
        accepted.gate_id, "late reject", actor_id=OWNER.principal_id
    )
    assert rejected_after_approve["ok"] is True
    assert rejected_after_approve["result"]["decision"] == "approved"

    async def no_operation(*_args, **_kwargs):
        return None

    async def legacy_approve(_gate_id, _note, **_kwargs):
        return True

    async def legacy_reject(_gate_id, _note, **_kwargs):
        return True

    monkeypatch.setattr(inbox_service, "decide_gate_if_operation", no_operation)
    monkeypatch.setattr(inbox_service.human_gate, "approve", legacy_approve)
    legacy = await inbox_service.approve_gate(
        accepted.gate_id, "legacy", actor_id=OWNER.principal_id
    )
    assert legacy == {
        "ok": True,
        "result": {"id": accepted.gate_id, "decision": "approved", "note": "legacy"},
    }
    monkeypatch.setattr(inbox_service.human_gate, "reject", legacy_reject)
    legacy_rejected = await inbox_service.reject_gate(
        accepted.gate_id, "legacy reject", actor_id=OWNER.principal_id
    )
    assert legacy_rejected["result"]["decision"] == "rejected"


@pytest.mark.asyncio
async def test_legacy_gate_decision_falls_back_when_098_decided_by_is_missing(monkeypatch):
    from app.mcp import human_gate

    class UndefinedColumn(Exception):
        sqlstate = "42703"

    class FakePool:
        def __init__(self):
            self.calls = []

        async def fetchrow(self, sql, *args):
            self.calls.append((sql, args))
            if len(self.calls) == 1:
                raise UndefinedColumn()
            return {"id": args[-1]}

    pool = FakePool()
    monkeypatch.setattr(human_gate, "get_pool", lambda: pool)
    gate_id = "00000000-0000-0000-0000-000000000123"
    assert await human_gate._settle_legacy_gate(
        gate_id, "approved", "legacy", "identity:admin@example.com"
    ) is True
    assert "decided_by" in pool.calls[0][0]
    assert "decided_by" not in pool.calls[1][0]


@pytest.mark.asyncio
async def test_inbox_missing_098_uses_read_only_legacy_fallback(monkeypatch):
    from app.services import inbox_service

    class MissingTable(Exception):
        sqlstate = "42P01"

    class FakePool:
        async def fetch(self, _sql):
            return []

    async def missing_schema():
        raise MissingTable()

    monkeypatch.setattr(inbox_service, "get_pool", lambda: FakePool())
    monkeypatch.setattr(inbox_service, "settle_expired_operations", missing_schema)
    assert await inbox_service.list_pending() == {"data": [], "total": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["primary", "fallback"])
async def test_inbox_runtime_and_fallback_failures_are_typed_503(monkeypatch, stage):
    from app.services import inbox_service

    class MissingTable(Exception):
        sqlstate = "42P01"

    class PermissionDenied(Exception):
        sqlstate = "42501"

    class FakePool:
        async def fetch(self, _sql):
            raise PermissionDenied()

    async def settle():
        if stage == "fallback":
            raise MissingTable()
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(inbox_service, "get_pool", lambda: FakePool())
    monkeypatch.setattr(inbox_service, "settle_expired_operations", settle)
    with pytest.raises(ApprovalOperationException) as caught:
        await inbox_service.list_pending()
    assert caught.value.code == "approval_inbox_unavailable"
    assert caught.value.status == 503
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_postgres_claim_and_finish_bind_redacted_values_without_name_errors(monkeypatch):
    memory = InMemoryApprovalRepository()
    clock = Clock()
    accepted = await ApprovalOperationService(
        memory, now=clock, principal=OWNER
    ).create(request())
    record = await memory.get(accepted.operation_id)
    assert record is not None

    class FakePool:
        def __init__(self):
            self.calls = []

        async def fetchrow(self, sql, *args):
            self.calls.append((sql, args))
            return {"id": accepted.operation_id}

    pool = FakePool()
    repository = PostgresApprovalRepository(pool)
    monkeypatch.setattr(repository, "get", AsyncMock(return_value=record))
    token = "00000000-0000-0000-0000-000000000001"
    claimed = await repository.claim("worker", token, clock(), clock() + timedelta(seconds=30))
    finished = await repository.finish(
        accepted.operation_id,
        token,
        ApprovalOperationState.SUCCEEDED,
        {"api_token": "result-secret", "value": 1},
        {"password": "error-secret"},
        clock(),
    )
    assert claimed is record
    assert finished is record
    finish_args = pool.calls[-1][1]
    assert "result-secret" not in finish_args[1]
    assert "error-secret" not in finish_args[2]
    assert '"$redacted": true' in finish_args[1]


@pytest.mark.asyncio
async def test_target_url_freezes_exact_safe_query_but_public_status_strips_it():
    repository = InMemoryApprovalRepository()
    service = ApprovalOperationService(repository, now=Clock(), principal=OWNER)
    url = "https://provider.example/orders/run?order_id=42&action=preview#section"
    accepted = await service.create(request(target={"url": url}))
    record = await repository.get(accepted.operation_id)
    status = await service.status(accepted.operation_id)
    assert record is not None and record.target["url"] == url
    assert status.target["url"] == "https://provider.example/orders/run"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@provider.example/run",
        "https://provider.example:bad/run",
        "https://provider.example/run?token=SECRET-TOKEN-123456",
        "https://provider.example/run?X-Amz-Signature=abcdef123456",
    ],
)
async def test_credential_or_invalid_target_urls_are_typed_422_and_never_persisted(url):
    repository = InMemoryApprovalRepository()
    service = ApprovalOperationService(repository, now=Clock(), principal=OWNER)
    with pytest.raises(ApprovalOperationException) as caught:
        await service.create(request(target={"url": url}))
    assert caught.value.status == 422
    assert caught.value.code in {"raw_secret_forbidden", "invalid_target_url"}
    assert repository.operations == {}


@pytest.mark.asyncio
async def test_free_text_is_sanitized_and_identifier_secrets_are_rejected():
    repository = InMemoryApprovalRepository()
    clock = Clock()
    service = ApprovalOperationService(repository, now=clock, principal=OWNER)
    accepted = await service.create(request(summary="run Bearer test-token-SECRET-CANARY-123456"))
    await repository.decide(
        accepted.gate_id,
        ApprovalDecision.REJECTED,
        "reason Bearer test-token-NOTE-CANARY-123456",
        OWNER.principal_id,
        clock(),
    )
    record = await repository.get(accepted.operation_id)
    status = await service.status(accepted.operation_id)
    serialized = json.dumps(status.model_dump(mode="json"), ensure_ascii=False)
    assert record is not None
    assert "SECRET-CANARY" not in record.summary
    assert "NOTE-CANARY" not in str(record.decision_note)
    assert "SECRET-CANARY" not in serialized and "NOTE-CANARY" not in serialized
    with pytest.raises(ValidationError):
        request(trace_id="Bearer test-token-TRACE-CANARY-123456")


@pytest.mark.asyncio
async def test_authentication_and_owner_read_are_fail_closed():
    repository = InMemoryApprovalRepository()
    unauthenticated = ApprovalOperationService(repository, now=Clock())
    with pytest.raises(ApprovalOperationException) as missing:
        await unauthenticated.create(request())
    assert (missing.value.code, missing.value.status) == ("authentication_required", 401)

    owner_service = ApprovalOperationService(repository, now=Clock(), principal=OWNER)
    accepted = await owner_service.create(request())
    with pytest.raises(ApprovalOperationException) as denied:
        await owner_service.status(accepted.operation_id, OTHER)
    assert (denied.value.code, denied.value.status) == ("approval_read_forbidden", 403)


def signed_headers(secret: bytes, method: str, path: str, body: bytes = b"") -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    actor_id = "admin@example.com"
    actor_role = "admin"
    canonical = "\n".join(
        ("frontend", timestamp, nonce, method, path, body_hash, actor_id, actor_role)
    ).encode()
    return {
        "X-Omni-Service-Id": "frontend",
        "X-Omni-Timestamp": timestamp,
        "X-Omni-Nonce": nonce,
        "X-Omni-Body-SHA256": body_hash,
        "X-Omni-Signature": hmac.new(secret, canonical, hashlib.sha256).hexdigest(),
        "X-Omni-Actor-Id": actor_id,
        "X-Omni-Actor-Role": actor_role,
    }


@pytest.mark.asyncio
async def test_service_hmac_is_required_replay_protected_and_cannot_create(tmp_path, monkeypatch):
    secret = b"a-secure-fixture-secret-with-at-least-32-bytes"
    secret_path = tmp_path / "approval-hmac"
    secret_path.write_bytes(secret)
    monkeypatch.setenv("OMNI_APPROVAL_SERVICE_SECRET_FILE", str(secret_path))
    repository = InMemoryApprovalRepository()
    service = ApprovalOperationService(repository, now=Clock())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_approval_operation_service] = lambda: service
    transport = httpx.ASGITransport(app=app)
    payload = request().model_dump(mode="json")
    body = json.dumps(payload, separators=(",", ":")).encode()
    path = "/api/v1/approval-operations"
    headers = {"Content-Type": "application/json", **signed_headers(secret, "POST", path, body)}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.post(path, content=body, headers={"Content-Type": "application/json"})
        forbidden = await client.post(path, content=body, headers=headers)
        replay = await client.post(path, content=body, headers=headers)
    assert anonymous.status_code == 401
    assert forbidden.status_code == 403
    assert replay.status_code == 401
    assert repository.operations == {}
