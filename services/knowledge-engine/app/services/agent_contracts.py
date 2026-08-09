"""Database-backed provider-neutral S10 session and attachment contracts."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Protocol

from app.schemas.runtime_trace import (
    AgentAttachmentInput,
    AgentAttachmentRecord,
    AgentSessionContractRecord,
    ProviderSessionContract,
)


SESSION_COLUMNS = (
    "session_id",
    "runner_provider",
    "runner_session_id",
    "project_dir_hash",
    "model",
    "effort",
    "status",
    "trace_id",
    "created_at",
    "updated_at",
    "contract_version",
    "context_snapshot_id",
    "requested_provider",
    "resolved_runner_mode",
    "fallback_reason_code",
    "provider_accepted_at",
    "parent_session_id",
    "project_handle",
    "project_display_name",
)
SESSION_PROJECTION = ", ".join(SESSION_COLUMNS)
# Compatibility aliases for downstream imports during the additive rollout.
LEGACY_SESSION_COLUMNS = SESSION_COLUMNS
LEGACY_SESSION_PROJECTION = SESSION_PROJECTION


def project_hash(project_dir: str) -> str:
    normalized = project_dir.replace("\\", "/").rstrip("/").casefold()
    return "sha256:" + hashlib.sha256(normalized.encode()).hexdigest()


def canonical_project_hash(payload: ProviderSessionContract) -> str:
    if payload.project_hash is not None:
        return payload.project_hash
    assert payload.project_dir is not None
    return project_hash(payload.project_dir)


class AgentContractStore(Protocol):
    async def upsert_session(self, payload: ProviderSessionContract) -> AgentSessionContractRecord: ...
    async def get_session(self, session_id: str) -> AgentSessionContractRecord | None: ...
    async def record_attachment(self, payload: AgentAttachmentInput) -> AgentAttachmentRecord: ...


def _session_from_row(row) -> AgentSessionContractRecord:
    return AgentSessionContractRecord(**dict(row))


class DatabaseAgentContractStore:
    async def upsert_session(self, payload: ProviderSessionContract) -> AgentSessionContractRecord:
        from app.database import get_pool

        async with get_pool().acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                f"SELECT {SESSION_PROJECTION} "
                "FROM mcp.agent_session_contracts WHERE session_id=$1 FOR UPDATE",
                payload.session_id,
            )
            if existing is not None:
                if existing["runner_session_id"] and payload.runner_session_id and existing["runner_session_id"] != payload.runner_session_id:
                    raise ValueError("agent_runner_identity_conflict")
                if existing["runner_session_id"] and existing["runner_provider"] != payload.runner_provider:
                    raise ValueError("agent_runner_provider_conflict")
            row = await conn.fetchrow(
                f"""INSERT INTO mcp.agent_session_contracts
                   (session_id,runner_provider,runner_session_id,project_dir_hash,model,effort,status,trace_id,
                    contract_version,context_snapshot_id,requested_provider,resolved_runner_mode,fallback_reason_code,
                    provider_accepted_at,parent_session_id,project_handle,project_display_name)
                   VALUES($1,$2,$3,$4,$5,$6,$7,(SELECT trace_id FROM mcp.runtime_executions WHERE trace_id=$8),
                          $9,$10,$11,$12,$13,$14,$15,$16,$17)
                   ON CONFLICT(session_id) DO UPDATE SET
                     runner_provider=EXCLUDED.runner_provider,
                     runner_session_id=COALESCE(EXCLUDED.runner_session_id,mcp.agent_session_contracts.runner_session_id),
                     project_dir_hash=EXCLUDED.project_dir_hash,model=EXCLUDED.model,effort=EXCLUDED.effort,
                     status=EXCLUDED.status,trace_id=COALESCE(EXCLUDED.trace_id,mcp.agent_session_contracts.trace_id),
                     contract_version=COALESCE(EXCLUDED.contract_version,mcp.agent_session_contracts.contract_version),
                     context_snapshot_id=COALESCE(EXCLUDED.context_snapshot_id,mcp.agent_session_contracts.context_snapshot_id),
                     requested_provider=COALESCE(EXCLUDED.requested_provider,mcp.agent_session_contracts.requested_provider),
                     resolved_runner_mode=COALESCE(EXCLUDED.resolved_runner_mode,mcp.agent_session_contracts.resolved_runner_mode),
                     fallback_reason_code=COALESCE(EXCLUDED.fallback_reason_code,mcp.agent_session_contracts.fallback_reason_code),
                     provider_accepted_at=COALESCE(EXCLUDED.provider_accepted_at,mcp.agent_session_contracts.provider_accepted_at),
                     parent_session_id=COALESCE(EXCLUDED.parent_session_id,mcp.agent_session_contracts.parent_session_id),
                     project_handle=COALESCE(EXCLUDED.project_handle,mcp.agent_session_contracts.project_handle),
                     project_display_name=COALESCE(EXCLUDED.project_display_name,mcp.agent_session_contracts.project_display_name),
                     updated_at=NOW()
                   RETURNING {SESSION_PROJECTION}""",
                payload.session_id, payload.runner_provider, payload.runner_session_id, canonical_project_hash(payload),
                payload.model, payload.effort, payload.status, payload.trace_id, "workbench.v1" if payload.project_handle else None,
                payload.context_snapshot_id, payload.requested_provider, payload.resolved_runner_mode,
                payload.fallback_reason_code, payload.provider_accepted_at, payload.parent_session_id,
                payload.project_handle, payload.project_display_name,
            )
        return _session_from_row(row)

    async def get_session(self, session_id: str) -> AgentSessionContractRecord | None:
        from app.database import get_pool
        row = await get_pool().fetchrow(
            f"SELECT {SESSION_PROJECTION} "
            "FROM mcp.agent_session_contracts WHERE session_id=$1",
            session_id,
        )
        return _session_from_row(row) if row else None

    async def record_attachment(self, payload: AgentAttachmentInput) -> AgentAttachmentRecord:
        from app.database import get_pool
        row = await get_pool().fetchrow(
            """INSERT INTO mcp.agent_attachments(attachment_id,session_id,storage_key,sha256,size_bytes,content_type)
               VALUES($1::uuid,$2,$3,$4,$5,$6)
               ON CONFLICT(session_id,sha256) DO UPDATE SET content_type=EXCLUDED.content_type
               RETURNING attachment_id::text,session_id,storage_key,sha256,size_bytes,content_type,created_at""",
            payload.attachment_id.removeprefix("attachment:"), payload.session_id, payload.storage_key,
            payload.sha256, payload.size_bytes, payload.content_type,
        )
        values = dict(row)
        values["attachment_id"] = "attachment:" + values["attachment_id"].replace("-", "")
        return AgentAttachmentRecord(**values)


class MemoryAgentContractStore:
    def __init__(self) -> None:
        self.sessions: dict[str, AgentSessionContractRecord] = {}
        self.attachments: dict[tuple[str, str], AgentAttachmentRecord] = {}

    async def upsert_session(self, payload: ProviderSessionContract) -> AgentSessionContractRecord:
        existing = self.sessions.get(payload.session_id)
        if existing and existing.runner_session_id and payload.runner_session_id and existing.runner_session_id != payload.runner_session_id:
            raise ValueError("agent_runner_identity_conflict")
        if existing and existing.runner_session_id and existing.runner_provider != payload.runner_provider:
            raise ValueError("agent_runner_provider_conflict")
        now = datetime.now(timezone.utc)
        record = AgentSessionContractRecord(
            session_id=payload.session_id, runner_provider=payload.runner_provider,
            runner_session_id=payload.runner_session_id or (existing.runner_session_id if existing else None),
            project_dir_hash=canonical_project_hash(payload), model=payload.model, effort=payload.effort,
            status=payload.status, trace_id=payload.trace_id or (existing.trace_id if existing else None),
            contract_version="workbench.v1" if payload.project_handle else (existing.contract_version if existing else None),
            context_snapshot_id=payload.context_snapshot_id or (existing.context_snapshot_id if existing else None),
            requested_provider=payload.requested_provider or (existing.requested_provider if existing else None),
            resolved_runner_mode=payload.resolved_runner_mode or (existing.resolved_runner_mode if existing else None),
            fallback_reason_code=payload.fallback_reason_code or (existing.fallback_reason_code if existing else None),
            provider_accepted_at=payload.provider_accepted_at or (existing.provider_accepted_at if existing else None),
            parent_session_id=payload.parent_session_id or (existing.parent_session_id if existing else None),
            project_handle=payload.project_handle or (existing.project_handle if existing else None),
            project_display_name=payload.project_display_name or (existing.project_display_name if existing else None),
            created_at=existing.created_at if existing else now, updated_at=now,
        )
        self.sessions[payload.session_id] = record
        return record

    async def get_session(self, session_id: str) -> AgentSessionContractRecord | None:
        return self.sessions.get(session_id)

    async def record_attachment(self, payload: AgentAttachmentInput) -> AgentAttachmentRecord:
        if payload.session_id not in self.sessions:
            raise ValueError("agent_session_not_found")
        key = (payload.session_id, payload.sha256)
        existing = self.attachments.get(key)
        if existing:
            return existing
        record = AgentAttachmentRecord(**payload.model_dump(), created_at=datetime.now(timezone.utc))
        self.attachments[key] = record
        return record
