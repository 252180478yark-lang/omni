-- P0 single-video production atom.  This is additive and intentionally lives
-- in pipeline: it does not create a fourth production lineage for ecommerce
-- visuals or AI insert-video experiments.

CREATE TABLE IF NOT EXISTS pipeline.production_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id VARCHAR(64) NOT NULL REFERENCES mvp_sku(id) ON DELETE RESTRICT,
    audience_record_id UUID NOT NULL REFERENCES pipeline.audience_records(id) ON DELETE RESTRICT,
    audience_portrait_id UUID REFERENCES pipeline.audience_portraits(id) ON DELETE RESTRICT,
    intent TEXT NOT NULL DEFAULT 'planting',
    contract_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    baseline_manifest JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'baseline_ready',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT production_orders_intent_check CHECK (intent = 'planting'),
    CONSTRAINT production_orders_contract_version_check CHECK (btrim(contract_version) <> ''),
    CONSTRAINT production_orders_baseline_manifest_check CHECK (jsonb_typeof(baseline_manifest) = 'object'),
    CONSTRAINT production_orders_status_check CHECK (status IN (
        'baseline_ready','truth_ready','spec_ready','awaiting_script_selection',
        'prompt_ready','awaiting_generation_approval','generating','raw_qa',
        'raw_passed','final_qa','ready_to_release','released','cancelled',
        'raw_rejected','final_rejected'
    ))
);

CREATE TABLE IF NOT EXISTS pipeline.order_truth_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL UNIQUE REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    snapshot JSONB NOT NULL,
    snapshot_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT order_truth_snapshots_object_check CHECK (jsonb_typeof(snapshot) = 'object'),
    CONSTRAINT order_truth_snapshots_hash_check CHECK (snapshot_hash ~ '^[a-f0-9]{64}$')
);

CREATE TABLE IF NOT EXISTS pipeline.production_content_specs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    truth_snapshot_id UUID NOT NULL REFERENCES pipeline.order_truth_snapshots(id) ON DELETE RESTRICT,
    spec JSONB NOT NULL,
    spec_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT production_content_specs_object_check CHECK (jsonb_typeof(spec) = 'object'),
    CONSTRAINT production_content_specs_hash_check CHECK (spec_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT production_content_specs_order_version_unique UNIQUE (production_order_id, version)
);

CREATE TABLE IF NOT EXISTS pipeline.production_script_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    content_spec_id UUID NOT NULL REFERENCES pipeline.production_content_specs(id) ON DELETE RESTRICT,
    script_id UUID NOT NULL REFERENCES pipeline.scripts(id) ON DELETE RESTRICT,
    candidate_slot SMALLINT NOT NULL CHECK (candidate_slot IN (1, 2)),
    deterministic_gate JSONB NOT NULL,
    critic_gate JSONB NOT NULL DEFAULT '{"status":"pending"}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending_review' CHECK (status IN ('pending_review','passed','failed')),
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT production_script_reviews_deterministic_gate_check CHECK (jsonb_typeof(deterministic_gate) = 'object'),
    CONSTRAINT production_script_reviews_critic_gate_check CHECK (jsonb_typeof(critic_gate) = 'object'),
    CONSTRAINT production_script_reviews_slot_unique UNIQUE (production_order_id, candidate_slot),
    CONSTRAINT production_script_reviews_script_unique UNIQUE (production_order_id, script_id)
);

CREATE TABLE IF NOT EXISTS pipeline.production_prompt_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    content_spec_id UUID NOT NULL REFERENCES pipeline.production_content_specs(id) ON DELETE RESTRICT,
    script_id UUID NOT NULL REFERENCES pipeline.scripts(id) ON DELETE RESTRICT,
    prompt_source JSONB NOT NULL,
    prompt_source_hash TEXT NOT NULL UNIQUE,
    requested_provider TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    reference_manifest JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT production_prompt_sources_object_check CHECK (jsonb_typeof(prompt_source) = 'object'),
    CONSTRAINT production_prompt_sources_reference_manifest_check CHECK (jsonb_typeof(reference_manifest) = 'object'),
    CONSTRAINT production_prompt_sources_hash_check CHECK (prompt_source_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT production_prompt_sources_seedance_only CHECK (requested_provider = 'seedance'),
    CONSTRAINT production_prompt_sources_order_script_unique UNIQUE (production_order_id, script_id)
);

CREATE TABLE IF NOT EXISTS pipeline.production_generation_attempts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    prompt_source_id UUID NOT NULL REFERENCES pipeline.production_prompt_sources(id) ON DELETE RESTRICT,
    generation_set_id UUID REFERENCES pipeline.video_generation_sets(id) ON DELETE RESTRICT,
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    approval_hash TEXT NOT NULL,
    requested_provider TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    actual_provider TEXT,
    actual_model TEXT,
    remote_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created','running','succeeded','failed','recoverable')),
    error_category TEXT,
    raw_asset_id UUID REFERENCES pipeline.assets(id) ON DELETE RESTRICT,
    duration_ms INTEGER,
    cost_cents INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT production_generation_attempts_approval_hash_check CHECK (approval_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT production_generation_attempts_order_attempt_unique UNIQUE (production_order_id, attempt_no),
    CONSTRAINT production_generation_attempts_active_unique UNIQUE (production_order_id, approval_hash)
        DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE IF NOT EXISTS pipeline.production_timelines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    generation_attempt_id UUID NOT NULL REFERENCES pipeline.production_generation_attempts(id) ON DELETE RESTRICT,
    timeline_spec JSONB NOT NULL,
    timeline_hash TEXT NOT NULL UNIQUE,
    final_asset_id UUID REFERENCES pipeline.assets(id) ON DELETE RESTRICT,
    compose_log JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','composing','succeeded','failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT production_timelines_spec_check CHECK (jsonb_typeof(timeline_spec) = 'object'),
    CONSTRAINT production_timelines_log_check CHECK (jsonb_typeof(compose_log) = 'object'),
    CONSTRAINT production_timelines_hash_check CHECK (timeline_hash ~ '^[a-f0-9]{64}$')
);

CREATE TABLE IF NOT EXISTS pipeline.production_qa_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    stage TEXT NOT NULL CHECK (stage IN ('raw','final')),
    asset_id UUID NOT NULL REFERENCES pipeline.assets(id) ON DELETE RESTRICT,
    report JSONB NOT NULL,
    passed BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT production_qa_reports_report_check CHECK (jsonb_typeof(report) = 'object')
);

CREATE TABLE IF NOT EXISTS pipeline.release_packages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL UNIQUE REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    final_asset_id UUID NOT NULL REFERENCES pipeline.assets(id) ON DELETE RESTRICT,
    manifest JSONB NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    released_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT release_packages_manifest_check CHECK (jsonb_typeof(manifest) = 'object'),
    CONSTRAINT release_packages_hash_check CHECK (manifest_hash ~ '^[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_production_orders_sku_status
    ON pipeline.production_orders (sku_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_production_generation_attempts_status
    ON pipeline.production_generation_attempts (production_order_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_production_qa_reports_order_stage
    ON pipeline.production_qa_reports (production_order_id, stage, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_production_script_reviews_one_selected
    ON pipeline.production_script_reviews (production_order_id)
    WHERE selected;
