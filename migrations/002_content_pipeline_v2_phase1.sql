-- Content Pipeline v2 Phase 1
-- New entities: digital_humans / briefs
-- Pipeline extension: product_id / brief_id / digital_human_id

CREATE SCHEMA IF NOT EXISTS content_studio;

CREATE TABLE IF NOT EXISTS content_studio.digital_humans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    seed_face_url TEXT NOT NULL,
    face_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    gender TEXT,
    age_range TEXT,
    style_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    identity_anchor TEXT,
    source_pipeline_id UUID NULL,
    source_scene_id INT NULL,
    quality_score NUMERIC(6,3) NOT NULL DEFAULT 0,
    ctr_avg NUMERIC(10,6) NOT NULL DEFAULT 0,
    cvr_avg NUMERIC(10,6) NOT NULL DEFAULT 0,
    usage_count INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_studio.briefs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID NULL,
    product_name TEXT,
    version INT NOT NULL DEFAULT 1,
    parent_brief_id UUID NULL,
    title TEXT NOT NULL,
    usp TEXT NOT NULL,
    scenarios JSONB NOT NULL DEFAULT '[]'::jsonb,
    audience_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    tone_style JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_notes TEXT,
    dmp_sop TEXT,
    kb_doc_id UUID NULL,
    quality_score NUMERIC(6,3) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE content_studio.pipelines
    ADD COLUMN IF NOT EXISTS product_id UUID NULL,
    ADD COLUMN IF NOT EXISTS brief_id UUID NULL,
    ADD COLUMN IF NOT EXISTS digital_human_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'content_studio'
          AND table_name = 'briefs'
          AND constraint_name = 'fk_briefs_parent'
    ) THEN
        ALTER TABLE content_studio.briefs
            ADD CONSTRAINT fk_briefs_parent
            FOREIGN KEY (parent_brief_id) REFERENCES content_studio.briefs(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'content_studio'
          AND table_name = 'pipelines'
          AND constraint_name = 'fk_pipelines_brief'
    ) THEN
        ALTER TABLE content_studio.pipelines
            ADD CONSTRAINT fk_pipelines_brief
            FOREIGN KEY (brief_id) REFERENCES content_studio.briefs(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'content_studio'
          AND table_name = 'pipelines'
          AND constraint_name = 'fk_pipelines_digital_human'
    ) THEN
        ALTER TABLE content_studio.pipelines
            ADD CONSTRAINT fk_pipelines_digital_human
            FOREIGN KEY (digital_human_id) REFERENCES content_studio.digital_humans(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_digital_humans_status ON content_studio.digital_humans(status);
CREATE INDEX IF NOT EXISTS idx_digital_humans_created ON content_studio.digital_humans(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_briefs_product ON content_studio.briefs(product_id);
CREATE INDEX IF NOT EXISTS idx_briefs_created ON content_studio.briefs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipelines_brief ON content_studio.pipelines(brief_id);
CREATE INDEX IF NOT EXISTS idx_pipelines_digital_human ON content_studio.pipelines(digital_human_id);
