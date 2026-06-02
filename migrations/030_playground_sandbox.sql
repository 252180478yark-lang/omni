-- migration 030: playground sandbox flag for agent_sessions
-- 给 /playground 创建的 session 打标位,这样 /chat 的 SessionList 可以过滤掉它们
-- 调真 tool / 真写下游数据,但 session 本身不出现在生产对话列表
ALTER TABLE mcp.agent_sessions ADD COLUMN IF NOT EXISTS sandbox BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN mcp.agent_sessions.sandbox IS
  'playground 创建的 session 标 true; /chat 的 SessionList 过滤掉; 调真 tool 真写数据但不出现在生产对话列表';
-- 部分索引(只索引正常 session)给 /chat 查列表加速
CREATE INDEX IF NOT EXISTS idx_agent_sessions_sandbox ON mcp.agent_sessions (sandbox) WHERE sandbox = false;
