-- migrations/028_agent_sessions.sql
-- W5-B: agent chat 前端 session 元数据表
-- 对话历史本身存在 Claude Code 自带 ~/.claude/projects/<dir>/sessions/<uuid>.jsonl，本表只存元数据

CREATE TABLE IF NOT EXISTS mcp.agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Claude Code 自己生成的 session uuid（用于 --resume）
    claude_session_id TEXT NOT NULL UNIQUE,
    -- 老板可以重命名
    title TEXT NOT NULL DEFAULT '新对话',
    -- 关联业务上下文（可选）
    sku_id VARCHAR(64),
    -- 最后一条消息预览（侧栏显示用）
    last_message_preview TEXT,
    -- 累计消息数 + token 数
    message_count INT NOT NULL DEFAULT 0,
    tokens_input_total INT NOT NULL DEFAULT 0,
    tokens_output_total INT NOT NULL DEFAULT 0,
    -- 状态
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_sessions_status ON mcp.agent_sessions (status, updated_at DESC);
CREATE INDEX idx_agent_sessions_sku ON mcp.agent_sessions (sku_id) WHERE sku_id IS NOT NULL;
CREATE INDEX idx_agent_sessions_claude_id ON mcp.agent_sessions (claude_session_id);

COMMENT ON TABLE mcp.agent_sessions IS 'W5-B agent chat 前端的 session 元数据，对话内容存在 Claude Code jsonl 文件';

-- 自动维护 updated_at（沿用 migrations 017/022 既有模式）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_agent_sessions_touch ON mcp.agent_sessions;
        CREATE TRIGGER trg_agent_sessions_touch
            BEFORE UPDATE ON mcp.agent_sessions
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;
