-- migration 032: Bug 记忆库 + 客户端调用日志 2026-05-28
-- 解决"bug 第一次修第二次还要修"
-- Phase A+ mcp.client_logs:客户端所有 IPC/fetch/spawn/error 留痕(不依赖人工反馈)
-- Phase A++ mcp.bug_memory:bug 长期记忆,Claude 启动时 inject 已知未修 bug 避坑

-- ─ A+ mcp.client_logs:客户端所有 IPC/fetch/spawn/error 留痕 ─
CREATE TABLE IF NOT EXISTS mcp.client_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES mcp.agent_sessions(id) ON DELETE CASCADE,
  client TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'info'
    CHECK (severity IN ('debug','info','warn','error','critical')),
  channel TEXT,
  payload JSONB,
  result JSONB,
  duration_ms INTEGER,
  stack_trace TEXT,
  user_marked_bug BOOLEAN NOT NULL DEFAULT FALSE,
  bug_memory_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE mcp.client_logs IS
  '客户端所有运行时事件留痕(IPC/fetch/spawn/error/crash/startup),被动抓不依赖反馈;后期归因 bug 用';
COMMENT ON COLUMN mcp.client_logs.event_type IS
  'ipc_call / ke_fetch / claude_spawn / claude_stderr / electron_error / electron_crash / startup / manual_bug_report';

CREATE INDEX IF NOT EXISTS idx_client_logs_session ON mcp.client_logs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_client_logs_severity ON mcp.client_logs(severity, created_at DESC)
  WHERE severity IN ('warn','error','critical');
CREATE INDEX IF NOT EXISTS idx_client_logs_bug ON mcp.client_logs(user_marked_bug, created_at DESC)
  WHERE user_marked_bug = TRUE;

-- ─ A++ mcp.bug_memory:bug 长期记忆 ─
CREATE TABLE IF NOT EXISTS mcp.bug_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  symptom TEXT NOT NULL,
  trigger_conditions TEXT,
  root_cause TEXT,
  fix_recipe TEXT,
  fix_applied BOOLEAN NOT NULL DEFAULT FALSE,
  occurrences INTEGER NOT NULL DEFAULT 1,
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  client_log_ids UUID[],
  tags TEXT[],
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE mcp.bug_memory IS
  'Bug 长期记忆:fix_applied=false 时启动期注入 Claude system prompt 让其避坑;同 title+symptom 相似可合并 occurrences++';

CREATE INDEX IF NOT EXISTS idx_bug_memory_unfixed
  ON mcp.bug_memory(fix_applied, last_seen DESC)
  WHERE fix_applied = FALSE;
CREATE INDEX IF NOT EXISTS idx_bug_memory_tags ON mcp.bug_memory USING GIN(tags);

-- 反向 FK(client_logs.bug_memory_id → bug_memory.id)
-- 用 DO block 防重复执行炸 constraint already exists
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'client_logs_bug_memory_fkey'
  ) THEN
    ALTER TABLE mcp.client_logs
      ADD CONSTRAINT client_logs_bug_memory_fkey
      FOREIGN KEY (bug_memory_id) REFERENCES mcp.bug_memory(id) ON DELETE SET NULL;
  END IF;
END $$;
