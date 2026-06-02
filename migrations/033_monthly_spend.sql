-- migration 033: 月度成本总账 2026-06-01
-- 蓝图 §4 L0-2【R-28】"成本闸 = 单次 + 月度总账":
--   单次会话刹车(--max-turns)已 done,但缺"无预算上限、无超额告警、无月度累计"。
-- 本 migration 落地"月度累计"那一半:把每次 Claude Code 会话跑完报的
--   total_cost_usd(前端 ws-handler task_done 里 chunk.total_cost_usd)按月归集进总账。
--
-- 纯加法:只 CREATE,绝不 ALTER 任何现有表(不碰 mcp.tool_calls / mcp.agent_sessions)。
-- 不应用(留老板早上 apply)、不接 cron、不发告警——告警接入是后续切片。
--
-- 设计:明细表(每笔一行,保留 session 维度可下钻)+ 月度汇总视图(总账读这视图)。
-- 不做"月桶 upsert"是因为单人量小,明细更可下钻、也不丢归因(可回溯到哪个 session 烧的)。
-- actor_id 预留(蓝图 §1.6【R-26】:单人→小团队只填字段不改表;默认 'yark')。

-- ─── 明细表:每笔会话成本一行 ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS mcp.monthly_spend (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 关联会话(可选;前端 task_done 拿到的是 claude_session_id,service 侧尽量解析成 uuid)
    -- 不加 FK 到 agent_sessions:允许"会话还没落 agent_sessions 表"也能记账(fail-open),
    -- 也避免删 session 时连带删账目(账要留痕)。
    session_id UUID,
    -- Claude Code 自己的 session uuid 文本(解析不到 agent_sessions.id 时也留着备查)
    claude_session_id TEXT,
    -- 这笔花费的美元金额(Claude Code result chunk 的 total_cost_usd)
    cost_usd NUMERIC(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    -- 来源标:claude_session(默认,会话跑完归集) / manual(手动补录) / other
    source TEXT NOT NULL DEFAULT 'claude_session',
    -- 哪个客户端跑的(desktop / web / orch),便于后期按端拆成本;可空
    client TEXT,
    -- 操作者(蓝图 §1.6【R-26】预留;单人期默认 'yark',扩团队只改默认值不改表)
    actor_id TEXT NOT NULL DEFAULT 'yark',
    -- 备注(手动补录或异常说明)
    note TEXT,
    -- 这笔归属的"账月"——按 spent_at 落在哪个自然月(用月初零点表示,便于 GROUP BY/索引)。
    -- 由 service 写入时算好;不靠触发器,保持 migration 纯净、行为显式。
    spend_month DATE NOT NULL,
    -- 实际发生时间(默认 now;补录历史账可显式传)
    spent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE mcp.monthly_spend IS
    '月度成本总账明细:每次 Claude Code 会话跑完报的 total_cost_usd 归集一行;'
    '总账读 mcp.v_monthly_spend_summary 视图。纯留痕账目,不删(删 session 不连带删)';
COMMENT ON COLUMN mcp.monthly_spend.spend_month IS
    '归属账月(月初零点 DATE,如 2026-06-01 代表 2026 年 6 月);service 按 spent_at 算好写入';
COMMENT ON COLUMN mcp.monthly_spend.cost_usd IS
    'Claude Code result chunk 的 total_cost_usd(美元);CHECK >= 0 防负值脏数据';
COMMENT ON COLUMN mcp.monthly_spend.actor_id IS
    '操作者预留字段(蓝图【R-26】单人→小团队只填字段不改表);单人期默认 yark';
COMMENT ON COLUMN mcp.monthly_spend.source IS
    'claude_session(会话跑完自动归集) / manual(手动补录) / other';

-- 按账月查总账(主路径)
CREATE INDEX IF NOT EXISTS idx_monthly_spend_month
    ON mcp.monthly_spend (spend_month);
-- 按会话反查这次烧了多少
CREATE INDEX IF NOT EXISTS idx_monthly_spend_session
    ON mcp.monthly_spend (session_id, spent_at DESC)
    WHERE session_id IS NOT NULL;

-- ─── 月度汇总视图:总账 / 软上限检测都读这个 ───────────────────────
CREATE OR REPLACE VIEW mcp.v_monthly_spend_summary AS
SELECT
    spend_month,
    actor_id,
    COUNT(*)              AS entry_count,
    SUM(cost_usd)         AS total_cost_usd,
    MIN(spent_at)         AS first_spent_at,
    MAX(spent_at)         AS last_spent_at
FROM mcp.monthly_spend
GROUP BY spend_month, actor_id;

COMMENT ON VIEW mcp.v_monthly_spend_summary IS
    '月度成本汇总(按账月 × 操作者):total_cost_usd 当月累计;'
    'cost_ledger_service 月度软上限/超额检测读这视图;omni 自身月成本进 BI 看板当一等指标(蓝图 §4 L0-2)';
