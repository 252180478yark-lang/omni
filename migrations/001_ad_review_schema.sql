-- 已有数据库环境可手动执行：psql -f migrations/001_ad_review_schema.sql
-- 内容与 services/infra-core/postgres/init.sql 中 ad_review 段一致

CREATE SCHEMA IF NOT EXISTS ad_review;
COMMENT ON SCHEMA ad_review IS 'Ad campaign review & optimization logs';

CREATE TABLE IF NOT EXISTS ad_review.products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    description TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_products_name ON ad_review.products (name);

CREATE TABLE IF NOT EXISTS ad_review.campaigns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID NOT NULL REFERENCES ad_review.products(id) ON DELETE CASCADE,
    name VARCHAR(500) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_budget DECIMAL(12,2),
    total_cost DECIMAL(12,2),
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    review_log_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_campaigns_product ON ad_review.campaigns (product_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON ad_review.campaigns (status);
CREATE INDEX IF NOT EXISTS idx_campaigns_date ON ad_review.campaigns (start_date DESC);

CREATE TABLE IF NOT EXISTS ad_review.audience_packs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    tags JSONB DEFAULT '[]',
    targeting_method_text TEXT,
    targeting_method_file TEXT,
    audience_profile_text TEXT,
    audience_profile_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audience_campaign ON ad_review.audience_packs (campaign_id);

CREATE TABLE IF NOT EXISTS ad_review.materials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_pack_id UUID NOT NULL REFERENCES ad_review.audience_packs(id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    name VARCHAR(500) NOT NULL,
    parent_material_id UUID REFERENCES ad_review.materials(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1,
    iteration_note TEXT,
    cost DECIMAL(12,2),
    impressions INTEGER,
    clicks INTEGER,
    front_impressions INTEGER,
    ctr DECIMAL(8,4),
    shares_7d INTEGER,
    comments INTEGER,
    plays INTEGER,
    play_3s INTEGER,
    play_25pct INTEGER,
    play_50pct INTEGER,
    play_75pct INTEGER,
    completion_rate DECIMAL(8,4),
    new_a3 INTEGER,
    cost_per_result DECIMAL(12,4),
    a3_ratio DECIMAL(8,4),
    play_3s_rate DECIMAL(8,4),
    interaction_rate DECIMAL(8,4),
    cpm DECIMAL(12,4),
    cpc DECIMAL(12,4),
    video_analysis_id TEXT,
    video_analysis_scores JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_materials_audience ON ad_review.materials (audience_pack_id);
CREATE INDEX IF NOT EXISTS idx_materials_campaign ON ad_review.materials (campaign_id);
CREATE INDEX IF NOT EXISTS idx_materials_parent ON ad_review.materials (parent_material_id);

CREATE TABLE IF NOT EXISTS ad_review.review_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    content_md TEXT NOT NULL,
    ai_suggestions JSONB,
    experience_tags JSONB DEFAULT '[]',
    kb_id UUID,
    kb_document_id UUID,
    kb_synced_at TIMESTAMPTZ,
    is_edited BOOLEAN DEFAULT FALSE,
    generation_model VARCHAR(100),
    generation_tokens INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_review_logs_campaign ON ad_review.review_logs (campaign_id);
CREATE INDEX IF NOT EXISTS idx_review_logs_tags ON ad_review.review_logs USING gin (experience_tags);

CREATE TABLE IF NOT EXISTS ad_review.csv_imports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    audience_pack_id UUID NOT NULL REFERENCES ad_review.audience_packs(id) ON DELETE CASCADE,
    original_filename VARCHAR(500),
    row_count INTEGER,
    column_mapping JSONB,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
