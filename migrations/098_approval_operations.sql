-- Recoverable, non-blocking approval operations.
-- This additive source migration is executed only by scripts/apply_migrations.py.

CREATE SCHEMA IF NOT EXISTS mcp;

CREATE TABLE IF NOT EXISTS mcp.approval_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id TEXT NOT NULL UNIQUE,
    requested_by TEXT NOT NULL,
    permission_snapshot_hash TEXT NOT NULL
        CHECK (permission_snapshot_hash ~ '^[0-9a-f]{64}$'),
    trace_id TEXT,
    handler TEXT NOT NULL,
    risk TEXT NOT NULL DEFAULT 'R3' CHECK (risk = 'R3'),
    idempotency_strategy TEXT NOT NULL
        CHECK (idempotency_strategy IN ('transactional', 'provider_idempotency', 'manual_reconciliation')),
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    redacted_payload JSONB NOT NULL,
    target JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN (
            'pending', 'resuming', 'succeeded', 'failed', 'cancelled',
            'expired', 'revoked', 'manual_reconciliation'
        )),
    decision TEXT CHECK (decision IN ('approved', 'rejected', 'expired', 'revoked')),
    decision_note TEXT,
    decision_actor TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    worker_id TEXT,
    worker_lease_token UUID,
    worker_lease_expires_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    effect_started_at TIMESTAMPTZ,
    result JSONB,
    error JSONB,
    attempt_count INT NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

ALTER TABLE mcp.human_gates
    ADD COLUMN IF NOT EXISTS operation_id UUID
        REFERENCES mcp.approval_operations(id) ON DELETE CASCADE;
ALTER TABLE mcp.human_gates
    ADD COLUMN IF NOT EXISTS decided_by TEXT;

CREATE TABLE IF NOT EXISTS mcp.approval_operation_audit (
    id BIGSERIAL PRIMARY KEY,
    operation_id UUID NOT NULL
        REFERENCES mcp.approval_operations(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN (
        'created', 'approved', 'rejected', 'revoked', 'expired',
        'claimed', 'effect_started', 'retry_scheduled', 'recovered_pending',
        'notification_failed',
        'succeeded', 'failed', 'manual_reconciliation'
    )),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_human_gates_operation
    ON mcp.human_gates(operation_id) WHERE operation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_approval_operations_claim
    ON mcp.approval_operations(state, decision, expires_at, worker_lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_approval_operations_trace
    ON mcp.approval_operations(trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_approval_operations_requester
    ON mcp.approval_operations(requested_by, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approval_operations_manual
    ON mcp.approval_operations(updated_at)
    WHERE state = 'manual_reconciliation';
CREATE INDEX IF NOT EXISTS idx_approval_operation_audit_operation
    ON mcp.approval_operation_audit(operation_id, created_at);
