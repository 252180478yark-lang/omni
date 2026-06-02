-- migration 031: 反馈飞轮地基 2026-05-28
-- 1. mcp.tool_calls 加 rating_category 归因分类字段
-- 2. 新建 mcp.message_feedback 消息级反馈表(整条 AI 回复评分,不是 tool 维度)

ALTER TABLE mcp.tool_calls
  ADD COLUMN IF NOT EXISTS rating_category TEXT;

COMMENT ON COLUMN mcp.tool_calls.rating_category IS
  '负反馈归因分类: prompt_bad / tradeoff_wrong / factual_error / tone_off / wrong_tool / incomplete / other';

CREATE INDEX IF NOT EXISTS idx_tool_calls_rating_category
  ON mcp.tool_calls(rating_category, created_at DESC)
  WHERE rating_category IS NOT NULL;

CREATE TABLE IF NOT EXISTS mcp.message_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES mcp.agent_sessions(id) ON DELETE CASCADE,
  message_id TEXT NOT NULL,
  rating TEXT NOT NULL CHECK (rating IN ('good', 'bad')),
  category TEXT,
  note TEXT,
  message_text_snapshot TEXT,
  tool_use_ids TEXT[],
  client TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, message_id)
);

COMMENT ON TABLE mcp.message_feedback IS
  'AI 整条消息的反馈(不是 tool 级):同 session_id+message_id 覆盖更新;message_text_snapshot 存当时消息内容(≤4KB)便于事后归因;tool_use_ids 这条消息涉及的 tool_use_id 反查方便';

CREATE INDEX idx_message_feedback_session
  ON mcp.message_feedback(session_id, created_at DESC);
CREATE INDEX idx_message_feedback_rating
  ON mcp.message_feedback(rating, category, created_at DESC)
  WHERE rating = 'bad';
