-- P0 real execution-content ↔ audience vector pre-match.
--
-- This is intentionally separate from 086's transparent lexical evidence:
-- it persists the actual candidate PromptSource preview / frozen PromptSource
-- that was embedded, together with the frozen audience source and model
-- identity.  It does not create an experiment arm or declare a winner.

CREATE TABLE IF NOT EXISTS pipeline.production_vector_match_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL
        REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    content_spec_id UUID NOT NULL
        REFERENCES pipeline.production_content_specs(id) ON DELETE RESTRICT,
    script_id UUID NOT NULL
        REFERENCES pipeline.scripts(id) ON DELETE RESTRICT,
    prompt_source_id UUID
        REFERENCES pipeline.production_prompt_sources(id) ON DELETE RESTRICT,
    stage TEXT NOT NULL CHECK (stage IN ('candidate', 'planned')),
    candidate_slot SMALLINT CHECK (candidate_slot IN (1, 2)),
    execution_source_kind TEXT NOT NULL
        CHECK (execution_source_kind IN ('candidate_prompt_preview', 'frozen_prompt_source')),
    execution_source_hash TEXT NOT NULL,
    audience_source_kind TEXT NOT NULL
        CHECK (audience_source_kind IN ('portrait', 'record_fallback')),
    audience_source_hash TEXT NOT NULL,
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    matcher_version TEXT NOT NULL,
    report_status TEXT NOT NULL CHECK (report_status IN ('scored', 'unscored')),
    report JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT production_vector_match_reports_execution_hash_check
        CHECK (execution_source_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT production_vector_match_reports_audience_hash_check
        CHECK (audience_source_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT production_vector_match_reports_report_check
        CHECK (jsonb_typeof(report) = 'object'),
    CONSTRAINT production_vector_match_reports_stage_source_check CHECK (
        (stage = 'candidate' AND prompt_source_id IS NULL AND candidate_slot IS NOT NULL
         AND execution_source_kind = 'candidate_prompt_preview')
        OR
        (stage = 'planned' AND prompt_source_id IS NOT NULL
         AND execution_source_kind = 'frozen_prompt_source')
    ),
    CONSTRAINT production_vector_match_reports_unique
        UNIQUE (
            production_order_id, script_id, stage, execution_source_hash,
            audience_source_hash, embedding_provider, embedding_model, matcher_version
        )
);

CREATE INDEX IF NOT EXISTS idx_production_vector_match_reports_order_stage
    ON pipeline.production_vector_match_reports (production_order_id, stage, created_at DESC);
