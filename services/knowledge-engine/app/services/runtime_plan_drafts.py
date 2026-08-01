"""Idempotent S9 repair-plan drafts; drafts never execute a repair."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Protocol

from app.schemas.runtime_trace import RuntimePlanDraft, RuntimePlanDraftCreate


def _draft_id(payload: RuntimePlanDraftCreate) -> str:
    raw = f"{payload.finding_fingerprint}\0{payload.base_snapshot_id}".encode()
    return "plan:" + hashlib.sha256(raw).hexdigest()[:32]


def _title(payload: RuntimePlanDraftCreate) -> str:
    return f"修复运行雷达发现 {payload.finding_fingerprint[7:19]}"


class RuntimePlanDraftStore(Protocol):
    async def create(self, payload: RuntimePlanDraftCreate) -> RuntimePlanDraft: ...


class DatabaseRuntimePlanDraftStore:
    async def create(self, payload: RuntimePlanDraftCreate) -> RuntimePlanDraft:
        from app.database import get_pool

        draft_id = _draft_id(payload)
        async with get_pool().acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                "SELECT * FROM mcp.runtime_plan_drafts WHERE finding_fingerprint=$1 AND base_snapshot_id=$2 FOR UPDATE",
                payload.finding_fingerprint,
                payload.base_snapshot_id,
            )
            if existing is not None:
                if payload.expected_version is not None and int(existing["version"]) != payload.expected_version:
                    raise ValueError("runtime_plan_version_conflict")
                return _from_row(existing, reused=True)
            if payload.expected_version not in (None, 1):
                raise ValueError("runtime_plan_version_conflict")
            row = await conn.fetchrow(
                """INSERT INTO mcp.runtime_plan_drafts
                   (draft_id,finding_fingerprint,trace_id,base_snapshot_id,title)
                   VALUES($1,$2,$3,$4,$5) RETURNING *""",
                draft_id,
                payload.finding_fingerprint,
                payload.trace_id,
                payload.base_snapshot_id,
                _title(payload),
            )
        return _from_row(row, reused=False)


def _from_row(row, *, reused: bool) -> RuntimePlanDraft:
    return RuntimePlanDraft(
        draft_id=row["draft_id"], finding_fingerprint=row["finding_fingerprint"],
        trace_id=row["trace_id"], base_snapshot_id=row["base_snapshot_id"], title=row["title"],
        status=row["status"], version=int(row["version"]), created_at=row["created_at"],
        updated_at=row["updated_at"], reused=reused,
    )


class MemoryRuntimePlanDraftStore:
    def __init__(self) -> None:
        self._drafts: dict[tuple[str, str], RuntimePlanDraft] = {}

    async def create(self, payload: RuntimePlanDraftCreate) -> RuntimePlanDraft:
        key = (payload.finding_fingerprint, payload.base_snapshot_id)
        existing = self._drafts.get(key)
        if existing is not None:
            if payload.expected_version is not None and payload.expected_version != existing.version:
                raise ValueError("runtime_plan_version_conflict")
            return existing.model_copy(update={"reused": True})
        if payload.expected_version not in (None, 1):
            raise ValueError("runtime_plan_version_conflict")
        now = datetime.now(timezone.utc)
        draft = RuntimePlanDraft(
            draft_id=_draft_id(payload), finding_fingerprint=payload.finding_fingerprint,
            trace_id=payload.trace_id, base_snapshot_id=payload.base_snapshot_id, title=_title(payload),
            version=1, created_at=now, updated_at=now,
        )
        self._drafts[key] = draft
        return draft
