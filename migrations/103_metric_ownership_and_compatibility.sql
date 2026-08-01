-- S12/S13: append-only metric observations, collision evidence and retirement telemetry.

CREATE SCHEMA IF NOT EXISTS mcp;

CREATE TABLE IF NOT EXISTS mcp.metric_source_owners (
    platform TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    owner_source TEXT NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_by TEXT NOT NULL DEFAULT 'first_observation',
    PRIMARY KEY (platform, metric_name),
    CHECK (platform <> '' AND metric_name <> '' AND owner_source <> '')
);

CREATE TABLE IF NOT EXISTS mcp.metric_observations (
    observation_id UUID PRIMARY KEY,
    sku_id TEXT NOT NULL,
    metric_date DATE NOT NULL,
    metric_name TEXT NOT NULL,
    value NUMERIC,
    platform TEXT NOT NULL,
    source TEXT NOT NULL,
    source_run_id TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_hash TEXT NOT NULL,
    UNIQUE (payload_hash),
    CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_metric_observations_key
    ON mcp.metric_observations (platform, metric_name, sku_id, metric_date, observed_at DESC);

CREATE TABLE IF NOT EXISTS mcp.metric_collisions (
    collision_id UUID PRIMARY KEY,
    observation_id UUID NOT NULL UNIQUE REFERENCES mcp.metric_observations(observation_id),
    owner_source TEXT NOT NULL,
    canonical_value NUMERIC,
    canonical_source TEXT,
    reason TEXT NOT NULL DEFAULT 'non_owner_write_blocked',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp.compatibility_telemetry (
    event_id UUID PRIMARY KEY,
    client_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    route_family TEXT NOT NULL,
    exclusive BOOLEAN NOT NULL DEFAULT FALSE,
    observed_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_hash TEXT NOT NULL UNIQUE,
    CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_compatibility_telemetry_window
    ON mcp.compatibility_telemetry (client_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS mcp.retirement_reconciliations (
    reconciliation_id UUID PRIMARY KEY,
    client_id TEXT NOT NULL,
    inventory_kind TEXT NOT NULL,
    source_checksum TEXT,
    target_checksum TEXT,
    state TEXT NOT NULL CHECK (state IN ('matched','mismatch','missing','unknown')),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (client_id, inventory_kind, observed_at)
);

CREATE OR REPLACE FUNCTION mcp.reject_append_only_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['metric_observations','metric_collisions','compatibility_telemetry','retirement_reconciliations']
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_trigger
      WHERE tgname = 'trg_' || table_name || '_append_only'
        AND tgrelid = ('mcp.' || table_name)::regclass
    ) THEN
      EXECUTE format(
        'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON mcp.%I FOR EACH ROW EXECUTE FUNCTION mcp.reject_append_only_mutation()',
        'trg_' || table_name || '_append_only', table_name
      );
    END IF;
  END LOOP;
END;
$$;

