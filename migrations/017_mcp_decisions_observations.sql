-- migrations/017_mcp_decisions_observations.sql
-- W4-B 切片 5：W4 加分 tool save_decision + schedule_observation 用的两张表

-- ─── decisions 决策日志表（save_decision F 类） ───
-- 老板"我刚拍板 X" 时随手记一行，事后能查
CREATE TABLE IF NOT EXISTS mcp.decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,                -- 决定的一行总结
    decision TEXT NOT NULL,             -- 实际拍板的内容（多行 markdown 也行）
    context TEXT,                       -- 当时的背景/数据/对话摘要（可空）
    tags TEXT[] NOT NULL DEFAULT '{}',  -- 自由 tag：sku-X / pricing / channel-tmall 等
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decisions_created_at
    ON mcp.decisions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_tags
    ON mcp.decisions USING gin (tags);

-- ─── observations 主动巡检任务登记表（schedule_observation T 类） ───
-- design doc §4.3 主动巡检。本 MVP 只做"登记"——cron 真触发由老板侧
-- Windows Task Scheduler 跑 `python -m app.observation.run_one --name <X>`
-- 完成（或后续切片接入 KE 内部 cron）。enabled=False 即软停。
CREATE TABLE IF NOT EXISTS mcp.observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,          -- 唯一名（如 daily_store_pulse）
    cron TEXT NOT NULL,                 -- 5/6 段 cron 表达式（"0 9 * * *" 等）
    prompt TEXT NOT NULL,               -- Claude headless 拉起来后的 prompt 或 skill 触发词
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_run TIMESTAMPTZ,               -- 最近一次成功跑的时间（外部 worker 写）
    next_run TIMESTAMPTZ,               -- 计算出的下次理论触发（注册时按 cron 算）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_observations_enabled
    ON mcp.observations (enabled) WHERE enabled = TRUE;
