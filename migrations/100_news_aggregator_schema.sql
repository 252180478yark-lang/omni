-- Canonical root-runner ownership for news-aggregator persistence.
-- Compatible with databases previously initialized by news Alembic revision
-- 20260310_0001. All DDL and seed writes are idempotent.

CREATE TABLE IF NOT EXISTS public.fetch_jobs (
    id UUID PRIMARY KEY,
    triggered_by VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    sources_used JSONB NOT NULL DEFAULT '[]'::jsonb,
    keywords_used JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_fetched INTEGER NOT NULL DEFAULT 0,
    after_dedup INTEGER NOT NULL DEFAULT 0,
    after_enrich INTEGER NOT NULL DEFAULT 0,
    error_log TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_fetch_jobs_status
    ON public.fetch_jobs (status, started_at);

CREATE TABLE IF NOT EXISTS public.source_configs (
    id UUID PRIMARY KEY,
    source_type VARCHAR(50) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    freshness VARCHAR(20) NOT NULL DEFAULT 'oneDay',
    max_results INTEGER NOT NULL DEFAULT 10,
    extra_params JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS public.articles (
    id UUID PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    url VARCHAR(2000) NOT NULL,
    source VARCHAR(50) NOT NULL,
    source_name VARCHAR(200),
    raw_snippet TEXT,
    ai_summary TEXT,
    ai_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    ai_relevance_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    is_starred BOOLEAN NOT NULL DEFAULT false,
    language VARCHAR(10) NOT NULL DEFAULT 'zh',
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    kb_doc_id VARCHAR(100),
    fetch_job_id UUID,
    CONSTRAINT uq_articles_url UNIQUE (url),
    CONSTRAINT articles_fetch_job_id_fkey
        FOREIGN KEY (fetch_job_id) REFERENCES public.fetch_jobs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_status_fetched
    ON public.articles (status, fetched_at);
CREATE INDEX IF NOT EXISTS idx_articles_tags
    ON public.articles USING gin (ai_tags);
CREATE INDEX IF NOT EXISTS idx_articles_archived
    ON public.articles (archived_at) WHERE status = 'archived';

INSERT INTO public.source_configs
    (id, source_type, display_name, is_enabled, keywords, freshness, max_results, extra_params)
VALUES
    ('00000000-0000-0000-0000-000000000501', 'serper', 'Serper', true,
     '["AI news today","LLM large language model","artificial intelligence breakthrough"]'::jsonb,
     'oneDay', 10, '{}'::jsonb),
    ('00000000-0000-0000-0000-000000000502', 'bocha', 'Bocha', true,
     '["AI 人工智能 最新","大模型 发布","AGI 智能体 Agent"]'::jsonb,
     'oneDay', 10, '{}'::jsonb),
    ('00000000-0000-0000-0000-000000000503', 'tianapi', 'Tianapi', true,
     '[]'::jsonb, 'oneDay', 10, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

DO $$
DECLARE
    missing_count INTEGER;
BEGIN
    SELECT count(*) INTO missing_count
      FROM (VALUES
        ('fetch_jobs', 'id'), ('fetch_jobs', 'triggered_by'),
        ('fetch_jobs', 'status'), ('fetch_jobs', 'started_at'),
        ('source_configs', 'id'), ('source_configs', 'source_type'),
        ('source_configs', 'keywords'), ('source_configs', 'extra_params'),
        ('articles', 'id'), ('articles', 'url'), ('articles', 'ai_tags'),
        ('articles', 'status'), ('articles', 'fetch_job_id')
      ) AS expected(table_name, column_name)
      LEFT JOIN information_schema.columns actual
        ON actual.table_schema = 'public'
       AND actual.table_name = expected.table_name
       AND actual.column_name = expected.column_name
     WHERE actual.column_name IS NULL;
    IF missing_count <> 0 THEN
        RAISE EXCEPTION 'existing news tables are incompatible with news-aggregator contract';
    END IF;
END $$;
