from __future__ import annotations

from typing import Any

import pytest

from app.services import video_production_workflow as workflow
from app.services.video_production_contract import P0_CONTRACT_VERSION


ORDER_ID = "00000000-0000-0000-0000-000000000071"
PROMPT_SOURCE_ID = "00000000-0000-0000-0000-000000000072"


class _AsyncContext:
    def __init__(self, value: Any):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _ApprovalConn:
    def __init__(self, vector_report: dict[str, Any]):
        self.vector_report = vector_report
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self):
        return _AsyncContext(None)

    async def fetchrow(self, sql: str, *args: Any):
        if "FROM pipeline.production_prompt_sources" in sql:
            return {
                "id": PROMPT_SOURCE_ID,
                "prompt_source": {"compiled": {"final_prompt": "frozen prompt"}},
                "prompt_source_hash": "prompt-hash",
                "reference_manifest": {"items": []},
                "requested_provider": "test-provider",
                "requested_model": "test-model",
            }
        if "FROM pipeline.production_vector_match_reports" in sql:
            return self.vector_report
        raise AssertionError(f"unexpected query: {sql}")

    async def execute(self, sql: str, *args: Any):
        self.execute_calls.append((sql, args))


class _ApprovalPool:
    def __init__(self, conn: _ApprovalConn):
        self.conn = conn

    def acquire(self):
        return _AsyncContext(self.conn)


def _v4_context() -> dict[str, Any]:
    return {
        "order": {
            "id": ORDER_ID,
            "contract_version": P0_CONTRACT_VERSION,
            "status": "prompt_ready",
        },
        "truth": {"snapshot": {}},
        "spec": {"spec": {"duration_seconds": 12}},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("report_status", "audience_source_kind", "report", "expected_error"),
    [
        (
            "unscored",
            "portrait",
            {"formal_pre_video_vector_gate": {"pass": True}},
            "execution_vector_match_v4_required",
        ),
        (
            "scored",
            "record_fallback",
            {"formal_pre_video_vector_gate": {"pass": True}},
            "execution_vector_match_v4_required",
        ),
        (
            "scored",
            "portrait",
            {
                "formal_pre_video_vector_gate": {
                    "pass": False,
                    "failed_checks": ["dimension_fact:pain_conflict"],
                }
            },
            "formal_pre_video_vector_gate_failed",
        ),
    ],
)
async def test_v4_approval_refuses_nonqualifying_vector_pre_match(
    monkeypatch,
    report_status: str,
    audience_source_kind: str,
    report: dict[str, Any],
    expected_error: str,
):
    """No incomplete v4 pre-match may transition the order to a human gate."""

    conn = _ApprovalConn(
        {
            "id": "00000000-0000-0000-0000-000000000073",
            "report_status": report_status,
            "audience_source_kind": audience_source_kind,
            "report": report,
        }
    )

    async def fake_load_context(_conn, _production_order_id: str, *, lock: bool = False):
        del lock
        return _v4_context()

    async def already_assessed(*, production_order_id: str):
        assert production_order_id == ORDER_ID
        return {"ok": True, "report": {"status": "scored"}}

    monkeypatch.setattr(workflow, "get_pool", lambda: _ApprovalPool(conn))
    monkeypatch.setattr(workflow, "_load_context", fake_load_context)
    monkeypatch.setattr(
        workflow,
        "_frozen_strong_lineage_planting_context",
        lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        workflow,
        "assess_frozen_execution_vector_match",
        already_assessed,
    )

    result = await workflow.request_generation_approval(
        production_order_id=ORDER_ID,
    )

    assert result["ok"] is False
    assert result["error"] == expected_error
    assert result["first_blocker"] == expected_error
    assert conn.execute_calls == []
