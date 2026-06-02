-- migration 038: 诊断官《改进提议》生命周期表 2026-06-02
-- 蓝图 §6.2 诊断官（两面共享的可调用分析能力）+ §6 改进半的正确落点（看见+提议+决策）。
--
-- 背景：现状只有 feedback_digest cron（被动聚类负反馈写 markdown，老板自己找）。
--   蓝图 §6.2 要求把它升级成**可调用 tool**（恰好落进宪法 §1.2「能力即工具」），
--   并给提议加 §6.2【R-20】生命周期防 inbox bankruptcy：
--   ① 优先级（按影响金额/频次）② 有效期（过期自动归档）③ 一键 接受/忽略/不再提醒同类 三态。
--
-- 本表只存"提议"——诊断官**只提议不碰开关**（§6.2 越界红线：拍板权 100% 在老板）。
-- R-14 归因分两层：observation（观察到的相关，带数据）vs hypothesis（可能原因，标假设+混杂因子）。
-- R-15 样本量：sample_size + confidence；n 不足只能 'preliminary'（初步观察/待验证）。
-- R-26 actor 预留：resolved_by 默认 yark。
--
-- 纯加法、可逆：CREATE TABLE/INDEX IF NOT EXISTS；DROP TABLE 即回滚（无外键依赖它）。

CREATE TABLE IF NOT EXISTS mcp.improvement_proposals (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 诊断面：content（作战面/内容改进）/ analysis（分析面/趋势归因，依赖多平台数据，阶段1）
    mode          TEXT NOT NULL DEFAULT 'content',
    -- 来源类别：msg_feedback / tool_feedback / asset_perf（决定文案模板 + 怎么算优先级）
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    -- R-14 第①层：观察到的相关（客观、带数据，不含因果断言）
    observation   TEXT NOT NULL,
    -- R-14 第②层：可能的原因（必须标"假设" + 列未排除的混杂因子 + "要证实需对比 X"）
    hypothesis    TEXT,
    -- 证据包：counts / sample_size / time_window / 源引用（category / tool_name / asset_ids…）
    evidence      JSONB NOT NULL DEFAULT '{}',
    -- R-15 样本量 + 置信语气：sample_size 行数/次数；confidence ∈ preliminary/observed
    sample_size   INTEGER NOT NULL DEFAULT 0,
    confidence    TEXT NOT NULL DEFAULT 'preliminary',
    -- R-20 优先级（按影响金额/频次，不按时间）：数值越大越该先看 + 人话理由
    priority      NUMERIC(10,2) NOT NULL DEFAULT 0,
    priority_reason TEXT,
    -- R-20 去重键（mode:source:subject）：同一议题重跑刷新而非堆叠；老板"不再提醒同类"按它静音
    dedupe_key    TEXT NOT NULL,
    occurrences   INTEGER NOT NULL DEFAULT 1,
    -- R-20 三态生命周期：open / accepted / ignored（=不再提醒同类，静音 dedupe_key）/ snoozed / expired
    status        TEXT NOT NULL DEFAULT 'open',
    snooze_until  TIMESTAMPTZ,         -- snoozed 时：此刻前不再 resurface
    expires_at    TIMESTAMPTZ,         -- 有效期：过期 open 提议视为 expired（list 时过滤/标注）
    resolved_at   TIMESTAMPTZ,
    resolution_note TEXT,
    resolved_by   VARCHAR(64) DEFAULT 'yark',   -- R-26 预留
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE mcp.improvement_proposals IS
    '诊断官《改进提议》（蓝图 §6.2）：只提议不碰开关。R-14 observation/hypothesis 分层、'
    'R-15 sample_size/confidence、R-20 priority/expiry/三态生命周期。老板拍板才落地，永不自动生效';
COMMENT ON COLUMN mcp.improvement_proposals.dedupe_key IS
    'mode:source:subject 去重键：同议题重跑刷新 occurrences/last_seen 而非堆叠；status=ignored 时静音（不再提醒同类）';
COMMENT ON COLUMN mcp.improvement_proposals.status IS
    'open / accepted（老板采纳，去改了）/ ignored（不再提醒同类，静音）/ snoozed（snooze_until 前不提）/ expired（过期归档）';

-- 同一去重键只保留一条"活的"（open/snoozed），避免重复提议堆叠。
-- accepted/ignored/expired 是终态，允许历史多条共存（部分索引只约束活态）。
CREATE UNIQUE INDEX IF NOT EXISTS uq_proposal_dedupe_active
    ON mcp.improvement_proposals (dedupe_key)
    WHERE status IN ('open', 'snoozed');

CREATE INDEX IF NOT EXISTS idx_proposal_status_priority
    ON mcp.improvement_proposals (status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_proposal_mode
    ON mcp.improvement_proposals (mode, status);


-- ===== DOWN（手动回滚用）=====
-- 纯可逆：DROP TABLE 即回到现状（无任何外键/代码强依赖它，diagnose tool 容错处理表缺失）。
--   DROP TABLE IF EXISTS mcp.improvement_proposals;   -- 连带删其索引
--   DELETE FROM public.schema_migrations WHERE filename = '038_improvement_proposals.sql';
