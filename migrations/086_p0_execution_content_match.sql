-- P0 execution-content audience-match evidence.  This stays inside the
-- planting-video atom: it records only the selected script, frozen prompt,
-- reference manifest and the actual post-production audio plan.  It neither
-- imports ecommerce-visual lineage nor treats a proxy score as a winner.

CREATE TABLE IF NOT EXISTS pipeline.production_content_match_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    production_order_id UUID NOT NULL
        REFERENCES pipeline.production_orders(id) ON DELETE RESTRICT,
    prompt_source_id UUID NOT NULL
        REFERENCES pipeline.production_prompt_sources(id) ON DELETE RESTRICT,
    stage TEXT NOT NULL CHECK (stage IN ('planned', 'final')),
    input_hash TEXT NOT NULL,
    report JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT production_content_match_reports_input_hash_check
        CHECK (input_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT production_content_match_reports_report_check
        CHECK (jsonb_typeof(report) = 'object'),
    CONSTRAINT production_content_match_reports_unique
        UNIQUE (production_order_id, prompt_source_id, stage, input_hash)
);

CREATE INDEX IF NOT EXISTS idx_production_content_match_reports_order_stage
    ON pipeline.production_content_match_reports (production_order_id, stage, created_at DESC);
