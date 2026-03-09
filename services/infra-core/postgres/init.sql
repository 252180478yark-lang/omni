CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS ai_hub;
CREATE SCHEMA IF NOT EXISTS knowledge;

COMMENT ON SCHEMA identity IS 'Identity service data (users, auth, tokens)';
COMMENT ON SCHEMA ai_hub IS 'AI provider hub data (usage, quotas)';
COMMENT ON SCHEMA knowledge IS 'Knowledge engine data (kb, docs, chunks)';
