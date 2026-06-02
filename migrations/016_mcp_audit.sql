-- migrations/016_mcp_audit.sql
-- MCP Server 审计与 Human Gate 表（W1 起用）
CREATE SCHEMA IF NOT EXISTS mcp;

CREATE TABLE IF NOT EXISTS mcp.tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_name TEXT NOT NULL,
    args JSONB NOT NULL,
    result JSONB,
    status TEXT NOT NULL,            -- pending|approved|rejected|completed|error|orphaned
    require_approval BOOLEAN NOT NULL DEFAULT FALSE,
    duration_ms INT,
    error TEXT,
    user_rating TEXT,                -- good|bad|redo|null
    rating_note TEXT,
    model_used TEXT,                 -- 实际用的 provider/model
    tokens_input INT,
    tokens_output INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name_time
    ON mcp.tool_calls (tool_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_calls_pending
    ON mcp.tool_calls (status) WHERE status='pending';
CREATE INDEX IF NOT EXISTS idx_tool_calls_rating
    ON mcp.tool_calls (user_rating) WHERE user_rating IS NOT NULL;

CREATE TABLE IF NOT EXISTS mcp.human_gates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_call_id UUID REFERENCES mcp.tool_calls(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    decision TEXT,                   -- approved|rejected
    decision_note TEXT,
    decided_at TIMESTAMPTZ,
    timeout_seconds INT NOT NULL DEFAULT 3600,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_human_gates_pending
    ON mcp.human_gates (decision) WHERE decision IS NULL;
