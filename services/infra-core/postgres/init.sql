-- Omni-Vibe OS Ultra — PostgreSQL 初始化
-- 由 docker-entrypoint-initdb.d 自动执行

-- ═══ 扩展 ═══
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ═══ Schema 隔离 ═══
CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS ai_hub;
CREATE SCHEMA IF NOT EXISTS knowledge;

COMMENT ON SCHEMA identity IS 'Identity service data (users, auth, tokens)';
COMMENT ON SCHEMA ai_hub IS 'AI provider hub data (usage, quotas)';
COMMENT ON SCHEMA knowledge IS 'Knowledge engine data (kb, docs, chunks)';

-- ═══ Knowledge Engine Tables (MOD-02 / MOD-03) ═══

CREATE TABLE IF NOT EXISTS knowledge.knowledge_bases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    embedding_provider VARCHAR(100) NOT NULL DEFAULT 'gemini',
    embedding_model VARCHAR(100) NOT NULL DEFAULT 'gemini-embedding-2-preview',
    dimension INTEGER NOT NULL DEFAULT 1536,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge.documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id UUID NOT NULL REFERENCES knowledge.knowledge_bases(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    source_url TEXT,
    source_type VARCHAR(50) NOT NULL DEFAULT 'manual',
    raw_text TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_documents_kb_id ON knowledge.documents (kb_id);

CREATE TABLE IF NOT EXISTS knowledge.tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id UUID NOT NULL,
    title VARCHAR(500),
    source_url TEXT,
    raw_text TEXT,
    source_type VARCHAR(50) NOT NULL DEFAULT 'manual',
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    error TEXT,
    document_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tasks_kb_id ON knowledge.tasks (kb_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON knowledge.tasks (status);

CREATE TABLE IF NOT EXISTS knowledge.knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES knowledge.documents(id) ON DELETE CASCADE,
    kb_id UUID NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    title VARCHAR(500),
    source_url TEXT,
    source_id VARCHAR(255),
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB NOT NULL DEFAULT '{}',
    source_type VARCHAR(50) NOT NULL DEFAULT 'manual',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chunks_kb_id ON knowledge.knowledge_chunks (kb_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON knowledge.knowledge_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_created_at ON knowledge.knowledge_chunks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata ON knowledge.knowledge_chunks USING gin (metadata);

-- HNSW 向量索引 (cosine distance)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON knowledge.knowledge_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 全文搜索列 + GIN 索引
-- tsv 由应用层用 jieba 分词后写入，而非 GENERATED，以支持中文全文检索。
ALTER TABLE knowledge.knowledge_chunks
    ADD COLUMN IF NOT EXISTS tsv tsvector;
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON knowledge.knowledge_chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS knowledge.entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id UUID NOT NULL,
    document_id UUID REFERENCES knowledge.documents(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(100) NOT NULL DEFAULT 'concept',
    description TEXT NOT NULL DEFAULT '',
    UNIQUE (kb_id, name)
);
CREATE INDEX IF NOT EXISTS idx_entities_kb_id ON knowledge.entities (kb_id);
CREATE INDEX IF NOT EXISTS idx_entities_document_id ON knowledge.entities (document_id);
CREATE INDEX IF NOT EXISTS idx_entities_name_trgm ON knowledge.entities USING gin (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS knowledge.relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id UUID NOT NULL,
    document_id UUID REFERENCES knowledge.documents(id) ON DELETE CASCADE,
    source_entity VARCHAR(255) NOT NULL,
    target_entity VARCHAR(255) NOT NULL,
    relation_type VARCHAR(100) NOT NULL DEFAULT 'related_to',
    weight REAL NOT NULL DEFAULT 1.0,
    UNIQUE (kb_id, source_entity, target_entity, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_relations_kb_id ON knowledge.relations (kb_id);
CREATE INDEX IF NOT EXISTS idx_relations_document_id ON knowledge.relations (document_id);
CREATE INDEX IF NOT EXISTS idx_relations_source ON knowledge.relations (kb_id, source_entity);
CREATE INDEX IF NOT EXISTS idx_relations_target ON knowledge.relations (kb_id, target_entity);

-- ═══ Video Analysis Tables ═══
CREATE SCHEMA IF NOT EXISTS video_analysis;

CREATE TABLE IF NOT EXISTS video_analysis.videos (
    id TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    report_md_path TEXT,
    report_json_path TEXT,
    report_txt_path TEXT,
    curve_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'queued',
    retries INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    progress REAL NOT NULL DEFAULT 0,
    status_message TEXT,
    metrics_json TEXT
);

CREATE TABLE IF NOT EXISTS video_analysis.cost_logs (
    id BIGSERIAL PRIMARY KEY,
    video_id TEXT,
    prompt_tokens INTEGER,
    response_tokens INTEGER,
    total_tokens INTEGER,
    cost_usd REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS video_analysis.knowledge_base (
    id BIGSERIAL PRIMARY KEY,
    video_id TEXT,
    summary TEXT,
    tags TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kb_pushed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS video_analysis.materials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    material_type VARCHAR(20) NOT NULL,
    title TEXT,
    source_url TEXT,
    target_kb_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    phase VARCHAR(40) NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    progress_message TEXT,
    error TEXT,
    retries INT NOT NULL DEFAULT 0,
    duration_sec REAL,
    unit_count INT NOT NULL DEFAULT 0,
    narrative_model TEXT,
    global_tone TEXT,
    bgm_json JSONB,
    file_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    cost_usd REAL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_va_materials_type ON video_analysis.materials(material_type);
CREATE INDEX IF NOT EXISTS idx_va_materials_status ON video_analysis.materials(status);
CREATE INDEX IF NOT EXISTS idx_va_materials_kb ON video_analysis.materials(target_kb_id);
CREATE INDEX IF NOT EXISTS idx_va_materials_created ON video_analysis.materials(created_at DESC);

CREATE TABLE IF NOT EXISTS video_analysis.material_units (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    material_id UUID NOT NULL REFERENCES video_analysis.materials(id) ON DELETE CASCADE,
    unit_index INT NOT NULL,
    unit_type VARCHAR(40) NOT NULL,
    start_sec REAL,
    end_sec REAL,
    image_index INT,
    keyframe_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    fields JSONB NOT NULL,
    prompt_pack JSONB NOT NULL,
    chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_va_units_material ON video_analysis.material_units(material_id);
CREATE INDEX IF NOT EXISTS idx_va_units_type ON video_analysis.material_units(unit_type);

CREATE TABLE IF NOT EXISTS video_analysis.material_clusters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_index INT NOT NULL,
    material_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary_json JSONB NOT NULL,
    target_kb_id UUID NOT NULL,
    chunk_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_va_clusters_kb ON video_analysis.material_clusters(target_kb_id);

-- ═══ Livestream Analysis Tables ═══
CREATE SCHEMA IF NOT EXISTS livestream;

CREATE TABLE IF NOT EXISTS livestream.tasks (
    id TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    phase TEXT NOT NULL DEFAULT 'queued',
    message TEXT NOT NULL DEFAULT '',
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 4,
    video_path TEXT,
    excel_path TEXT,
    json_path TEXT,
    error TEXT,
    summary_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ═══ HyPE — Hypothetical Prompt Embeddings ═══
CREATE TABLE IF NOT EXISTS knowledge.hype_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id UUID NOT NULL REFERENCES knowledge.knowledge_chunks(id) ON DELETE CASCADE,
    kb_id UUID NOT NULL,
    question_index INTEGER NOT NULL DEFAULT 0,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hype_kb_id ON knowledge.hype_embeddings (kb_id);
CREATE INDEX IF NOT EXISTS idx_hype_chunk_id ON knowledge.hype_embeddings (chunk_id);
CREATE INDEX IF NOT EXISTS idx_hype_embedding_hnsw
    ON knowledge.hype_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ═══ Ad Review (SP8) ═══
CREATE SCHEMA IF NOT EXISTS ad_review;
COMMENT ON SCHEMA ad_review IS 'Ad campaign review & optimization logs';

CREATE TABLE IF NOT EXISTS ad_review.products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    sku VARCHAR(100),
    price DECIMAL(12,2),
    margin_rate DECIMAL(5,4),
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

ALTER TABLE ad_review.campaigns
    ADD COLUMN IF NOT EXISTS brief_id UUID NULL,
    ADD COLUMN IF NOT EXISTS digital_human_id UUID NULL;

CREATE INDEX IF NOT EXISTS idx_campaigns_brief ON ad_review.campaigns (brief_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_digital_human ON ad_review.campaigns (digital_human_id);

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

CREATE TABLE IF NOT EXISTS ad_review.material_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_pack_id UUID NOT NULL REFERENCES ad_review.audience_packs(id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    style_label VARCHAR(100) NOT NULL,
    video_purpose VARCHAR(20) NOT NULL DEFAULT 'seeding',
    description TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_material_groups_audience ON ad_review.material_groups (audience_pack_id);
CREATE INDEX IF NOT EXISTS idx_material_groups_campaign ON ad_review.material_groups (campaign_id);

CREATE TABLE IF NOT EXISTS ad_review.materials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_pack_id UUID NOT NULL REFERENCES ad_review.audience_packs(id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL REFERENCES ad_review.campaigns(id) ON DELETE CASCADE,
    group_id UUID REFERENCES ad_review.material_groups(id) ON DELETE SET NULL,
    name VARCHAR(500) NOT NULL,
    parent_material_id UUID REFERENCES ad_review.materials(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1,
    iteration_note TEXT,
    change_tags JSONB DEFAULT '[]',
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
    conversion_rate DECIMAL(8,6),
    video_analysis_id TEXT,
    video_analysis_scores JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_materials_audience ON ad_review.materials (audience_pack_id);
CREATE INDEX IF NOT EXISTS idx_materials_campaign ON ad_review.materials (campaign_id);
CREATE INDEX IF NOT EXISTS idx_materials_group ON ad_review.materials (group_id);
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

-- ═══════════════════════════════════════════════════════════════════
-- Content Studio (内容工坊)
-- ═══════════════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS content_studio;

CREATE TABLE IF NOT EXISTS content_studio.pipelines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step TEXT NOT NULL DEFAULT 'copy',
    source_text TEXT,
    copy_result TEXT,
    script_result JSONB,
    -- 产品白底图 URL 列表，保证全流程产品外观一致
    product_images JSONB DEFAULT '[]'::jsonb,
    -- 人物档案：[{id, name, description, face_url, scenes}]，保证全流程人物一致
    character_profiles JSONB DEFAULT '[]'::jsonb,
    storyboard_results JSONB DEFAULT '[]'::jsonb,
    video_results JSONB DEFAULT '[]'::jsonb,
    final_video_url TEXT,
    download_url TEXT,
    config JSONB DEFAULT '{}'::jsonb,
    cost_estimate JSONB DEFAULT '{}'::jsonb,
    actual_cost JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pipelines_status ON content_studio.pipelines (status);
CREATE INDEX IF NOT EXISTS idx_pipelines_created ON content_studio.pipelines (created_at DESC);

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

CREATE TABLE IF NOT EXISTS content_studio.style_presets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO content_studio.style_presets (name, description, is_builtin, config) VALUES
('种草安利', '小红书/抖音种草风格，真实感强', TRUE,
 '{"copy_style":"grassplanting","image_style":"lifestyle_photo","tone":"casual","pace":"medium"}'),
('品牌宣传', '高端品牌调性，电影感', TRUE,
 '{"copy_style":"brand","image_style":"cinematic","tone":"professional","pace":"slow"}'),
('促销活动', '强调优惠力度、紧迫感', TRUE,
 '{"copy_style":"promotion","image_style":"vibrant","tone":"exciting","pace":"fast"}'),
('科技测评', '理性分析、数据驱动', TRUE,
 '{"copy_style":"tech_review","image_style":"clean_modern","tone":"analytical","pace":"medium"}'),
('温馨故事', '情感共鸣、生活化', TRUE,
 '{"copy_style":"storytelling","image_style":"warm_illustration","tone":"emotional","pace":"slow"}')
ON CONFLICT DO NOTHING;