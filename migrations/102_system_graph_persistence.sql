-- S7: immutable system-graph snapshots and refresh audit.
-- Source-only additive migration; scripts/apply_migrations.py is the only runner.

CREATE SCHEMA IF NOT EXISTS mcp;

CREATE TABLE IF NOT EXISTS mcp.system_graph_refreshes (
    refresh_id UUID PRIMARY KEY,
    request_fingerprint TEXT NOT NULL UNIQUE CHECK (request_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    actor_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')),
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_results JSONB NOT NULL DEFAULT '[]'::jsonb,
    snapshot_id TEXT,
    error JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp.system_graph_snapshots (
    snapshot_id TEXT PRIMARY KEY CHECK (snapshot_id ~ '^sha256:[0-9a-f]{64}$'),
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    commit_sha TEXT NOT NULL CHECK (commit_sha ~ '^[0-9a-f]{40,64}$'),
    definition_revision TEXT NOT NULL CHECK (definition_revision ~ '^sha256:[0-9a-f]{64}$'),
    feature_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_results JSONB NOT NULL DEFAULT '[]'::jsonb,
    snapshot_json JSONB NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    persisted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'fk_system_graph_refresh_snapshot'
           AND conrelid = 'mcp.system_graph_refreshes'::regclass
    ) THEN
        ALTER TABLE mcp.system_graph_refreshes
            ADD CONSTRAINT fk_system_graph_refresh_snapshot
            FOREIGN KEY (snapshot_id) REFERENCES mcp.system_graph_snapshots(snapshot_id) ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS mcp.system_graph_nodes (
    snapshot_id TEXT NOT NULL REFERENCES mcp.system_graph_snapshots(snapshot_id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    node_key TEXT NOT NULL,
    label TEXT NOT NULL,
    state JSONB NOT NULL,
    attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (snapshot_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_system_graph_nodes_lookup
    ON mcp.system_graph_nodes(kind, node_key, snapshot_id);

CREATE TABLE IF NOT EXISTS mcp.system_graph_edges (
    snapshot_id TEXT NOT NULL REFERENCES mcp.system_graph_snapshots(snapshot_id) ON DELETE RESTRICT,
    edge_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    state JSONB NOT NULL,
    attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (snapshot_id, edge_id),
    FOREIGN KEY (snapshot_id, source_node_id)
        REFERENCES mcp.system_graph_nodes(snapshot_id, node_id) ON DELETE RESTRICT,
    FOREIGN KEY (snapshot_id, target_node_id)
        REFERENCES mcp.system_graph_nodes(snapshot_id, node_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_system_graph_edges_source
    ON mcp.system_graph_edges(snapshot_id, source_node_id);
CREATE INDEX IF NOT EXISTS idx_system_graph_edges_target
    ON mcp.system_graph_edges(snapshot_id, target_node_id);

CREATE OR REPLACE FUNCTION mcp.reject_system_graph_snapshot_update()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'system graph snapshots are immutable';
END;
$$;

DROP TRIGGER IF EXISTS trg_system_graph_snapshots_immutable ON mcp.system_graph_snapshots;
CREATE TRIGGER trg_system_graph_snapshots_immutable
BEFORE UPDATE OR DELETE ON mcp.system_graph_snapshots
FOR EACH ROW EXECUTE FUNCTION mcp.reject_system_graph_snapshot_update();

COMMENT ON TABLE mcp.system_graph_snapshots IS 'S7 immutable content-addressed fact graph; application updates are prohibited.';
COMMENT ON TABLE mcp.system_graph_refreshes IS 'Audited idempotent graph refresh lifecycle; collector failure remains partial/unknown.';
