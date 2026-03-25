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
ALTER TABLE knowledge.knowledge_chunks
    ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED;
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