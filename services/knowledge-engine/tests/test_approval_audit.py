from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastmcp import FastMCP


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.mcp import approval_audit  # noqa: E402
from app.mcp.approval_audit import get_current_tool_call_id  # noqa: E402
from app.mcp.audit import TOOL_REGISTRY, tool_with_audit  # noqa: E402
from app.schemas.approval_operations import (  # noqa: E402
    ApprovalDecision,
    ApprovalOperationState,
)
from app.services.approval_operations import (  # noqa: E402
    ApprovalOperationService,
    InMemoryApprovalRepository,
    StaticApprovalAuthorizationVerifier,
    knowledge_engine_requester_principal,
)
from app.workers.approval_operations import (  # noqa: E402
    ApprovalOperationWorker,
    HANDLERS,
)


class FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, statement: str, *args: object) -> str:
        self.calls.append((statement, args))
        return "UPDATE 1"


def test_all_real_gated_tools_use_the_dedicated_decorator() -> None:
    tools_root = SERVICE_ROOT / "app" / "mcp" / "tools"
    dedicated: list[tuple[str, str]] = []
    legacy_gated: list[tuple[str, str]] = []
    for path in sorted(tools_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                name = getattr(decorator.func, "id", "")
                if name == "approval_tool_with_audit":
                    dedicated.append((path.name, node.name))
                if name == "tool_with_audit" and any(
                    keyword.arg == "require_approval"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in decorator.keywords
                ):
                    legacy_gated.append((path.name, node.name))
    assert legacy_gated == []
    assert len(dedicated) == 12


def test_registry_contract_matches_normal_audit_entries() -> None:
    mcp = FastMCP("approval-registry-fixture")

    @tool_with_audit(mcp)
    async def fixture_normal_registry() -> dict:
        return {"ok": True}

    @approval_audit.approval_tool_with_audit(mcp)
    async def fixture_approval_registry() -> dict:
        return {"ok": True}

    try:
        normal = TOOL_REGISTRY["fixture_normal_registry"]
        approved = TOOL_REGISTRY["fixture_approval_registry"]
        assert set(approved) == {"fn", "require_approval", "timeout_seconds"}
        assert set(approved).issubset(normal)
        assert normal["require_approval"] is False
        assert approved["require_approval"] is True
        assert callable(approved["fn"])
    finally:
        HANDLERS.pop("mcp.fixture_approval_registry", None)
        TOOL_REGISTRY.pop("fixture_normal_registry", None)
        TOOL_REGISTRY.pop("fixture_approval_registry", None)


@pytest.mark.asyncio
async def test_rejects_raw_secret_before_any_unsafe_audit_or_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool()
    monkeypatch.setattr(approval_audit, "get_pool", lambda: pool)
    summaries: list[dict] = []
    body_calls: list[str] = []
    raw_secret = "DO-NOT-PERSIST-this-raw-secret-value"

    @approval_audit.approval_tool_with_audit(
        FastMCP("approval-input-fixture"),
        summary_fn=lambda args: summaries.append(args) or "should not render",
    )
    async def fixture_reject_raw_secret(api_token: str) -> dict:
        body_calls.append(api_token)
        return {"ok": True}

    try:
        result = await fixture_reject_raw_secret(raw_secret)
        assert result == {
            "ok": False,
            "error": "raw_secret_forbidden",
            "retryable": False,
        }
        assert summaries == []
        assert body_calls == []
        assert len(pool.calls) == 1
        assert raw_secret not in repr(pool.calls)
        assert json.loads(str(pool.calls[0][1][2])) == {
            "input_rejected": True,
            "code": "raw_secret_forbidden",
        }
    finally:
        HANDLERS.pop("mcp.fixture_reject_raw_secret", None)
        TOOL_REGISTRY.pop("fixture_reject_raw_secret", None)


@pytest.mark.asyncio
async def test_async_pending_resumes_once_with_same_frozen_payload_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_path = tmp_path / "approval-secret"
    secret_path.write_bytes(b"approval-audit-fixture-secret-at-least-thirty-two-bytes")
    monkeypatch.setenv("OMNI_APPROVAL_SERVICE_SECRET_FILE", str(secret_path))
    monkeypatch.delenv("OMNI_LEGACY_BLOCKING_APPROVAL", raising=False)
    requester = knowledge_engine_requester_principal()
    assert requester is not None
    repository = InMemoryApprovalRepository()
    operation_service = ApprovalOperationService(
        repository,
        principal=requester,
        now=lambda: datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
    )
    pool = FakePool()
    monkeypatch.setattr(approval_audit, "get_pool", lambda: pool)
    monkeypatch.setattr(
        approval_audit,
        "ApprovalOperationService",
        lambda **_kwargs: operation_service,
    )
    body_calls: list[int] = []
    body_contexts: list[str | None] = []

    @approval_audit.approval_tool_with_audit(FastMCP("approval-resume-fixture"))
    async def fixture_async_approval_effect(value: int) -> dict:
        body_calls.append(value)
        body_contexts.append(get_current_tool_call_id())
        return {"ok": True, "value": value * 2}

    try:
        assert get_current_tool_call_id() is None
        queued = await fixture_async_approval_effect(7)
        assert queued["status"] == "pending_approval"
        assert body_calls == []
        record = await repository.get(queued["operation_id"])
        assert record is not None
        assert (
            json.loads(str(pool.calls[0][1][2]))
            == record.redacted_payload
            == {"value": 7}
        )
        decided = await repository.decide(
            record.gate_id,
            ApprovalDecision.APPROVED,
            "approved",
            "identity:admin@example.com",
            datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
        )
        assert decided is not None
        worker = ApprovalOperationWorker(
            repository,
            handlers={record.handler: HANDLERS[record.handler]},
            authorization_verifier=StaticApprovalAuthorizationVerifier(requester),
            now=lambda: datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
        )
        completed = await worker.run_once()
        assert completed is not None
        assert completed.state is ApprovalOperationState.SUCCEEDED
        assert completed.result == {"ok": True, "value": 14}
        assert await worker.run_once() is None
        assert body_calls == [7]
        assert body_contexts == [record.trace_id]
        assert get_current_tool_call_id() is None
    finally:
        HANDLERS.pop("mcp.fixture_async_approval_effect", None)
        TOOL_REGISTRY.pop("fixture_async_approval_effect", None)


@pytest.mark.asyncio
async def test_legacy_blocking_compatibility_binds_and_resets_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool()
    monkeypatch.setattr(approval_audit, "get_pool", lambda: pool)
    monkeypatch.setenv("OMNI_LEGACY_BLOCKING_APPROVAL", "true")

    async def approve(**_kwargs):
        return {"decision": "approved", "decision_note": "fixture"}

    monkeypatch.setattr(approval_audit.human_gate, "request_approval", approve)
    observed: list[str | None] = []

    @approval_audit.approval_tool_with_audit(FastMCP("legacy-approval-fixture"))
    async def fixture_legacy_approval() -> dict:
        observed.append(get_current_tool_call_id())
        raise RuntimeError("must not escape")

    try:
        result = await fixture_legacy_approval()
        assert result == {"ok": False, "error": "approved_effect_failed"}
        inserted_id = str(pool.calls[0][1][0])
        assert observed == [inserted_id]
        assert get_current_tool_call_id() is None
        assert "must not escape" not in repr(pool.calls)
    finally:
        HANDLERS.pop("mcp.fixture_legacy_approval", None)
        TOOL_REGISTRY.pop("fixture_legacy_approval", None)


@pytest.mark.asyncio
async def test_legacy_compatibility_never_persists_secret_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool()
    monkeypatch.setattr(approval_audit, "get_pool", lambda: pool)
    monkeypatch.setenv("OMNI_LEGACY_BLOCKING_APPROVAL", "true")

    async def approve(**_kwargs):
        return {"decision": "approved", "decision_note": "fixture"}

    monkeypatch.setattr(approval_audit.human_gate, "request_approval", approve)
    result_secret = "provider-result-secret-must-not-persist"

    @approval_audit.approval_tool_with_audit(FastMCP("legacy-result-fixture"))
    async def fixture_legacy_secret_result() -> dict:
        return {"ok": True, "api_token": result_secret}

    try:
        result = await fixture_legacy_secret_result()
        assert result["api_token"] == result_secret
        assert result_secret not in repr(pool.calls)
        persisted = json.loads(str(pool.calls[-1][1][0]))
        assert persisted["api_token"] == {"$redacted": True}
    finally:
        HANDLERS.pop("mcp.fixture_legacy_secret_result", None)
        TOOL_REGISTRY.pop("fixture_legacy_secret_result", None)
