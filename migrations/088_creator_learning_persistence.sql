-- Creator learning / Douyin benchmark persistence (PRD 2026-07-28).
--
-- This migration is deliberately additive.  content_studio is the domain
-- truth for creator sources, videos, reconstructions, templates, applications
-- and prescreens.  video_analysis.videos remains an optional evidence
-- reference only; no dependency is taken on its historical reverse-engineer
-- materials/material_units/material_clusters tables.
--
-- The repository's SQL files currently end at 086, but the deployed migration
-- ledger already has an unrelated 087.  Keep this as 088 so a migration runner
-- cannot collide with that applied filename.

CREATE SCHEMA IF NOT EXISTS content_studio;

-- All creator-learning JSON documents are versioned.  Keeping this helper
-- small and immutable lets the database reject unversioned writer payloads
-- without imposing a schema on legacy JSON columns.
CREATE OR REPLACE FUNCTION content_studio.creator_json_is_versioned(value JSONB)
RETURNS BOOLEAN
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT COALESCE(
        jsonb_typeof(value) = 'object'
        AND NULLIF(btrim(value ->> 'schema_version'), '') IS NOT NULL,
        FALSE
    );
$$;

-- -------------------------------------------------------------------------
-- DES-012 / DES-013: source identity and append-only sync history.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_studio.creator_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform TEXT NOT NULL DEFAULT 'douyin',
    source_type TEXT NOT NULL,
    external_account_id TEXT,
    canonical_url TEXT NOT NULL,
    display_name TEXT,
    identity_strength TEXT NOT NULL DEFAULT 'unverified',
    sync_status TEXT NOT NULL DEFAULT 'active',
    cursor JSONB NOT NULL DEFAULT
        '{"schema_version":"creator_cursor.v1"}'::jsonb,
    source_metadata JSONB NOT NULL DEFAULT
        '{"schema_version":"creator_source.v1"}'::jsonb,
    last_synced_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT creator_sources_platform_check
        CHECK (platform = 'douyin'),
    CONSTRAINT creator_sources_type_check
        CHECK (source_type IN ('account', 'video')),
    CONSTRAINT creator_sources_identity_strength_check
        CHECK (identity_strength IN ('unverified', 'weak', 'strong', 'verified')),
    CONSTRAINT creator_sources_sync_status_check
        CHECK (sync_status IN (
            'active', 'syncing', 'paused', 'auth_required', 'error', 'archived'
        )),
    CONSTRAINT creator_sources_external_account_nonblank_check
        CHECK (external_account_id IS NULL OR btrim(external_account_id) <> ''),
    CONSTRAINT creator_sources_canonical_url_nonblank_check
        CHECK (btrim(canonical_url) <> ''),
    CONSTRAINT creator_sources_cursor_check
        CHECK (content_studio.creator_json_is_versioned(cursor)),
    CONSTRAINT creator_sources_metadata_check
        CHECK (content_studio.creator_json_is_versioned(source_metadata)),
    CONSTRAINT creator_sources_archived_at_check
        CHECK (sync_status <> 'archived' OR archived_at IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_sources_platform_account
    ON content_studio.creator_sources (platform, external_account_id)
    WHERE external_account_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_sources_platform_canonical_without_account
    ON content_studio.creator_sources (platform, canonical_url)
    WHERE external_account_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_creator_sources_sync_status
    ON content_studio.creator_sources (sync_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS content_studio.creator_sync_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID NOT NULL REFERENCES content_studio.creator_sources(id)
        ON DELETE RESTRICT,
    idempotency_key TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    cursor_before JSONB NOT NULL DEFAULT
        '{"schema_version":"creator_cursor.v1"}'::jsonb,
    cursor_after JSONB NOT NULL DEFAULT
        '{"schema_version":"creator_cursor.v1"}'::jsonb,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    deduped_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    inaccessible_count INTEGER NOT NULL DEFAULT 0,
    termination_reason TEXT,
    error_code TEXT,
    error TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT creator_sync_runs_status_check
        CHECK (status IN (
            'queued', 'running', 'partial', 'succeeded', 'failed',
            'cancelled', 'auth_required'
        )),
    CONSTRAINT creator_sync_runs_idempotency_nonblank_check
        CHECK (idempotency_key IS NULL OR btrim(idempotency_key) <> ''),
    CONSTRAINT creator_sync_runs_counts_nonnegative_check
        CHECK (
            discovered_count >= 0 AND deduped_count >= 0 AND failed_count >= 0
            AND inaccessible_count >= 0
        ),
    CONSTRAINT creator_sync_runs_cursor_before_check
        CHECK (content_studio.creator_json_is_versioned(cursor_before)),
    CONSTRAINT creator_sync_runs_cursor_after_check
        CHECK (content_studio.creator_json_is_versioned(cursor_after))
);

-- A partial/auth-paused run owns the source cursor until resumed or terminal.
CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_sync_runs_active_source
    ON content_studio.creator_sync_runs (source_id)
    WHERE status IN ('queued', 'running', 'partial', 'auth_required');
CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_sync_runs_idempotency
    ON content_studio.creator_sync_runs (source_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_creator_sync_runs_source_created
    ON content_studio.creator_sync_runs (source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_creator_sync_runs_status
    ON content_studio.creator_sync_runs (status, updated_at DESC);

-- A source is soft archived by setting sync_status=archived/archived_at.  A
-- physical delete would destroy audit references and is intentionally refused.
CREATE OR REPLACE FUNCTION content_studio.guard_creator_source_delete()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'creator_source_hard_delete_forbidden_use_soft_archive'
        USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_creator_source_delete
    ON content_studio.creator_sources;
CREATE TRIGGER trg_guard_creator_source_delete
BEFORE DELETE ON content_studio.creator_sources
FOR EACH ROW EXECUTE FUNCTION content_studio.guard_creator_source_delete();

-- Sync rows are history records.  A worker may update the mutable run state,
-- but identity and terminal records may never be rewritten or deleted.
CREATE OR REPLACE FUNCTION content_studio.guard_creator_sync_run_history()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'creator_sync_run_delete_forbidden'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.source_id IS DISTINCT FROM OLD.source_id
       OR NEW.cursor_before IS DISTINCT FROM OLD.cursor_before
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'creator_sync_run_identity_immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status IN ('succeeded', 'failed', 'cancelled')
       AND (to_jsonb(NEW) - 'updated_at')
           IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
        RAISE EXCEPTION 'creator_sync_run_terminal_immutable'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_creator_sync_run_history
    ON content_studio.creator_sync_runs;
CREATE TRIGGER trg_guard_creator_sync_run_history
BEFORE UPDATE OR DELETE ON content_studio.creator_sync_runs
FOR EACH ROW EXECUTE FUNCTION content_studio.guard_creator_sync_run_history();

-- -------------------------------------------------------------------------
-- DES-014: a source owns a KB binding, never the KB's lifecycle.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_studio.creator_knowledge_bindings (
    source_id UUID PRIMARY KEY REFERENCES content_studio.creator_sources(id)
        ON DELETE RESTRICT,
    kb_id UUID NOT NULL REFERENCES knowledge.knowledge_bases(id)
        ON DELETE RESTRICT,
    document_count INTEGER NOT NULL DEFAULT 0,
    last_write_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT creator_knowledge_bindings_document_count_check
        CHECK (document_count >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_knowledge_bindings_kb
    ON content_studio.creator_knowledge_bindings (kb_id);

-- -------------------------------------------------------------------------
-- Existing material/task/reconstruction/template tables become creator-ready.
-- Legacy rows retain their old meaning; creator writers opt into a named
-- schema_version and are subject to the stricter contracts below.
-- -------------------------------------------------------------------------
ALTER TABLE content_studio.seed_materials
    ADD COLUMN IF NOT EXISTS source_id UUID,
    ADD COLUMN IF NOT EXISTS external_video_id TEXT,
    ADD COLUMN IF NOT EXISTS canonical_url TEXT,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER,
    ADD COLUMN IF NOT EXISTS media_status TEXT,
    ADD COLUMN IF NOT EXISTS managed_uri TEXT,
    ADD COLUMN IF NOT EXISTS sha256 TEXT,
    ADD COLUMN IF NOT EXISTS retention_policy TEXT,
    ADD COLUMN IF NOT EXISTS excluded_by_user BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.seed_materials'::regclass
          AND conname = 'seed_materials_creator_source_fkey'
    ) THEN
        ALTER TABLE content_studio.seed_materials
            ADD CONSTRAINT seed_materials_creator_source_fkey
            FOREIGN KEY (source_id) REFERENCES content_studio.creator_sources(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.seed_materials'::regclass
          AND conname = 'seed_materials_duration_ms_nonnegative_check'
    ) THEN
        ALTER TABLE content_studio.seed_materials
            ADD CONSTRAINT seed_materials_duration_ms_nonnegative_check
            CHECK (duration_ms IS NULL OR duration_ms >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.seed_materials'::regclass
          AND conname = 'seed_materials_external_video_nonblank_check'
    ) THEN
        ALTER TABLE content_studio.seed_materials
            ADD CONSTRAINT seed_materials_external_video_nonblank_check
            CHECK (external_video_id IS NULL OR btrim(external_video_id) <> '');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.seed_materials'::regclass
          AND conname = 'seed_materials_sha256_check'
    ) THEN
        ALTER TABLE content_studio.seed_materials
            ADD CONSTRAINT seed_materials_sha256_check
            CHECK (sha256 IS NULL OR sha256 ~ '^[a-f0-9]{64}$');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.seed_materials'::regclass
          AND conname = 'seed_materials_media_status_check'
    ) THEN
        ALTER TABLE content_studio.seed_materials
            ADD CONSTRAINT seed_materials_media_status_check
            CHECK (media_status IS NULL OR media_status IN (
                'discovered', 'queued', 'downloaded', 'managed', 'analyzed',
                'knowledge_written', 'benchmark_ready', 'inaccessible',
                'failed', 'deleted', 'excluded'
            ));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.seed_materials'::regclass
          AND conname = 'seed_materials_retention_policy_check'
    ) THEN
        ALTER TABLE content_studio.seed_materials
            ADD CONSTRAINT seed_materials_retention_policy_check
            CHECK (retention_policy IS NULL OR retention_policy IN (
                'knowledge_delete_after_kb', 'benchmark_retain',
                'manual_retain', 'deleted'
            ));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_seed_materials_source_external_video
    ON content_studio.seed_materials (source_id, external_video_id)
    WHERE source_id IS NOT NULL AND external_video_id IS NOT NULL;
-- Douyin video IDs are platform-global.  This catches the same work being
-- discovered from both a profile page and a single-video import.
CREATE UNIQUE INDEX IF NOT EXISTS uq_seed_materials_external_video_global
    ON content_studio.seed_materials (external_video_id)
    WHERE external_video_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_seed_materials_creator_source_published
    ON content_studio.seed_materials (source_id, published_at DESC)
    WHERE source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_seed_materials_media_status
    ON content_studio.seed_materials (media_status, updated_at DESC)
    WHERE media_status IS NOT NULL;

ALTER TABLE content_studio.template_analysis_tasks
    ADD COLUMN IF NOT EXISTS schema_version TEXT NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS source_id UUID,
    ADD COLUMN IF NOT EXISTS sync_run_id UUID,
    ADD COLUMN IF NOT EXISTS mode TEXT,
    ADD COLUMN IF NOT EXISTS scope_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS progress_counts JSONB,
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS lease_owner TEXT,
    ADD COLUMN IF NOT EXISTS lease_token UUID,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lease_heartbeat_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS error_code TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.template_analysis_tasks'::regclass
          AND conname = 'template_tasks_creator_source_fkey'
    ) THEN
        ALTER TABLE content_studio.template_analysis_tasks
            ADD CONSTRAINT template_tasks_creator_source_fkey
            FOREIGN KEY (source_id) REFERENCES content_studio.creator_sources(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.template_analysis_tasks'::regclass
          AND conname = 'template_tasks_creator_sync_run_fkey'
    ) THEN
        ALTER TABLE content_studio.template_analysis_tasks
            ADD CONSTRAINT template_tasks_creator_sync_run_fkey
            FOREIGN KEY (sync_run_id) REFERENCES content_studio.creator_sync_runs(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.template_analysis_tasks'::regclass
          AND conname = 'template_tasks_creator_mode_check'
    ) THEN
        ALTER TABLE content_studio.template_analysis_tasks
            ADD CONSTRAINT template_tasks_creator_mode_check
            CHECK (mode IS NULL OR mode IN ('knowledge_only', 'benchmark_full', 'cluster'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.template_analysis_tasks'::regclass
          AND conname = 'template_tasks_creator_idempotency_nonblank_check'
    ) THEN
        ALTER TABLE content_studio.template_analysis_tasks
            ADD CONSTRAINT template_tasks_creator_idempotency_nonblank_check
            CHECK (idempotency_key IS NULL OR btrim(idempotency_key) <> '');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.template_analysis_tasks'::regclass
          AND conname = 'template_tasks_creator_lease_shape_check'
    ) THEN
        ALTER TABLE content_studio.template_analysis_tasks
            ADD CONSTRAINT template_tasks_creator_lease_shape_check
            CHECK (
                (lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
                OR
                (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.template_analysis_tasks'::regclass
          AND conname = 'template_tasks_creator_versioned_payload_check'
    ) THEN
        ALTER TABLE content_studio.template_analysis_tasks
            ADD CONSTRAINT template_tasks_creator_versioned_payload_check
            CHECK (
                schema_version = 'legacy'
                OR (
                    mode IS NOT NULL
                    AND content_studio.creator_json_is_versioned(scope_snapshot)
                    AND content_studio.creator_json_is_versioned(progress_counts)
                )
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_template_analysis_tasks_idempotency
    ON content_studio.template_analysis_tasks (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_template_analysis_tasks_lease_token
    ON content_studio.template_analysis_tasks (lease_token)
    WHERE lease_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_template_analysis_tasks_creator_source
    ON content_studio.template_analysis_tasks (source_id, created_at DESC)
    WHERE source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_template_analysis_tasks_lease_expiry
    ON content_studio.template_analysis_tasks (lease_expires_at)
    WHERE lease_token IS NOT NULL;

-- A batch task is intentionally separate from independently leased video
-- work.  This lets a large account resume only failed videos without mutating
-- the batch's audit record.
CREATE TABLE IF NOT EXISTS content_studio.creator_video_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES content_studio.template_analysis_tasks(id)
        ON DELETE RESTRICT,
    video_id UUID NOT NULL REFERENCES content_studio.seed_materials(id)
        ON DELETE RESTRICT,
    source_id UUID REFERENCES content_studio.creator_sources(id)
        ON DELETE SET NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    idempotency_key TEXT,
    lease_owner TEXT,
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    lease_heartbeat_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_code TEXT,
    error TEXT,
    analysis_video_id TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT creator_video_tasks_mode_check
        CHECK (mode IN ('knowledge_only', 'benchmark_full', 'cluster')),
    CONSTRAINT creator_video_tasks_status_check
        CHECK (status IN (
            'queued', 'leased', 'running', 'succeeded', 'partial',
            'retryable', 'failed', 'cancelled', 'inaccessible', 'excluded'
        )),
    CONSTRAINT creator_video_tasks_stage_check
        CHECK (stage IN (
            'queued', 'download', 'extract', 'analyze', 'knowledge',
            'reconstruct', 'cluster', 'complete'
        )),
    CONSTRAINT creator_video_tasks_retry_check
        CHECK (retry_count >= 0 AND max_retries >= 0 AND retry_count <= max_retries),
    CONSTRAINT creator_video_tasks_idempotency_nonblank_check
        CHECK (idempotency_key IS NULL OR btrim(idempotency_key) <> ''),
    CONSTRAINT creator_video_tasks_lease_shape_check
        CHECK (
            (lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
            OR
            (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_video_tasks_task_video
    ON content_studio.creator_video_tasks (task_id, video_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_video_tasks_idempotency
    ON content_studio.creator_video_tasks (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_video_tasks_active_lease
    ON content_studio.creator_video_tasks (lease_token)
    WHERE lease_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_creator_video_tasks_lease_expiry
    ON content_studio.creator_video_tasks (lease_expires_at)
    WHERE status IN ('leased', 'running');
CREATE INDEX IF NOT EXISTS idx_creator_video_tasks_task_status
    ON content_studio.creator_video_tasks (task_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_creator_video_tasks_source_status
    ON content_studio.creator_video_tasks (source_id, status, created_at DESC)
    WHERE source_id IS NOT NULL;

-- video_analysis is an evidence service.  Add its foreign keys only when the
-- service schema is installed, so clean deployments can still run this domain
-- migration before the optional analyzer comes up.
DO $$
BEGIN
    IF to_regclass('video_analysis.videos') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conrelid = 'content_studio.creator_video_tasks'::regclass
             AND conname = 'creator_video_tasks_analysis_video_fkey'
       ) THEN
        ALTER TABLE content_studio.creator_video_tasks
            ADD CONSTRAINT creator_video_tasks_analysis_video_fkey
            FOREIGN KEY (analysis_video_id) REFERENCES video_analysis.videos(id)
            ON DELETE SET NULL;
    END IF;
END $$;

ALTER TABLE content_studio.material_reconstructions
    ADD COLUMN IF NOT EXISTS schema_version TEXT NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS material_id UUID,
    ADD COLUMN IF NOT EXISTS mode TEXT,
    ADD COLUMN IF NOT EXISTS facts_json JSONB,
    ADD COLUMN IF NOT EXISTS contract_json JSONB,
    ADD COLUMN IF NOT EXISTS warnings_json JSONB,
    ADD COLUMN IF NOT EXISTS analyzer_version TEXT,
    ADD COLUMN IF NOT EXISTS model_version TEXT,
    ADD COLUMN IF NOT EXISTS prompt_version TEXT,
    ADD COLUMN IF NOT EXISTS analysis_video_id TEXT,
    ADD COLUMN IF NOT EXISTS parent_reconstruction_id UUID,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,4);

-- seed_material_id is the legacy name.  Populate the explicit material_id
-- alias only from existing deterministic lineage; do not invent source links.
UPDATE content_studio.material_reconstructions
SET material_id = seed_material_id
WHERE material_id IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.material_reconstructions'::regclass
          AND conname = 'material_reconstructions_material_fkey'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT material_reconstructions_material_fkey
            FOREIGN KEY (material_id) REFERENCES content_studio.seed_materials(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.material_reconstructions'::regclass
          AND conname = 'material_reconstructions_parent_fkey'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT material_reconstructions_parent_fkey
            FOREIGN KEY (parent_reconstruction_id)
            REFERENCES content_studio.material_reconstructions(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.material_reconstructions'::regclass
          AND conname = 'material_reconstructions_material_alias_check'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT material_reconstructions_material_alias_check
            CHECK (material_id IS NULL OR material_id = seed_material_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.material_reconstructions'::regclass
          AND conname = 'material_reconstructions_mode_check'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT material_reconstructions_mode_check
            CHECK (mode IS NULL OR mode IN ('knowledge_only', 'benchmark_full'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.material_reconstructions'::regclass
          AND conname = 'material_reconstructions_confidence_score_check'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT material_reconstructions_confidence_score_check
            CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.material_reconstructions'::regclass
          AND conname = 'material_reconstructions_creator_payload_check'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT material_reconstructions_creator_payload_check
            CHECK (
                schema_version = 'legacy'
                OR (
                    material_id IS NOT NULL
                    AND mode IS NOT NULL
                    AND content_studio.creator_json_is_versioned(facts_json)
                    AND content_studio.creator_json_is_versioned(contract_json)
                    AND content_studio.creator_json_is_versioned(warnings_json)
                    AND NULLIF(btrim(analyzer_version), '') IS NOT NULL
                    AND NULLIF(btrim(model_version), '') IS NOT NULL
                    AND NULLIF(btrim(prompt_version), '') IS NOT NULL
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.material_reconstructions'::regclass
          AND conname = 'material_reconstructions_ready_evidence_check'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT material_reconstructions_ready_evidence_check
            CHECK (
                status <> 'ready'
                OR (
                    schema_version <> 'legacy'
                    AND content_studio.creator_json_is_versioned(facts_json)
                    AND content_studio.creator_json_is_versioned(contract_json)
                )
            );
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('video_analysis.videos') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conrelid = 'content_studio.material_reconstructions'::regclass
             AND conname = 'material_reconstructions_analysis_video_fkey'
       ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT material_reconstructions_analysis_video_fkey
            FOREIGN KEY (analysis_video_id) REFERENCES video_analysis.videos(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_material_reconstructions_creator_version
    ON content_studio.material_reconstructions (material_id, analysis_version)
    WHERE material_id IS NOT NULL AND schema_version <> 'legacy';
CREATE INDEX IF NOT EXISTS idx_material_reconstructions_creator_material_status
    ON content_studio.material_reconstructions (material_id, status, created_at DESC)
    WHERE material_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_material_reconstructions_analysis_video
    ON content_studio.material_reconstructions (analysis_video_id)
    WHERE analysis_video_id IS NOT NULL;

CREATE OR REPLACE FUNCTION content_studio.guard_creator_reconstruction()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent_material UUID;
    parent_version INTEGER;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'ready' THEN
            RAISE EXCEPTION 'ready_reconstruction_delete_forbidden'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;

    IF NEW.parent_reconstruction_id IS NOT NULL THEN
        SELECT material_id, analysis_version
          INTO parent_material, parent_version
          FROM content_studio.material_reconstructions
         WHERE id = NEW.parent_reconstruction_id;
        IF parent_material IS DISTINCT FROM NEW.material_id
           OR parent_version IS NULL
           OR parent_version >= NEW.analysis_version THEN
            RAISE EXCEPTION 'creator_reconstruction_parent_lineage_invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status = 'ready'
       AND (to_jsonb(NEW) - 'updated_at')
           IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
        RAISE EXCEPTION 'ready_reconstruction_immutable_create_child_version'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_creator_reconstruction
    ON content_studio.material_reconstructions;
CREATE TRIGGER trg_guard_creator_reconstruction
BEFORE INSERT OR UPDATE OR DELETE ON content_studio.material_reconstructions
FOR EACH ROW EXECUTE FUNCTION content_studio.guard_creator_reconstruction();

ALTER TABLE content_studio.prompt_templates
    ADD COLUMN IF NOT EXISTS template_schema_version TEXT NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS legacy_status TEXT,
    ADD COLUMN IF NOT EXISTS source_id UUID,
    ADD COLUMN IF NOT EXISTS template_kind TEXT NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS cluster_key TEXT,
    ADD COLUMN IF NOT EXISTS applicability JSONB,
    ADD COLUMN IF NOT EXISTS timeline JSONB,
    ADD COLUMN IF NOT EXISTS slots JSONB,
    ADD COLUMN IF NOT EXISTS excluded_specifics JSONB,
    ADD COLUMN IF NOT EXISTS production_cost JSONB,
    ADD COLUMN IF NOT EXISTS ai_feasibility JSONB,
    ADD COLUMN IF NOT EXISTS sample_count INTEGER,
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS archived_by TEXT;

-- Preserve an old unknown lifecycle value for inspection.  active/archived
-- have deterministic modern equivalents; no unknown row is silently adopted.
UPDATE content_studio.prompt_templates
SET legacy_status = COALESCE(legacy_status, status),
    status = 'adopted'
WHERE status = 'active';

UPDATE content_studio.prompt_templates
SET legacy_status = COALESCE(legacy_status, status),
    status = 'archived',
    archived_at = COALESCE(archived_at, NOW())
WHERE status = 'archive';

UPDATE content_studio.prompt_templates
SET legacy_status = COALESCE(legacy_status, status)
WHERE status NOT IN ('draft', 'adopted', 'archived')
  AND legacy_status IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.prompt_templates'::regclass
          AND conname = 'prompt_templates_creator_source_fkey'
    ) THEN
        ALTER TABLE content_studio.prompt_templates
            ADD CONSTRAINT prompt_templates_creator_source_fkey
            FOREIGN KEY (source_id) REFERENCES content_studio.creator_sources(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.prompt_templates'::regclass
          AND conname = 'prompt_templates_creator_kind_check'
    ) THEN
        ALTER TABLE content_studio.prompt_templates
            ADD CONSTRAINT prompt_templates_creator_kind_check
            CHECK (template_kind IN ('legacy', 'benchmark_abstract'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.prompt_templates'::regclass
          AND conname = 'prompt_templates_creator_status_check'
    ) THEN
        ALTER TABLE content_studio.prompt_templates
            ADD CONSTRAINT prompt_templates_creator_status_check
            CHECK (
                status IN ('draft', 'adopted', 'archived')
                OR (template_schema_version = 'legacy' AND legacy_status IS NOT NULL)
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.prompt_templates'::regclass
          AND conname = 'prompt_templates_creator_sample_count_check'
    ) THEN
        ALTER TABLE content_studio.prompt_templates
            ADD CONSTRAINT prompt_templates_creator_sample_count_check
            CHECK (sample_count IS NULL OR sample_count >= 1);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'content_studio.prompt_templates'::regclass
          AND conname = 'prompt_templates_creator_payload_check'
    ) THEN
        ALTER TABLE content_studio.prompt_templates
            ADD CONSTRAINT prompt_templates_creator_payload_check
            CHECK (
                template_schema_version = 'legacy'
                OR (
                    template_kind = 'benchmark_abstract'
                    AND source_id IS NOT NULL
                    AND NULLIF(btrim(cluster_key), '') IS NOT NULL
                    AND sample_count IS NOT NULL
                    AND content_studio.creator_json_is_versioned(applicability)
                    AND content_studio.creator_json_is_versioned(timeline)
                    AND content_studio.creator_json_is_versioned(slots)
                    AND content_studio.creator_json_is_versioned(excluded_specifics)
                    AND content_studio.creator_json_is_versioned(production_cost)
                    AND content_studio.creator_json_is_versioned(ai_feasibility)
                )
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_templates_creator_cluster_version
    ON content_studio.prompt_templates (source_id, cluster_key, version)
    WHERE source_id IS NOT NULL AND cluster_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_prompt_templates_creator_source_status
    ON content_studio.prompt_templates (source_id, status, created_at DESC)
    WHERE source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_prompt_templates_creator_kind
    ON content_studio.prompt_templates (template_kind, status, created_at DESC)
    WHERE template_kind = 'benchmark_abstract';

-- DES-015: canonical relational source lineage replaces the historical UUID
-- arrays for all new creator templates.  Arrays remain readable for legacy
-- callers during the compatibility window.
CREATE TABLE IF NOT EXISTS content_studio.template_source_materials (
    template_id UUID NOT NULL REFERENCES content_studio.prompt_templates(id)
        ON DELETE RESTRICT,
    material_id UUID NOT NULL REFERENCES content_studio.seed_materials(id)
        ON DELETE RESTRICT,
    reconstruction_id UUID NOT NULL
        REFERENCES content_studio.material_reconstructions(id)
        ON DELETE RESTRICT,
    evidence_json JSONB NOT NULL DEFAULT
        '{"schema_version":"template_evidence.v1"}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (template_id, material_id, reconstruction_id),
    CONSTRAINT template_source_materials_evidence_check
        CHECK (content_studio.creator_json_is_versioned(evidence_json))
);
CREATE INDEX IF NOT EXISTS idx_template_source_materials_material
    ON content_studio.template_source_materials (material_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_template_source_materials_reconstruction
    ON content_studio.template_source_materials (reconstruction_id, created_at DESC);

CREATE OR REPLACE FUNCTION content_studio.guard_template_source_material()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    reconstruction_material UUID;
    template_source UUID;
    material_source UUID;
    template_status TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT status INTO template_status
        FROM content_studio.prompt_templates WHERE id = OLD.template_id;
        IF template_status = 'adopted' THEN
            RAISE EXCEPTION 'adopted_template_source_lineage_immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;

    SELECT material_id INTO reconstruction_material
    FROM content_studio.material_reconstructions WHERE id = NEW.reconstruction_id;
    IF reconstruction_material IS DISTINCT FROM NEW.material_id THEN
        RAISE EXCEPTION 'template_source_reconstruction_material_mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT source_id INTO template_source
    FROM content_studio.prompt_templates WHERE id = NEW.template_id;
    SELECT source_id INTO material_source
    FROM content_studio.seed_materials WHERE id = NEW.material_id;
    IF template_source IS NOT NULL AND material_source IS NOT NULL
       AND template_source IS DISTINCT FROM material_source THEN
        RAISE EXCEPTION 'template_source_cross_creator_forbidden'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_template_source_material
    ON content_studio.template_source_materials;
CREATE TRIGGER trg_guard_template_source_material
BEFORE INSERT OR UPDATE OR DELETE ON content_studio.template_source_materials
FOR EACH ROW EXECUTE FUNCTION content_studio.guard_template_source_material();

-- DES-016: one request may persist up to three structurally diverse candidate
-- templates.  This table is explicitly not pipeline.experiments.
CREATE TABLE IF NOT EXISTS content_studio.template_applications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    candidate_rank SMALLINT NOT NULL,
    idempotency_key TEXT NOT NULL,
    template_id UUID NOT NULL REFERENCES content_studio.prompt_templates(id)
        ON DELETE RESTRICT,
    template_version INTEGER NOT NULL,
    template_snapshot JSONB NOT NULL,
    snapshot_hash TEXT NOT NULL,
    sku_id VARCHAR(64) NOT NULL REFERENCES public.mvp_sku(id) ON DELETE RESTRICT,
    audience_record_id UUID NOT NULL REFERENCES pipeline.audience_records(id)
        ON DELETE RESTRICT,
    intent TEXT NOT NULL,
    hard_filter JSONB NOT NULL DEFAULT
        '{"schema_version":"template_hard_filter.v1"}'::jsonb,
    scores JSONB NOT NULL DEFAULT
        '{"schema_version":"template_scores.v1"}'::jsonb,
    reasons JSONB NOT NULL DEFAULT
        '{"schema_version":"template_reasons.v1"}'::jsonb,
    risk JSONB NOT NULL DEFAULT
        '{"schema_version":"template_risk.v1"}'::jsonb,
    status TEXT NOT NULL DEFAULT 'candidate',
    selected_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT template_applications_candidate_rank_check
        CHECK (candidate_rank BETWEEN 1 AND 3),
    CONSTRAINT template_applications_idempotency_nonblank_check
        CHECK (btrim(idempotency_key) <> ''),
    CONSTRAINT template_applications_template_version_check
        CHECK (template_version >= 1),
    CONSTRAINT template_applications_snapshot_hash_check
        CHECK (snapshot_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT template_applications_intent_check
        CHECK (intent IN ('planting', 'harvest', 'soft_ad', 'hard_ad')),
    CONSTRAINT template_applications_status_check
        CHECK (status IN (
            'candidate', 'selected', 'script_created', 'trial_authorized',
            'trial_generated', 'rejected', 'expired', 'archived'
        )),
    CONSTRAINT template_applications_snapshot_check
        CHECK (content_studio.creator_json_is_versioned(template_snapshot)),
    CONSTRAINT template_applications_hard_filter_check
        CHECK (content_studio.creator_json_is_versioned(hard_filter)),
    CONSTRAINT template_applications_scores_check
        CHECK (content_studio.creator_json_is_versioned(scores)),
    CONSTRAINT template_applications_reasons_check
        CHECK (content_studio.creator_json_is_versioned(reasons)),
    CONSTRAINT template_applications_risk_check
        CHECK (content_studio.creator_json_is_versioned(risk)),
    CONSTRAINT template_applications_request_rank_unique
        UNIQUE (request_id, candidate_rank),
    CONSTRAINT template_applications_idempotency_rank_unique
        UNIQUE (idempotency_key, candidate_rank)
);
CREATE INDEX IF NOT EXISTS idx_template_applications_sku_audience_created
    ON content_studio.template_applications (sku_id, audience_record_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_template_applications_template_status
    ON content_studio.template_applications (template_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_template_applications_trial_ready
    ON content_studio.template_applications (created_at DESC)
    WHERE status IN ('selected', 'script_created', 'trial_authorized');

CREATE OR REPLACE FUNCTION content_studio.guard_template_application()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'template_application_delete_forbidden'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.request_id IS DISTINCT FROM OLD.request_id
       OR NEW.candidate_rank IS DISTINCT FROM OLD.candidate_rank
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.template_id IS DISTINCT FROM OLD.template_id
       OR NEW.template_version IS DISTINCT FROM OLD.template_version
       OR NEW.template_snapshot IS DISTINCT FROM OLD.template_snapshot
       OR NEW.snapshot_hash IS DISTINCT FROM OLD.snapshot_hash
       OR NEW.sku_id IS DISTINCT FROM OLD.sku_id
       OR NEW.audience_record_id IS DISTINCT FROM OLD.audience_record_id
       OR NEW.intent IS DISTINCT FROM OLD.intent
       OR NEW.hard_filter IS DISTINCT FROM OLD.hard_filter
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'template_application_snapshot_immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_template_application
    ON content_studio.template_applications;
CREATE TRIGGER trg_guard_template_application
BEFORE UPDATE OR DELETE ON content_studio.template_applications
FOR EACH ROW EXECUTE FUNCTION content_studio.guard_template_application();

CREATE OR REPLACE FUNCTION content_studio.guard_creator_prompt_template()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    immutable_new JSONB;
    immutable_old JSONB;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'adopted' THEN
            RAISE EXCEPTION 'adopted_template_delete_forbidden'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;

    -- New benchmark templates may be adopted only after their canonical source
    -- relation is written.  Legacy generic templates retain their old path.
    IF NEW.status = 'adopted'
       AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'adopted')
       AND NEW.template_kind = 'benchmark_abstract'
       AND NOT EXISTS (
           SELECT 1 FROM content_studio.template_source_materials source_link
           WHERE source_link.template_id = NEW.id
       ) THEN
        RAISE EXCEPTION 'benchmark_template_requires_source_lineage_before_adoption'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status = 'adopted' THEN
        IF NEW.status NOT IN ('adopted', 'archived') THEN
            RAISE EXCEPTION 'adopted_template_cannot_reopen'
                USING ERRCODE = '23514';
        END IF;

        immutable_new := to_jsonb(NEW) - ARRAY[
            'updated_at', 'usage_count', 'ctr_observed', 'cvr_observed',
            'confidence', 'status', 'archived_at', 'archived_by'
        ];
        immutable_old := to_jsonb(OLD) - ARRAY[
            'updated_at', 'usage_count', 'ctr_observed', 'cvr_observed',
            'confidence', 'status', 'archived_at', 'archived_by'
        ];
        IF immutable_new IS DISTINCT FROM immutable_old THEN
            RAISE EXCEPTION 'adopted_template_payload_immutable_create_child_version'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status = 'archived'
       AND NEW.status IS DISTINCT FROM 'archived' THEN
        RAISE EXCEPTION 'archived_template_cannot_reopen_create_child_version'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_creator_prompt_template
    ON content_studio.prompt_templates;
CREATE TRIGGER trg_guard_creator_prompt_template
BEFORE INSERT OR UPDATE OR DELETE ON content_studio.prompt_templates
FOR EACH ROW EXECUTE FUNCTION content_studio.guard_creator_prompt_template();

-- -------------------------------------------------------------------------
-- DES-017 / DES-018: template-to-script/asset lineage.  Existing production
-- and experiment rows retain their historical purpose after a deterministic
-- backfill; template_trial is an explicit non-experiment path.
-- -------------------------------------------------------------------------
ALTER TABLE pipeline.scripts
    ADD COLUMN IF NOT EXISTS content_contract_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS template_application_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.scripts'::regclass
          AND conname = 'scripts_template_application_fkey'
    ) THEN
        ALTER TABLE pipeline.scripts
            ADD CONSTRAINT scripts_template_application_fkey
            FOREIGN KEY (template_application_id)
            REFERENCES content_studio.template_applications(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.scripts'::regclass
          AND conname = 'scripts_creator_contract_schema_check'
    ) THEN
        ALTER TABLE pipeline.scripts
            ADD CONSTRAINT scripts_creator_contract_schema_check
            CHECK (
                content_contract_schema_version IS NULL
                OR content_contract_schema_version IN ('creator_template.v1')
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.scripts'::regclass
          AND conname = 'scripts_creator_template_contract_check'
    ) THEN
        ALTER TABLE pipeline.scripts
            ADD CONSTRAINT scripts_creator_template_contract_check
            CHECK (
                template_application_id IS NULL
                OR (
                    content_contract_schema_version = 'creator_template.v1'
                    AND content_studio.creator_json_is_versioned(content_contract)
                    AND jsonb_typeof(content_contract -> 'reference_template') = 'object'
                    AND (content_contract -> 'reference_template') ? 'id'
                    AND (content_contract -> 'reference_template') ? 'version'
                    AND (content_contract -> 'reference_template') ? 'snapshot_hash'
                    AND (content_contract -> 'reference_template') ? 'application_id'
                    AND jsonb_typeof(
                        content_contract -> 'reference_template' -> 'source_video_ids'
                    ) = 'array'
                )
            );
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_scripts_template_application
    ON pipeline.scripts (template_application_id, created_at DESC)
    WHERE template_application_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS pipeline.script_template_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    script_id UUID NOT NULL REFERENCES pipeline.scripts(id) ON DELETE RESTRICT,
    template_id UUID NOT NULL REFERENCES content_studio.prompt_templates(id)
        ON DELETE RESTRICT,
    application_id UUID REFERENCES content_studio.template_applications(id)
        ON DELETE RESTRICT,
    template_version INTEGER NOT NULL,
    snapshot_hash TEXT NOT NULL,
    template_snapshot JSONB NOT NULL,
    source_material_ids UUID[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT script_template_sources_script_template_unique UNIQUE (script_id, template_id),
    CONSTRAINT script_template_sources_version_check CHECK (template_version >= 1),
    CONSTRAINT script_template_sources_snapshot_hash_check
        CHECK (snapshot_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT script_template_sources_snapshot_check
        CHECK (content_studio.creator_json_is_versioned(template_snapshot)),
    CONSTRAINT script_template_sources_material_ids_nonempty_check
        CHECK (cardinality(source_material_ids) >= 1)
);
CREATE INDEX IF NOT EXISTS idx_script_template_sources_template
    ON pipeline.script_template_sources (template_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_script_template_sources_application
    ON pipeline.script_template_sources (application_id)
    WHERE application_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_script_template_sources_materials
    ON pipeline.script_template_sources USING GIN (source_material_ids);

CREATE OR REPLACE FUNCTION pipeline.guard_script_template_source()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    template_state TEXT;
    current_template_version INTEGER;
    application_template UUID;
    application_version INTEGER;
    application_hash TEXT;
    script_application UUID;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'script_template_source_lineage_immutable'
            USING ERRCODE = '23514';
    END IF;

    SELECT status, version INTO template_state, current_template_version
    FROM content_studio.prompt_templates WHERE id = NEW.template_id;
    IF template_state IS DISTINCT FROM 'adopted'
       OR current_template_version IS DISTINCT FROM NEW.template_version THEN
        RAISE EXCEPTION 'script_template_source_requires_current_adopted_template'
            USING ERRCODE = '23514';
    END IF;

    SELECT template_application_id INTO script_application
    FROM pipeline.scripts WHERE id = NEW.script_id;
    IF NEW.application_id IS DISTINCT FROM script_application THEN
        RAISE EXCEPTION 'script_template_source_application_mismatch'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.application_id IS NOT NULL THEN
        SELECT template_id, template_version, snapshot_hash
          INTO application_template, application_version, application_hash
          FROM content_studio.template_applications
         WHERE id = NEW.application_id;
        IF application_template IS DISTINCT FROM NEW.template_id
           OR application_version IS DISTINCT FROM NEW.template_version
           OR application_hash IS DISTINCT FROM NEW.snapshot_hash THEN
            RAISE EXCEPTION 'script_template_source_application_snapshot_mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_script_template_source
    ON pipeline.script_template_sources;
CREATE TRIGGER trg_guard_script_template_source
BEFORE INSERT OR UPDATE OR DELETE ON pipeline.script_template_sources
FOR EACH ROW EXECUTE FUNCTION pipeline.guard_script_template_source();

ALTER TABLE pipeline.assets
    ADD COLUMN IF NOT EXISTS generation_purpose TEXT,
    ADD COLUMN IF NOT EXISTS template_application_id UUID,
    ADD COLUMN IF NOT EXISTS generation_approval_gate_id UUID,
    ADD COLUMN IF NOT EXISTS generation_authorization_snapshot JSONB;

-- Historical experiment assets must retain their real semantics instead of
-- being silently defaulted to production.
UPDATE pipeline.assets
SET generation_purpose = CASE
    WHEN experiment_id IS NOT NULL OR experiment_arm_id IS NOT NULL THEN 'experiment'
    ELSE 'production'
END
WHERE generation_purpose IS NULL;

ALTER TABLE pipeline.assets
    ALTER COLUMN generation_purpose SET DEFAULT 'production';
ALTER TABLE pipeline.assets
    ALTER COLUMN generation_purpose SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.assets'::regclass
          AND conname = 'assets_template_application_fkey'
    ) THEN
        ALTER TABLE pipeline.assets
            ADD CONSTRAINT assets_template_application_fkey
            FOREIGN KEY (template_application_id)
            REFERENCES content_studio.template_applications(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.assets'::regclass
          AND conname = 'assets_generation_approval_gate_fkey'
    ) THEN
        ALTER TABLE pipeline.assets
            ADD CONSTRAINT assets_generation_approval_gate_fkey
            FOREIGN KEY (generation_approval_gate_id) REFERENCES mcp.human_gates(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.assets'::regclass
          AND conname = 'assets_generation_purpose_check'
    ) THEN
        ALTER TABLE pipeline.assets
            ADD CONSTRAINT assets_generation_purpose_check
            CHECK (generation_purpose IN ('production', 'experiment', 'template_trial'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.assets'::regclass
          AND conname = 'assets_template_trial_contract_check'
    ) THEN
        ALTER TABLE pipeline.assets
            ADD CONSTRAINT assets_template_trial_contract_check
            CHECK (
                generation_purpose <> 'template_trial'
                OR (
                    experiment_id IS NULL
                    AND experiment_arm_id IS NULL
                    AND template_application_id IS NOT NULL
                    AND generation_approval_gate_id IS NOT NULL
                    AND content_studio.creator_json_is_versioned(
                        generation_authorization_snapshot
                    )
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.assets'::regclass
          AND conname = 'assets_nontrial_template_fields_empty_check'
    ) THEN
        ALTER TABLE pipeline.assets
            ADD CONSTRAINT assets_nontrial_template_fields_empty_check
            CHECK (
                generation_purpose = 'template_trial'
                OR (
                    template_application_id IS NULL
                    AND generation_approval_gate_id IS NULL
                    AND generation_authorization_snapshot IS NULL
                )
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_assets_generation_purpose_created
    ON pipeline.assets (generation_purpose, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_template_application
    ON pipeline.assets (template_application_id, scene_no, created_at DESC)
    WHERE template_application_id IS NOT NULL;

CREATE OR REPLACE FUNCTION pipeline.guard_template_trial_asset()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    approved BOOLEAN;
    app_ok BOOLEAN;
    script_ok BOOLEAN;
BEGIN
    IF NEW.generation_purpose <> 'template_trial' THEN
        RETURN NEW;
    END IF;

    SELECT (gate.decision = 'approved')
      INTO approved
      FROM mcp.human_gates gate
     WHERE gate.id = NEW.generation_approval_gate_id;
    IF approved IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'template_trial_requires_approved_human_gate'
            USING ERRCODE = '23514';
    END IF;

    SELECT application.status IN ('trial_authorized', 'trial_generated')
      INTO app_ok
      FROM content_studio.template_applications application
     WHERE application.id = NEW.template_application_id;
    IF app_ok IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'template_trial_application_not_authorized'
            USING ERRCODE = '23514';
    END IF;

    SELECT script.status = 'adopted'
       AND script.template_application_id = NEW.template_application_id
      INTO script_ok
      FROM pipeline.scripts script
     WHERE script.id = NEW.script_id;
    IF script_ok IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'template_trial_requires_adopted_matching_script'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_template_trial_asset ON pipeline.assets;
CREATE TRIGGER trg_guard_template_trial_asset
BEFORE INSERT OR UPDATE OF generation_purpose, template_application_id,
    generation_approval_gate_id, generation_authorization_snapshot,
    experiment_id, experiment_arm_id, script_id
ON pipeline.assets
FOR EACH ROW EXECUTE FUNCTION pipeline.guard_template_trial_asset();

-- -------------------------------------------------------------------------
-- DES-019: prescreen reports are versioned evidence, never overwritten.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_studio.fidelity_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asset_id UUID NOT NULL REFERENCES pipeline.assets(id) ON DELETE RESTRICT,
    segment_no SMALLINT NOT NULL,
    source_reconstruction_id UUID NOT NULL
        REFERENCES content_studio.material_reconstructions(id) ON DELETE RESTRICT,
    parent_report_id UUID REFERENCES content_studio.fidelity_reports(id)
        ON DELETE RESTRICT,
    report_version INTEGER NOT NULL DEFAULT 1,
    input_hash TEXT NOT NULL,
    weights JSONB NOT NULL,
    component_scores JSONB NOT NULL,
    evidence JSONB NOT NULL,
    technical_gate JSONB NOT NULL,
    repair_delta JSONB NOT NULL,
    judge_version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fidelity_reports_segment_no_check CHECK (segment_no >= 1),
    CONSTRAINT fidelity_reports_version_check CHECK (report_version >= 1),
    CONSTRAINT fidelity_reports_input_hash_check CHECK (input_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT fidelity_reports_judge_version_check CHECK (btrim(judge_version) <> ''),
    CONSTRAINT fidelity_reports_status_check
        CHECK (status IN ('completed', 'partial', 'prescreen_failed')),
    CONSTRAINT fidelity_reports_weights_check
        CHECK (content_studio.creator_json_is_versioned(weights)),
    CONSTRAINT fidelity_reports_component_scores_check
        CHECK (content_studio.creator_json_is_versioned(component_scores)),
    CONSTRAINT fidelity_reports_evidence_check
        CHECK (content_studio.creator_json_is_versioned(evidence)),
    CONSTRAINT fidelity_reports_technical_gate_check
        CHECK (content_studio.creator_json_is_versioned(technical_gate)),
    CONSTRAINT fidelity_reports_repair_delta_check
        CHECK (content_studio.creator_json_is_versioned(repair_delta)),
    CONSTRAINT fidelity_reports_asset_segment_version_unique
        UNIQUE (asset_id, segment_no, report_version),
    CONSTRAINT fidelity_reports_input_unique
        UNIQUE (asset_id, segment_no, input_hash)
);
CREATE INDEX IF NOT EXISTS idx_fidelity_reports_asset_segment
    ON content_studio.fidelity_reports (asset_id, segment_no, report_version DESC);
CREATE INDEX IF NOT EXISTS idx_fidelity_reports_reconstruction
    ON content_studio.fidelity_reports (source_reconstruction_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fidelity_reports_parent
    ON content_studio.fidelity_reports (parent_report_id)
    WHERE parent_report_id IS NOT NULL;

CREATE OR REPLACE FUNCTION content_studio.guard_fidelity_report()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent_asset UUID;
    parent_segment SMALLINT;
    parent_version INTEGER;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'fidelity_report_append_only'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.parent_report_id IS NULL AND NEW.report_version <> 1 THEN
        RAISE EXCEPTION 'fidelity_report_root_must_be_version_one'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.parent_report_id IS NOT NULL THEN
        SELECT asset_id, segment_no, report_version
          INTO parent_asset, parent_segment, parent_version
          FROM content_studio.fidelity_reports
         WHERE id = NEW.parent_report_id;
        IF parent_asset IS DISTINCT FROM NEW.asset_id
           OR parent_segment IS DISTINCT FROM NEW.segment_no
           OR parent_version IS NULL
           OR parent_version >= NEW.report_version THEN
            RAISE EXCEPTION 'fidelity_report_parent_lineage_invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_fidelity_report ON content_studio.fidelity_reports;
CREATE TRIGGER trg_guard_fidelity_report
BEFORE INSERT OR UPDATE OR DELETE ON content_studio.fidelity_reports
FOR EACH ROW EXECUTE FUNCTION content_studio.guard_fidelity_report();

-- This companion view deliberately layers onto the canonical full-lineage
-- view rather than reconstructing it.  The runtime's canonical view has
-- evolved beyond the checked-in 052 definition; layering prevents this
-- migration from dropping unrelated lineage columns while exposing template
-- trial provenance to API readers.
CREATE OR REPLACE VIEW pipeline.v_asset_creator_template_lineage AS
SELECT
    lineage.*,
    asset.generation_purpose,
    asset.template_application_id,
    asset.generation_approval_gate_id,
    asset.generation_authorization_snapshot,
    source_link.template_id AS reference_template_id,
    source_link.template_version AS reference_template_version,
    source_link.snapshot_hash AS reference_template_snapshot_hash,
    source_link.source_material_ids AS reference_source_material_ids,
    source_link.application_id AS script_template_application_id,
    application.request_id AS template_application_request_id,
    application.candidate_rank AS template_application_candidate_rank,
    application.status AS template_application_status,
    template.source_id AS template_source_id,
    template.template_kind,
    template.status AS template_status
FROM pipeline.v_asset_full_lineage lineage
JOIN pipeline.assets asset ON asset.id = lineage.asset_id
LEFT JOIN pipeline.script_template_sources source_link
    ON source_link.script_id = asset.script_id
LEFT JOIN content_studio.template_applications application
    ON application.id = asset.template_application_id
LEFT JOIN content_studio.prompt_templates template
    ON template.id = source_link.template_id;

-- Match the repository's normal updated_at convention without requiring this
-- migration to depend on a particular bootstrap order in a partial install.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_creator_sources_touch ON content_studio.creator_sources;
        CREATE TRIGGER trg_creator_sources_touch
            BEFORE UPDATE ON content_studio.creator_sources
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_creator_sync_runs_touch ON content_studio.creator_sync_runs;
        CREATE TRIGGER trg_creator_sync_runs_touch
            BEFORE UPDATE ON content_studio.creator_sync_runs
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_creator_knowledge_bindings_touch ON content_studio.creator_knowledge_bindings;
        CREATE TRIGGER trg_creator_knowledge_bindings_touch
            BEFORE UPDATE ON content_studio.creator_knowledge_bindings
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_creator_video_tasks_touch ON content_studio.creator_video_tasks;
        CREATE TRIGGER trg_creator_video_tasks_touch
            BEFORE UPDATE ON content_studio.creator_video_tasks
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_template_analysis_tasks_creator_touch
            ON content_studio.template_analysis_tasks;
        CREATE TRIGGER trg_template_analysis_tasks_creator_touch
            BEFORE UPDATE ON content_studio.template_analysis_tasks
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_material_reconstructions_creator_touch
            ON content_studio.material_reconstructions;
        CREATE TRIGGER trg_material_reconstructions_creator_touch
            BEFORE UPDATE ON content_studio.material_reconstructions
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_prompt_templates_creator_touch
            ON content_studio.prompt_templates;
        CREATE TRIGGER trg_prompt_templates_creator_touch
            BEFORE UPDATE ON content_studio.prompt_templates
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;

COMMENT ON TABLE content_studio.creator_sources IS
    'Creator-learning canonical source identity; physical deletion is blocked, archive by sync_status/archived_at.';
COMMENT ON TABLE content_studio.creator_sync_runs IS
    'Append-only creator sync audit. One queued/running/partial/auth_required run owns a source cursor.';
COMMENT ON TABLE content_studio.creator_video_tasks IS
    'Independently leased, resumable per-video work item for a creator batch; video_analysis is evidence only.';
COMMENT ON TABLE content_studio.template_source_materials IS
    'Canonical template-to-material-to-reconstruction many-to-many lineage for creator benchmark templates.';
COMMENT ON TABLE content_studio.template_applications IS
    'Up to three immutable candidate snapshots per matching request; explicitly not an advertising experiment.';
COMMENT ON TABLE pipeline.script_template_sources IS
    'Immutable adopted-template snapshot lineage injected into a generated script.';
COMMENT ON COLUMN pipeline.assets.generation_purpose IS
    'production/experiment/template_trial. template_trial is a non-experiment path requiring a selected application and approved human gate.';
COMMENT ON TABLE content_studio.fidelity_reports IS
    'Append-only versioned structural-fidelity and technical-prescreen evidence; total score is not a market-performance claim.';
COMMENT ON VIEW pipeline.v_asset_creator_template_lineage IS
    'Creator-template companion lineage layered on v_asset_full_lineage without changing its historical column contract.';
