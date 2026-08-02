-- G1: immutable workbench context and additive bindings to existing truth sources.
-- Source-only migration. It is executed exclusively by scripts/apply_migrations.py.
-- Existing rows remain valid: all bindings added to existing tables are nullable.

CREATE SCHEMA IF NOT EXISTS mcp;

CREATE OR REPLACE FUNCTION mcp.is_safe_workbench_ref(value TEXT)
RETURNS BOOLEAN LANGUAGE SQL IMMUTABLE PARALLEL SAFE STRICT AS $$
    SELECT value ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$'
       AND (
           value ~ '^(ui_route|api_route):/[A-Za-z0-9._/-]*$'
           OR value !~ ':[\\/]'
       );
$$;

CREATE OR REPLACE FUNCTION mcp.are_safe_workbench_refs(value JSONB)
RETURNS BOOLEAN LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE STRICT AS $$
DECLARE
    item JSONB;
    text_value TEXT;
    seen TEXT[] := ARRAY[]::TEXT[];
BEGIN
    IF jsonb_typeof(value) <> 'array' THEN
        RETURN FALSE;
    END IF;
    FOR item IN SELECT element FROM jsonb_array_elements(value) AS elements(element)
    LOOP
        IF jsonb_typeof(item) <> 'string' THEN
            RETURN FALSE;
        END IF;
        text_value := item #>> '{}';
        IF NOT mcp.is_safe_workbench_ref(text_value)
           OR text_value = ANY(seen) THEN
            RETURN FALSE;
        END IF;
        seen := array_append(seen, text_value);
    END LOOP;
    RETURN TRUE;
END;
$$;

CREATE TABLE IF NOT EXISTS mcp.workbench_context_snapshots (
    snapshot_id TEXT PRIMARY KEY
        CHECK (mcp.is_safe_workbench_ref(snapshot_id)),
    context_ref TEXT NOT NULL
        CHECK (mcp.is_safe_workbench_ref(context_ref)),
    revision BIGINT NOT NULL CHECK (revision >= 1),
    workspace_ref TEXT NOT NULL
        CHECK (mcp.is_safe_workbench_ref(workspace_ref)),
    shop_ref TEXT
        CHECK (shop_ref IS NULL OR mcp.is_safe_workbench_ref(shop_ref)),
    sku_ref TEXT
        CHECK (sku_ref IS NULL OR mcp.is_safe_workbench_ref(sku_ref)),
    project_ref TEXT
        CHECK (project_ref IS NULL OR mcp.is_safe_workbench_ref(project_ref)),
    environment_ref TEXT
        CHECK (environment_ref IS NULL OR mcp.is_safe_workbench_ref(environment_ref)),
    task_ref TEXT
        CHECK (task_ref IS NULL OR mcp.is_safe_workbench_ref(task_ref)),
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (mcp.are_safe_workbench_refs(evidence_refs)),
    origin_surface_ref TEXT NOT NULL
        CHECK (mcp.is_safe_workbench_ref(origin_surface_ref)),
    permission_scope_hash TEXT NOT NULL
        CHECK (permission_scope_hash ~ '^sha256:[0-9a-f]{64}$'),
    availability TEXT NOT NULL DEFAULT 'available'
        CHECK (availability IN ('available', 'unavailable')),
    rebind_reason TEXT
        CHECK (rebind_reason IS NULL OR rebind_reason ~ '^[a-z][a-z0-9_.-]{0,99}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_workbench_context_snapshots_context_revision
        UNIQUE (context_ref, revision)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_workbench_context_snapshots_append_only'
          AND tgrelid = 'mcp.workbench_context_snapshots'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_workbench_context_snapshots_append_only
        BEFORE UPDATE OR DELETE ON mcp.workbench_context_snapshots
        FOR EACH ROW EXECUTE FUNCTION mcp.reject_append_only_mutation();
    END IF;
END;
$$;

ALTER TABLE mcp.agent_session_contracts
    ADD COLUMN IF NOT EXISTS contract_version TEXT,
    ADD COLUMN IF NOT EXISTS context_snapshot_id TEXT,
    ADD COLUMN IF NOT EXISTS requested_provider TEXT,
    ADD COLUMN IF NOT EXISTS resolved_runner_mode TEXT,
    ADD COLUMN IF NOT EXISTS fallback_reason_code TEXT,
    ADD COLUMN IF NOT EXISTS provider_accepted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS parent_session_id TEXT,
    ADD COLUMN IF NOT EXISTS project_handle TEXT,
    ADD COLUMN IF NOT EXISTS project_display_name TEXT;

ALTER TABLE mcp.agent_session_contracts
    DROP CONSTRAINT IF EXISTS agent_session_contracts_status_check;
ALTER TABLE mcp.agent_session_contracts
    ADD CONSTRAINT agent_session_contracts_status_check
    CHECK (status IN (
        'resolving', 'active', 'paused', 'completed', 'failed',
        'cancelled', 'unavailable', 'archived'
    ));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_session_contracts_context_snapshot_fkey'
          AND conrelid = 'mcp.agent_session_contracts'::regclass
    ) THEN
        ALTER TABLE mcp.agent_session_contracts
            ADD CONSTRAINT agent_session_contracts_context_snapshot_fkey
            FOREIGN KEY (context_snapshot_id)
            REFERENCES mcp.workbench_context_snapshots(snapshot_id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_session_contracts_parent_session_fkey'
          AND conrelid = 'mcp.agent_session_contracts'::regclass
    ) THEN
        ALTER TABLE mcp.agent_session_contracts
            ADD CONSTRAINT agent_session_contracts_parent_session_fkey
            FOREIGN KEY (parent_session_id)
            REFERENCES mcp.agent_session_contracts(session_id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_session_contracts_parent_not_self_check'
          AND conrelid = 'mcp.agent_session_contracts'::regclass
    ) THEN
        ALTER TABLE mcp.agent_session_contracts
            ADD CONSTRAINT agent_session_contracts_parent_not_self_check
            CHECK (parent_session_id IS NULL OR parent_session_id <> session_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_session_contracts_workbench_fields_check'
          AND conrelid = 'mcp.agent_session_contracts'::regclass
    ) THEN
        ALTER TABLE mcp.agent_session_contracts
            ADD CONSTRAINT agent_session_contracts_workbench_fields_check
            CHECK (
                (contract_version IS NULL OR contract_version = 'workbench.v1')
                AND (
                    requested_provider IS NULL
                    OR requested_provider IN ('auto', 'codex', 'claude')
                )
                AND (resolved_runner_mode IS NULL OR resolved_runner_mode IN ('host', 'local'))
                AND (
                    fallback_reason_code IS NULL
                    OR fallback_reason_code ~ '^[a-z][a-z0-9_.-]{0,99}$'
                )
                AND (
                    requested_provider IS NULL
                    OR requested_provider = 'auto'
                    OR requested_provider = runner_provider
                    OR fallback_reason_code IS NOT NULL
                )
                AND (
                    project_handle IS NULL
                    OR project_handle ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{1,199}$'
                )
                AND (
                    project_display_name IS NULL
                    OR (
                        char_length(project_display_name) BETWEEN 1 AND 160
                        AND project_display_name = btrim(project_display_name)
                        AND project_display_name !~ '^[[:space:]]'
                        AND project_display_name !~ '[[:space:]]$'
                        AND project_display_name !~ '[\\/]'
                        AND project_display_name !~ E'[\\r\\n]'
                        AND project_display_name NOT IN ('.', '..')
                        AND project_display_name !~ '^~'
                        AND project_display_name !~* '%(2f|5c)'
                    )
                )
                AND (
                    contract_version IS NULL
                    OR (
                        context_snapshot_id IS NOT NULL
                        AND requested_provider IS NOT NULL
                        AND project_handle IS NOT NULL
                        AND project_display_name IS NOT NULL
                        AND (
                            (
                                status IN ('resolving', 'unavailable')
                                AND provider_accepted_at IS NULL
                            )
                            OR (
                                status IN (
                                    'active', 'paused', 'completed', 'failed', 'cancelled'
                                )
                                AND runner_session_id IS NOT NULL
                                AND resolved_runner_mode IS NOT NULL
                                AND provider_accepted_at IS NOT NULL
                            )
                            OR status = 'archived'
                        )
                    )
                )
            );
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION mcp.guard_agent_session_provider_acceptance()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.context_snapshot_id IS NOT NULL
       AND NEW.context_snapshot_id IS DISTINCT FROM OLD.context_snapshot_id THEN
        RAISE EXCEPTION 'agent session context snapshot binding is immutable';
    END IF;
    IF OLD.parent_session_id IS NOT NULL
       AND NEW.parent_session_id IS DISTINCT FROM OLD.parent_session_id THEN
        RAISE EXCEPTION 'agent session lineage binding is immutable';
    END IF;
    IF OLD.project_handle IS NOT NULL AND (
        NEW.project_handle IS DISTINCT FROM OLD.project_handle
        OR NEW.project_display_name IS DISTINCT FROM OLD.project_display_name
    ) THEN
        RAISE EXCEPTION 'agent session opaque project identity is immutable';
    END IF;
    IF OLD.provider_accepted_at IS NOT NULL AND (
        NEW.contract_version IS DISTINCT FROM OLD.contract_version
        OR NEW.requested_provider IS DISTINCT FROM OLD.requested_provider
        OR NEW.runner_provider IS DISTINCT FROM OLD.runner_provider
        OR NEW.resolved_runner_mode IS DISTINCT FROM OLD.resolved_runner_mode
        OR NEW.fallback_reason_code IS DISTINCT FROM OLD.fallback_reason_code
        OR NEW.context_snapshot_id IS DISTINCT FROM OLD.context_snapshot_id
        OR NEW.parent_session_id IS DISTINCT FROM OLD.parent_session_id
        OR NEW.project_dir_hash IS DISTINCT FROM OLD.project_dir_hash
        OR NEW.project_handle IS DISTINCT FROM OLD.project_handle
        OR NEW.project_display_name IS DISTINCT FROM OLD.project_display_name
        OR NEW.provider_accepted_at IS DISTINCT FROM OLD.provider_accepted_at
    ) THEN
        RAISE EXCEPTION
            'accepted agent session provider, context, lineage, and project identity are immutable';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_agent_session_contracts_provider_acceptance_lock'
          AND tgrelid = 'mcp.agent_session_contracts'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_agent_session_contracts_provider_acceptance_lock
        BEFORE UPDATE ON mcp.agent_session_contracts
        FOR EACH ROW EXECUTE FUNCTION mcp.guard_agent_session_provider_acceptance();
    END IF;
END;
$$;

ALTER TABLE mcp.runtime_executions
    ADD COLUMN IF NOT EXISTS context_snapshot_id TEXT,
    ADD COLUMN IF NOT EXISTS idempotency_key_hash TEXT;

ALTER TABLE mcp.approval_operations
    ADD COLUMN IF NOT EXISTS context_snapshot_id TEXT,
    ADD COLUMN IF NOT EXISTS agent_session_id TEXT;

CREATE OR REPLACE FUNCTION mcp.guard_workbench_context_binding()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.context_snapshot_id IS NOT NULL
       AND NEW.context_snapshot_id IS DISTINCT FROM OLD.context_snapshot_id THEN
        RAISE EXCEPTION 'workbench context snapshot binding is immutable';
    END IF;
    IF OLD.agent_session_id IS NOT NULL
       AND NEW.agent_session_id IS DISTINCT FROM OLD.agent_session_id THEN
        RAISE EXCEPTION 'approval operation agent session binding is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION mcp.guard_runtime_execution_binding()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.context_snapshot_id IS NOT NULL
       AND NEW.context_snapshot_id IS DISTINCT FROM OLD.context_snapshot_id THEN
        RAISE EXCEPTION 'runtime execution context snapshot binding is immutable';
    END IF;
    IF OLD.idempotency_key_hash IS NOT NULL
       AND NEW.idempotency_key_hash IS DISTINCT FROM OLD.idempotency_key_hash THEN
        RAISE EXCEPTION 'runtime execution idempotency binding is immutable';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'runtime_executions_context_snapshot_fkey'
          AND conrelid = 'mcp.runtime_executions'::regclass
    ) THEN
        ALTER TABLE mcp.runtime_executions
            ADD CONSTRAINT runtime_executions_context_snapshot_fkey
            FOREIGN KEY (context_snapshot_id)
            REFERENCES mcp.workbench_context_snapshots(snapshot_id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'runtime_executions_idempotency_key_hash_check'
          AND conrelid = 'mcp.runtime_executions'::regclass
    ) THEN
        ALTER TABLE mcp.runtime_executions
            ADD CONSTRAINT runtime_executions_idempotency_key_hash_check
            CHECK (
                idempotency_key_hash IS NULL
                OR idempotency_key_hash ~ '^sha256:[0-9a-f]{64}$'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'approval_operations_context_snapshot_fkey'
          AND conrelid = 'mcp.approval_operations'::regclass
    ) THEN
        ALTER TABLE mcp.approval_operations
            ADD CONSTRAINT approval_operations_context_snapshot_fkey
            FOREIGN KEY (context_snapshot_id)
            REFERENCES mcp.workbench_context_snapshots(snapshot_id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'approval_operations_agent_session_fkey'
          AND conrelid = 'mcp.approval_operations'::regclass
    ) THEN
        ALTER TABLE mcp.approval_operations
            ADD CONSTRAINT approval_operations_agent_session_fkey
            FOREIGN KEY (agent_session_id)
            REFERENCES mcp.agent_session_contracts(session_id)
            ON DELETE RESTRICT;
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS trg_runtime_executions_context_lock
    ON mcp.runtime_executions;
CREATE TRIGGER trg_runtime_executions_context_lock
BEFORE UPDATE ON mcp.runtime_executions
FOR EACH ROW EXECUTE FUNCTION mcp.guard_runtime_execution_binding();

DROP TRIGGER IF EXISTS trg_approval_operations_context_lock
    ON mcp.approval_operations;
CREATE TRIGGER trg_approval_operations_context_lock
BEFORE UPDATE ON mcp.approval_operations
FOR EACH ROW EXECUTE FUNCTION mcp.guard_workbench_context_binding();

CREATE INDEX IF NOT EXISTS idx_workbench_context_snapshots_workspace_created
    ON mcp.workbench_context_snapshots(workspace_ref, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workbench_context_snapshots_sku
    ON mcp.workbench_context_snapshots(sku_ref, created_at DESC)
    WHERE sku_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_workbench_context_snapshots_project
    ON mcp.workbench_context_snapshots(project_ref, created_at DESC)
    WHERE project_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_session_contracts_context_snapshot
    ON mcp.agent_session_contracts(context_snapshot_id)
    WHERE context_snapshot_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_session_contracts_parent_session
    ON mcp.agent_session_contracts(parent_session_id)
    WHERE parent_session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runtime_executions_context_snapshot
    ON mcp.runtime_executions(context_snapshot_id)
    WHERE context_snapshot_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_approval_operations_context_snapshot
    ON mcp.approval_operations(context_snapshot_id)
    WHERE context_snapshot_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_approval_operations_agent_session
    ON mcp.approval_operations(agent_session_id)
    WHERE agent_session_id IS NOT NULL;

COMMENT ON TABLE mcp.workbench_context_snapshots IS
    'G1 append-only immutable workbench object, task, evidence, and permission binding; no business payload or secret is copied.';
COMMENT ON COLUMN mcp.workbench_context_snapshots.origin_surface_ref IS
    'Creation provenance only; the current UI surface is not stored in this immutable snapshot.';
COMMENT ON COLUMN mcp.workbench_context_snapshots.permission_scope_hash IS
    'SHA-256 digest of the authorized scope; raw permissions and credentials are prohibited.';
COMMENT ON COLUMN mcp.workbench_context_snapshots.availability IS
    'Whether referenced objects remain available; historical snapshots are retained when unavailable.';

COMMENT ON COLUMN mcp.agent_session_contracts.context_snapshot_id IS
    'Immutable workbench target binding after provider_accepted_at is set.';
COMMENT ON COLUMN mcp.agent_session_contracts.requested_provider IS
    'Provider requested before resolution; nullable for legacy sessions.';
COMMENT ON COLUMN mcp.agent_session_contracts.resolved_runner_mode IS
    'Resolved execution boundary: host or local; immutable after provider acceptance.';
COMMENT ON COLUMN mcp.agent_session_contracts.fallback_reason_code IS
    'Safe machine-readable pre-acceptance fallback disclosure; never contains raw provider output.';
COMMENT ON COLUMN mcp.agent_session_contracts.parent_session_id IS
    'Optional lineage link for recovery into a new logical session; no in-place provider switch.';
COMMENT ON COLUMN mcp.agent_session_contracts.project_handle IS
    'Opaque public project identifier; raw project_dir is prohibited at this boundary.';
COMMENT ON COLUMN mcp.agent_session_contracts.project_display_name IS
    'Safe display label without path separators; raw local paths are prohibited.';

COMMENT ON COLUMN mcp.runtime_executions.context_snapshot_id IS
    'Frozen context used by this existing runtime execution truth source.';
COMMENT ON COLUMN mcp.runtime_executions.idempotency_key_hash IS
    'Optional canonical idempotency digest for new operations; nullable for legacy runtime executions and immutable after binding.';
COMMENT ON COLUMN mcp.approval_operations.context_snapshot_id IS
    'Frozen context reviewed by this existing approval operation.';
COMMENT ON COLUMN mcp.approval_operations.agent_session_id IS
    'Optional provider-neutral agent session bound to this existing approval operation.';
