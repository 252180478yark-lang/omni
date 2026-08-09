"""Append-only Workbench context resolution with compare-and-swap rebind."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Protocol

from app.schemas.workbench_contexts import (
    WorkbenchContextInput,
    WorkbenchContextResolveRequest,
    WorkbenchContextResult,
)
from app.schemas.workbench_foundation import WorkbenchContextSnapshot


SNAPSHOT_COLUMNS = (
    "snapshot_id",
    "context_ref",
    "revision",
    "workspace_ref",
    "shop_ref",
    "sku_ref",
    "project_ref",
    "environment_ref",
    "task_ref",
    "evidence_refs",
    "origin_surface_ref",
    "permission_scope_hash",
    "availability",
    "rebind_reason",
    "created_at",
)
SNAPSHOT_PROJECTION = ", ".join(SNAPSHOT_COLUMNS)


class WorkbenchContextConflict(ValueError):
    pass


class WorkbenchContextStore(Protocol):
    async def resolve(
        self,
        payload: WorkbenchContextResolveRequest,
        *,
        permission_scope_hash: str,
    ) -> WorkbenchContextResult: ...


def local_owner_permission_scope_hash() -> str:
    canonical = json.dumps(
        {"actor": "local-owner", "scopes": ["workbench:read", "workbench:write"]},
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _context_values(value: WorkbenchContextInput) -> dict:
    return value.model_dump(mode="json")


def _matches(
    snapshot: WorkbenchContextSnapshot,
    context: WorkbenchContextInput,
    permission_scope_hash: str,
) -> bool:
    values = _context_values(context)
    return all(
        getattr(snapshot, field) == values[field]
        for field in (
            "context_ref",
            "workspace_ref",
            "shop_ref",
            "sku_ref",
            "project_ref",
            "environment_ref",
            "task_ref",
            "evidence_refs",
            "origin_surface_ref",
            "availability",
            "rebind_reason",
        )
    ) and snapshot.permission_scope_hash == permission_scope_hash


def _snapshot_id(
    context: WorkbenchContextInput,
    revision: int,
    permission_scope_hash: str,
) -> str:
    canonical = json.dumps(
        {
            "context": _context_values(context),
            "revision": revision,
            "permission_scope_hash": permission_scope_hash,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return "context:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _next_snapshot(
    context: WorkbenchContextInput,
    revision: int,
    permission_scope_hash: str,
    *,
    created_at: datetime | None = None,
) -> WorkbenchContextSnapshot:
    return WorkbenchContextSnapshot(
        schema_version=1,
        snapshot_id=_snapshot_id(context, revision, permission_scope_hash),
        revision=revision,
        permission_scope_hash=permission_scope_hash,
        created_at=created_at or datetime.now(timezone.utc),
        **_context_values(context),
    )


def _resolve_against_current(
    current: WorkbenchContextSnapshot | None,
    payload: WorkbenchContextResolveRequest,
    permission_scope_hash: str,
) -> tuple[WorkbenchContextSnapshot, bool]:
    expected_id = payload.expected_snapshot_id
    expected_revision = payload.expected_revision
    if current is None:
        if expected_id is not None:
            raise WorkbenchContextConflict("context_rebind_conflict")
        return _next_snapshot(payload.context, 1, permission_scope_hash), False

    if expected_id is None:
        if _matches(current, payload.context, permission_scope_hash):
            return current, True
        raise WorkbenchContextConflict("context_expected_pair_required")

    assert expected_revision is not None
    if current.snapshot_id == expected_id and current.revision == expected_revision:
        if _matches(current, payload.context, permission_scope_hash):
            return current, True
        return _next_snapshot(
            payload.context,
            expected_revision + 1,
            permission_scope_hash,
        ), False

    # A response may be lost after the append succeeds. Reusing the exact next
    # row makes the retry idempotent without weakening compare-and-swap.
    if (
        current.revision == expected_revision + 1
        and _matches(current, payload.context, permission_scope_hash)
    ):
        return current, True
    raise WorkbenchContextConflict("context_rebind_conflict")


def _from_row(row) -> WorkbenchContextSnapshot:
    values = dict(row)
    values["schema_version"] = 1
    values["evidence_refs"] = list(values.get("evidence_refs") or [])
    return WorkbenchContextSnapshot(**values)


class DatabaseWorkbenchContextStore:
    async def resolve(
        self,
        payload: WorkbenchContextResolveRequest,
        *,
        permission_scope_hash: str,
    ) -> WorkbenchContextResult:
        from app.database import get_pool

        async with get_pool().acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                payload.context.context_ref,
            )
            row = await conn.fetchrow(
                f"SELECT {SNAPSHOT_PROJECTION} "
                "FROM mcp.workbench_context_snapshots "
                "WHERE context_ref=$1 ORDER BY revision DESC LIMIT 1",
                payload.context.context_ref,
            )
            snapshot, reused = _resolve_against_current(
                _from_row(row) if row else None,
                payload,
                permission_scope_hash,
            )
            if reused:
                return WorkbenchContextResult(snapshot=snapshot, reused=True)
            inserted = await conn.fetchrow(
                f"""INSERT INTO mcp.workbench_context_snapshots
                    (snapshot_id,context_ref,revision,workspace_ref,shop_ref,sku_ref,
                     project_ref,environment_ref,task_ref,evidence_refs,origin_surface_ref,
                     permission_scope_hash,availability,rebind_reason,created_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14,$15)
                    RETURNING {SNAPSHOT_PROJECTION}""",
                snapshot.snapshot_id,
                snapshot.context_ref,
                snapshot.revision,
                snapshot.workspace_ref,
                snapshot.shop_ref,
                snapshot.sku_ref,
                snapshot.project_ref,
                snapshot.environment_ref,
                snapshot.task_ref,
                json.dumps(snapshot.evidence_refs),
                snapshot.origin_surface_ref,
                snapshot.permission_scope_hash,
                snapshot.availability,
                snapshot.rebind_reason,
                snapshot.created_at,
            )
        return WorkbenchContextResult(snapshot=_from_row(inserted), reused=False)


class MemoryWorkbenchContextStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, list[WorkbenchContextSnapshot]] = {}

    async def resolve(
        self,
        payload: WorkbenchContextResolveRequest,
        *,
        permission_scope_hash: str,
    ) -> WorkbenchContextResult:
        records = self.snapshots.setdefault(payload.context.context_ref, [])
        snapshot, reused = _resolve_against_current(
            records[-1] if records else None,
            payload,
            permission_scope_hash,
        )
        if not reused:
            records.append(snapshot)
        return WorkbenchContextResult(snapshot=snapshot, reused=reused)


__all__ = [
    "DatabaseWorkbenchContextStore",
    "MemoryWorkbenchContextStore",
    "WorkbenchContextConflict",
    "WorkbenchContextStore",
    "local_owner_permission_scope_hash",
]
