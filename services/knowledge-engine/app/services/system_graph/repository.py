"""Immutable S7 graph persistence with in-memory and PostgreSQL adapters."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from app.schemas.system_graph import GraphRefreshRecord, GraphSnapshot, SourceResult
from app.services.system_graph.canonical import canonical_json


def refresh_fingerprint(payload: dict[str, Any]) -> str:
    raw = canonical_json(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def refresh_id_for(fingerprint: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"omni:system-graph:{fingerprint}"))


class GraphRepository(Protocol):
    async def begin_refresh(
        self, *, fingerprint: str, actor_id: str, request: dict[str, Any]
    ) -> tuple[GraphRefreshRecord, bool]: ...

    async def mark_refresh_running(self, refresh_id: str) -> GraphRefreshRecord: ...
    async def save_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot: ...
    async def complete_refresh(
        self, refresh_id: str, snapshot: GraphSnapshot
    ) -> GraphRefreshRecord: ...
    async def fail_refresh(
        self, refresh_id: str, *, code: str, retryable: bool
    ) -> GraphRefreshRecord: ...
    async def get_refresh(self, refresh_id: str) -> GraphRefreshRecord: ...
    async def get_snapshot(self, snapshot_id: str) -> GraphSnapshot: ...
    async def latest_snapshot(self) -> GraphSnapshot | None: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _refresh_from_row(row: Any) -> GraphRefreshRecord:
    values = dict(row)
    source_results = values.get("source_results") or []
    error = values.get("error")
    if isinstance(source_results, str):
        source_results = json.loads(source_results)
    if isinstance(error, str):
        error = json.loads(error)
    return GraphRefreshRecord(
        refresh_id=str(values["refresh_id"]),
        request_fingerprint=values["request_fingerprint"],
        state=values["state"],
        snapshot_id=values.get("snapshot_id"),
        source_results=source_results,
        error=error,
        created_at=values["created_at"],
        updated_at=values["updated_at"],
    )


def _snapshot_from_value(value: Any) -> GraphSnapshot:
    if isinstance(value, str):
        return GraphSnapshot.model_validate_json(value)
    return GraphSnapshot.model_validate(value)


class DatabaseGraphRepository:
    async def begin_refresh(
        self, *, fingerprint: str, actor_id: str, request: dict[str, Any]
    ) -> tuple[GraphRefreshRecord, bool]:
        from app.database import get_pool

        refresh_id = refresh_id_for(fingerprint)
        row = await get_pool().fetchrow(
            """INSERT INTO mcp.system_graph_refreshes
                     (refresh_id,request_fingerprint,actor_id,state,request_json)
                   VALUES($1::uuid,$2,$3,'pending',$4::jsonb)
                   ON CONFLICT(request_fingerprint) DO NOTHING RETURNING *""",
            refresh_id,
            fingerprint,
            actor_id,
            json.dumps(request, ensure_ascii=False, sort_keys=True),
        )
        created = row is not None
        if row is None:
            row = await get_pool().fetchrow(
                "SELECT * FROM mcp.system_graph_refreshes WHERE request_fingerprint=$1",
                fingerprint,
            )
        if row is None:
            raise RuntimeError("system_graph_refresh_create_failed")
        return _refresh_from_row(row), created

    async def mark_refresh_running(self, refresh_id: str) -> GraphRefreshRecord:
        from app.database import get_pool

        row = await get_pool().fetchrow(
            """UPDATE mcp.system_graph_refreshes
                  SET state='running',updated_at=NOW()
                WHERE refresh_id=$1::uuid AND state='pending' RETURNING *""",
            refresh_id,
        )
        if row is None:
            return await self.get_refresh(refresh_id)
        return _refresh_from_row(row)

    async def save_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        from app.database import get_pool

        payload = snapshot.model_dump(mode="json")
        content = snapshot.content
        pool = get_pool()
        async with pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                "SELECT snapshot_json FROM mcp.system_graph_snapshots WHERE snapshot_id=$1",
                snapshot.snapshot_id,
            )
            if existing is not None:
                stored = _snapshot_from_value(existing["snapshot_json"])
                if canonical_json(stored.content.model_dump(mode="json")) != canonical_json(
                    snapshot.content.model_dump(mode="json")
                ):
                    raise ValueError("immutable_snapshot_collision")
                return stored
            await conn.execute(
                """INSERT INTO mcp.system_graph_snapshots
                     (snapshot_id,content_hash,commit_sha,definition_revision,feature_ids,
                      source_results,snapshot_json,generated_at)
                   VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8)""",
                snapshot.snapshot_id,
                snapshot.content_hash,
                content.commit,
                content.definition_revision,
                json.dumps(content.feature_ids, ensure_ascii=False),
                json.dumps([item.model_dump(mode="json") for item in content.source_results]),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                snapshot.generated_at_utc,
            )
            if content.nodes:
                await conn.executemany(
                    """INSERT INTO mcp.system_graph_nodes
                         (snapshot_id,node_id,kind,node_key,label,state,attrs,evidence,sources)
                       VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9::jsonb)""",
                    [
                        (
                            snapshot.snapshot_id,
                            node.id,
                            node.kind,
                            node.key,
                            node.label,
                            json.dumps(node.state.model_dump(mode="json")),
                            json.dumps(node.attrs, ensure_ascii=False, sort_keys=True),
                            json.dumps([item.model_dump(mode="json") for item in node.evidence]),
                            json.dumps(node.sources),
                        )
                        for node in content.nodes
                    ],
                )
            if content.edges:
                await conn.executemany(
                    """INSERT INTO mcp.system_graph_edges
                         (snapshot_id,edge_id,relation,source_node_id,target_node_id,confidence,
                          state,attrs,evidence,sources)
                       VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10::jsonb)""",
                    [
                        (
                            snapshot.snapshot_id,
                            edge.id,
                            edge.relation,
                            edge.source,
                            edge.target,
                            edge.confidence,
                            json.dumps(edge.state.model_dump(mode="json")),
                            json.dumps(edge.attrs, ensure_ascii=False, sort_keys=True),
                            json.dumps([item.model_dump(mode="json") for item in edge.evidence]),
                            json.dumps(edge.sources),
                        )
                        for edge in content.edges
                    ],
                )
        return snapshot

    async def complete_refresh(
        self, refresh_id: str, snapshot: GraphSnapshot
    ) -> GraphRefreshRecord:
        from app.database import get_pool

        partial = any(item.status.value != "success" for item in snapshot.content.source_results)
        state = "partial" if partial else "completed"
        row = await get_pool().fetchrow(
            """UPDATE mcp.system_graph_refreshes
                  SET state=$2,snapshot_id=$3,source_results=$4::jsonb,error=NULL,updated_at=NOW()
                WHERE refresh_id=$1::uuid RETURNING *""",
            refresh_id,
            state,
            snapshot.snapshot_id,
            json.dumps([item.model_dump(mode="json") for item in snapshot.content.source_results]),
        )
        if row is None:
            raise KeyError(refresh_id)
        return _refresh_from_row(row)

    async def fail_refresh(
        self, refresh_id: str, *, code: str, retryable: bool
    ) -> GraphRefreshRecord:
        from app.database import get_pool

        row = await get_pool().fetchrow(
            """UPDATE mcp.system_graph_refreshes
                  SET state='failed',error=$2::jsonb,updated_at=NOW()
                WHERE refresh_id=$1::uuid RETURNING *""",
            refresh_id,
            json.dumps({"code": code, "retryable": retryable}),
        )
        if row is None:
            raise KeyError(refresh_id)
        return _refresh_from_row(row)

    async def get_refresh(self, refresh_id: str) -> GraphRefreshRecord:
        from app.database import get_pool

        row = await get_pool().fetchrow(
            "SELECT * FROM mcp.system_graph_refreshes WHERE refresh_id=$1::uuid",
            refresh_id,
        )
        if row is None:
            raise KeyError(refresh_id)
        return _refresh_from_row(row)

    async def get_snapshot(self, snapshot_id: str) -> GraphSnapshot:
        from app.database import get_pool

        row = await get_pool().fetchrow(
            "SELECT snapshot_json FROM mcp.system_graph_snapshots WHERE snapshot_id=$1",
            snapshot_id,
        )
        if row is None:
            raise KeyError(snapshot_id)
        return _snapshot_from_value(row["snapshot_json"])

    async def latest_snapshot(self) -> GraphSnapshot | None:
        from app.database import get_pool

        row = await get_pool().fetchrow(
            """SELECT snapshot_json FROM mcp.system_graph_snapshots
                 ORDER BY generated_at DESC,persisted_at DESC LIMIT 1"""
        )
        return _snapshot_from_value(row["snapshot_json"]) if row else None


class MemoryGraphRepository:
    """Deterministic fixture repository with production-equivalent immutability."""

    def __init__(self) -> None:
        self.refreshes: dict[str, GraphRefreshRecord] = {}
        self.by_fingerprint: dict[str, str] = {}
        self.snapshots: dict[str, GraphSnapshot] = {}

    async def begin_refresh(
        self, *, fingerprint: str, actor_id: str, request: dict[str, Any]
    ) -> tuple[GraphRefreshRecord, bool]:
        del actor_id, request
        existing_id = self.by_fingerprint.get(fingerprint)
        if existing_id:
            return self.refreshes[existing_id], False
        now = _utc_now()
        record = GraphRefreshRecord(
            refresh_id=refresh_id_for(fingerprint),
            request_fingerprint=fingerprint,
            state="pending",
            created_at=now,
            updated_at=now,
        )
        self.refreshes[record.refresh_id] = record
        self.by_fingerprint[fingerprint] = record.refresh_id
        return record, True

    async def mark_refresh_running(self, refresh_id: str) -> GraphRefreshRecord:
        current = await self.get_refresh(refresh_id)
        if current.state == "pending":
            current = current.model_copy(update={"state": "running", "updated_at": _utc_now()})
            self.refreshes[refresh_id] = current
        return current

    async def save_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        current = self.snapshots.get(snapshot.snapshot_id)
        if current and canonical_json(current.content.model_dump(mode="json")) != canonical_json(
            snapshot.content.model_dump(mode="json")
        ):
            raise ValueError("immutable_snapshot_collision")
        self.snapshots[snapshot.snapshot_id] = current or snapshot
        return self.snapshots[snapshot.snapshot_id]

    async def complete_refresh(
        self, refresh_id: str, snapshot: GraphSnapshot
    ) -> GraphRefreshRecord:
        current = await self.get_refresh(refresh_id)
        partial = any(item.status.value != "success" for item in snapshot.content.source_results)
        updated = current.model_copy(
            update={
                "state": "partial" if partial else "completed",
                "snapshot_id": snapshot.snapshot_id,
                "source_results": list(snapshot.content.source_results),
                "updated_at": _utc_now(),
            }
        )
        self.refreshes[refresh_id] = updated
        return updated

    async def fail_refresh(
        self, refresh_id: str, *, code: str, retryable: bool
    ) -> GraphRefreshRecord:
        current = await self.get_refresh(refresh_id)
        updated = current.model_copy(
            update={
                "state": "failed",
                "error": {"code": code, "retryable": retryable},
                "updated_at": _utc_now(),
            }
        )
        self.refreshes[refresh_id] = updated
        return updated

    async def get_refresh(self, refresh_id: str) -> GraphRefreshRecord:
        if refresh_id not in self.refreshes:
            raise KeyError(refresh_id)
        return self.refreshes[refresh_id]

    async def get_snapshot(self, snapshot_id: str) -> GraphSnapshot:
        if snapshot_id not in self.snapshots:
            raise KeyError(snapshot_id)
        return self.snapshots[snapshot_id]

    async def latest_snapshot(self) -> GraphSnapshot | None:
        if not self.snapshots:
            return None
        return max(self.snapshots.values(), key=lambda item: item.generated_at_utc)


def source_results_json(values: list[SourceResult]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in values]
