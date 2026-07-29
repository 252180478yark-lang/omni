-- Canonical clean-database bootstrap for the historical content_studio
-- pipeline table.  Migrations 002--005 were written against an image-init
-- side effect; keeping this small, idempotent table definition here makes the
-- migration ledger self-contained without rewriting those historical files.
-- This is shared legacy infrastructure only.  It does not activate the P1
-- ecommerce-visual or deferred AI-insert branches.

-- These knowledge foundations were also historically created by the Docker
-- init script.  Several numbered migrations extend them (014 and 049), so a
-- clean migration run must own their minimal canonical definitions.
CREATE SCHEMA IF NOT EXISTS knowledge;

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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tsv tsvector
);
CREATE INDEX IF NOT EXISTS idx_chunks_kb_id ON knowledge.knowledge_chunks (kb_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON knowledge.knowledge_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_created_at ON knowledge.knowledge_chunks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata ON knowledge.knowledge_chunks USING gin (metadata);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON knowledge.knowledge_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON knowledge.knowledge_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

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
CREATE INDEX IF NOT EXISTS idx_relations_source ON knowledge.relations (source_entity);
CREATE INDEX IF NOT EXISTS idx_relations_target ON knowledge.relations (target_entity);

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
    ON knowledge.hype_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE SCHEMA IF NOT EXISTS content_studio;

CREATE TABLE IF NOT EXISTS content_studio.pipelines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step TEXT NOT NULL DEFAULT 'copy',
    source_text TEXT,
    copy_result TEXT,
    script_result JSONB,
    product_images JSONB DEFAULT '[]'::jsonb,
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
