-- S8-S10: append-only execution evidence and provider-neutral Agent contracts.
-- Source-only migration.  It is executed exclusively by scripts/apply_migrations.py.

CREATE SCHEMA IF NOT EXISTS mcp;

CREATE TABLE IF NOT EXISTS mcp.runtime_executions (
    trace_id TEXT PRIMARY KEY CHECK (trace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    execution_id TEXT NOT NULL CHECK (execution_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    correlation_id TEXT CHECK (correlation_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    session_id TEXT CHECK (session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    gate_id TEXT CHECK (gate_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp.runtime_spans (
    trace_id TEXT NOT NULL REFERENCES mcp.runtime_executions(trace_id) ON DELETE RESTRICT,
    span_id TEXT NOT NULL CHECK (span_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    parent_span_id TEXT CHECK (parent_span_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    kind TEXT NOT NULL CHECK (kind IN ('http', 'websocket', 'tool', 'service', 'database', 'source', 'host', 'model', 'gap')),
    node_id TEXT,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'cancelled', 'partial', 'unknown')),
    PRIMARY KEY (trace_id, span_id)
);

CREATE TABLE IF NOT EXISTS mcp.runtime_events (
    cursor BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL CHECK (source ~ '^[a-z][a-z0-9_.-]{1,99}$'),
    event_id TEXT NOT NULL CHECK (event_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    trace_id TEXT NOT NULL REFERENCES mcp.runtime_executions(trace_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL,
    span_id TEXT,
    parent_span_id TEXT,
    correlation_id TEXT,
    session_id TEXT,
    gate_id TEXT,
    sequence BIGINT CHECK (sequence IS NULL OR sequence >= 0),
    event_type TEXT NOT NULL CHECK (event_type IN ('started', 'completed', 'failed', 'cancelled', 'retry', 'gap', 'annotation')),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled', 'partial', 'unknown')),
    span_kind TEXT NOT NULL CHECK (span_kind IN ('http', 'websocket', 'tool', 'service', 'database', 'source', 'host', 'model', 'gap')),
    node_id TEXT,
    read_write TEXT NOT NULL DEFAULT 'none' CHECK (read_write IN ('none', 'read', 'write', 'read_write')),
    payload_schema JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retention_until TIMESTAMPTZ NOT NULL,
    UNIQUE (source, event_id)
);

CREATE INDEX IF NOT EXISTS idx_runtime_events_trace_cursor
    ON mcp.runtime_events(trace_id, cursor);
CREATE INDEX IF NOT EXISTS idx_runtime_events_trace_sequence
    ON mcp.runtime_events(trace_id, sequence, observed_at, cursor);
CREATE INDEX IF NOT EXISTS idx_runtime_events_session
    ON mcp.runtime_events(session_id, cursor) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runtime_events_gate
    ON mcp.runtime_events(gate_id, cursor) WHERE gate_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runtime_events_retention
    ON mcp.runtime_events(retention_until);

CREATE TABLE IF NOT EXISTS mcp.agent_session_contracts (
    session_id TEXT PRIMARY KEY CHECK (session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    runner_provider TEXT NOT NULL CHECK (runner_provider IN ('codex', 'claude')),
    runner_session_id TEXT UNIQUE CHECK (runner_session_id IS NULL OR runner_session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    project_dir_hash TEXT NOT NULL CHECK (project_dir_hash ~ '^sha256:[0-9a-f]{64}$'),
    model TEXT,
    effort TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'failed', 'cancelled', 'archived')),
    trace_id TEXT REFERENCES mcp.runtime_executions(trace_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp.agent_attachments (
    attachment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL REFERENCES mcp.agent_session_contracts(session_id) ON DELETE RESTRICT,
    storage_key TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    content_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, sha256)
);

CREATE TABLE IF NOT EXISTS mcp.runtime_plan_drafts (
    draft_id TEXT PRIMARY KEY CHECK (draft_id ~ '^plan:[0-9a-f]{32}$'),
    finding_fingerprint TEXT NOT NULL CHECK (finding_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'),
    base_snapshot_id TEXT NOT NULL CHECK (base_snapshot_id ~ '^sha256:[0-9a-f]{64}$'),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'stale')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (finding_fingerprint, base_snapshot_id)
);

COMMENT ON TABLE mcp.runtime_events IS 'S8 append-only redacted runtime event ledger; payload raw values are prohibited.';
COMMENT ON TABLE mcp.agent_session_contracts IS 'S10 provider-neutral session contract; project path is represented only by a hash.';
COMMENT ON TABLE mcp.runtime_plan_drafts IS 'S9 candidate-plan drafts only; creation never authorizes implementation or side effects.';
