-- migrations/029_orch_lineage.sql
-- W7 mobile orchestrator: 跨项目 + usage_limit 续跑
--
-- 1) mcp.agent_sessions 加 project_dir → omni-desktop session_manager.spawn() 传 cwd
-- 2) orch schema 两张表: paused_sessions (claude stderr 撞 limit 时自动写) +
--    scheduled_resumes (老板手机定时续跑写)
-- 3) 一个 view 让 main process resume scheduler 一句 SQL 拉到点任务

-- ─── 1. mcp.agent_sessions 加 project_dir ──────────────────────────
ALTER TABLE mcp.agent_sessions
    ADD COLUMN IF NOT EXISTS project_dir TEXT;

COMMENT ON COLUMN mcp.agent_sessions.project_dir IS
    '老板想让这个 session 在哪个目录跑 (E:/agent/omni / E:/somewhere/else); '
    'omni-desktop session_manager.spawn() 拿来作 cwd 传给 claude.cmd; '
    'NULL 时回退到 omni-desktop 进程 cwd (= 老的兼容行为)';

-- ─── 2. orch schema ─────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS orch;

-- 2a. 撞 limit 时 claude-runner stderr regex 命中后自动写
CREATE TABLE IF NOT EXISTS orch.paused_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES mcp.agent_sessions(id) ON DELETE CASCADE,
    claude_session_id TEXT NOT NULL,
    paused_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retry_at_hint TEXT,
    reason TEXT NOT NULL DEFAULT 'usage_limit'
        CHECK (reason IN ('usage_limit', 'manual', 'error')),
    stderr_excerpt TEXT
);

CREATE INDEX IF NOT EXISTS idx_paused_sessions_session
    ON orch.paused_sessions (session_id, paused_at DESC);

COMMENT ON TABLE orch.paused_sessions IS
    'claude-runner stderr 撞 limit 后自动写; 老板手机看 GET /api/paused-sessions '
    '决定要不要设定时续跑 (scheduled_resumes)';

COMMENT ON COLUMN orch.paused_sessions.retry_at_hint IS
    'claude stderr 原文里的 "try again at 3pm" 时间字段, 不解析直接给老板看; '
    'NULL 时表示没解析到具体时间 (claude 输出格式变了)';

-- 2b. 老板手机点"3 点续跑"时写
CREATE TABLE IF NOT EXISTS orch.scheduled_resumes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES mcp.agent_sessions(id) ON DELETE CASCADE,
    scheduled_at TIMESTAMPTZ NOT NULL,
    resume_prompt TEXT NOT NULL DEFAULT '继续',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    completed_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sched_resumes_pending
    ON orch.scheduled_resumes (scheduled_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_sched_resumes_session
    ON orch.scheduled_resumes (session_id, created_at DESC);

COMMENT ON TABLE orch.scheduled_resumes IS
    'omni-desktop main process resume-scheduler.ts 每 60s 扫这表, '
    'scheduled_at <= NOW() AND status=pending 的取出 spawn claude --resume';

-- ─── 3. 让 scheduler 一句 SQL 拉到点任务的视图 ─────────────────────
CREATE OR REPLACE VIEW orch.v_resumes_due AS
SELECT
    r.id AS resume_id,
    r.session_id,
    r.scheduled_at,
    r.resume_prompt,
    s.claude_session_id,
    s.project_dir,
    s.title AS session_title
FROM orch.scheduled_resumes r
JOIN mcp.agent_sessions s ON s.id = r.session_id
WHERE r.status = 'pending'
  AND r.scheduled_at <= NOW()
  AND s.status != 'deleted';

COMMENT ON VIEW orch.v_resumes_due IS
    'omni-desktop resume-scheduler 每 60s SELECT 这视图; 拿到 resume_id + '
    'claude_session_id + project_dir 直接 spawn claude --resume cwd=project_dir';
