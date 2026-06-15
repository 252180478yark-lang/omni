-- ============================================================
-- Migration 052: 编导 brief A/B 单变量迭代闭环（实验台账 + 状态机底座）
--
-- 背景（2026-06-15）：圈人群后的「内容 brief 链」（step 3.5 画像 → 3.6 编导
-- brief）缺一个把【N 条视频投后真实数据 → 单变量 A/B → 迭代 → 沉淀获胜框架】
-- 串起来的台账。本 migration 建状态机底座（确定性，不跑 agent loop）：
--   ① pipeline.experiments       一行 = SKU×人群×投放意图(intent)×北极星 的长期实验
--   ② pipeline.experiment_rounds 一行 = 一个 flight（只扫一个变量）
--   ③ pipeline.experiment_arms   一行 = 某轮某臂（一个变量取值 = 一条 director_brief）
--   ④ pipeline.assets            +experiment_id/+experiment_arm_id（一臂多视频，归属唯一锚）
--   ⑤ pipeline.scripts           +intent（director_brief 的投放意图维度，可被 A/B 扫）
--   ⑥ knowledge.prompt_rules     +source_experiment_id/+source_round_var（市场数据→规则桥的判重锚）
--   ⑦ v_experiment_round_results 汇总视图：按 north_star_metric 动态从 ad_metrics JSONB 取真值，
--                                winner 排序唯一口径=avg（非 sum，sum 会把"投得多"误判成"取值好"）
--   ⑧ v_asset_full_lineage       纯加法重建，反查链路补实验维度
--
-- 设计稿：docs/design-director-brief-ab-loop.md
-- 纯加法、幂等（IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / CREATE OR REPLACE）。
-- 列约定对齐 021/047（denorm sku_id / 弱 FK denorm / content_studio.touch_updated_at 触发器）。
-- ============================================================

-- ────────────────────────────────────────────────────────
-- ① 实验台账（一行 = SKU×人群×intent 的长期实验；无 version/parent——长期台账不是多版本产物）
-- ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline.experiments (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id               VARCHAR(64) NOT NULL,                       -- denorm 全表锚
    portrait_id          UUID REFERENCES pipeline.audience_portraits(id) ON DELETE SET NULL,
    audience_record_id   UUID,                                       -- denorm（弱 FK，同 047 先例）
    audience_run_id      UUID,                                       -- denorm
    matrix_run_id        UUID,                                       -- denorm
    intent               TEXT NOT NULL,                              -- planting/harvest/soft_ad/hard_ad（不允许 generic）
    north_star_metric    TEXT NOT NULL,                              -- ∈ ad_metrics 白名单（tool 层校验，DB 写不动 Python 常量）
    north_star_direction TEXT NOT NULL DEFAULT 'higher_better',
    title                TEXT,
    baseline             JSONB NOT NULL DEFAULT '{}'::jsonb,         -- 已锁定变量取值集 {swept_variable: variable_value}
    status               TEXT NOT NULL DEFAULT 'running',
    winning_framework_md TEXT,                                       -- 沉淀时落人读获胜框架快照（不覆盖）
    framework_distilled_at TIMESTAMPTZ,
    notes                TEXT,
    actor_id             VARCHAR(64) DEFAULT 'yark',
    adopted_by           VARCHAR(64) DEFAULT 'yark',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT experiments_intent_check
        CHECK (intent IN ('planting', 'harvest', 'soft_ad', 'hard_ad')),
    CONSTRAINT experiments_direction_check
        CHECK (north_star_direction IN ('higher_better', 'lower_better')),
    CONSTRAINT experiments_status_check
        CHECK (status IN ('running', 'converged', 'archived'))
);
CREATE INDEX IF NOT EXISTS idx_experiments_sku
    ON pipeline.experiments (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_experiments_running
    ON pipeline.experiments (sku_id) WHERE status = 'running';

COMMENT ON TABLE pipeline.experiments IS
    '编导 brief A/B 实验台账（SKU×人群×intent×北极星）；状态机底座，不跑 agent loop。current_round 派生 MAX(round_no) 不冗余存。';

-- ────────────────────────────────────────────────────────
-- ② round（一行 = 一个 flight，扫一个变量；UNIQUE(experiment_id,round_no) 是单变量纪律载体）
-- ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline.experiment_rounds (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id     UUID NOT NULL REFERENCES pipeline.experiments(id) ON DELETE CASCADE,
    sku_id            VARCHAR(64) NOT NULL,                          -- denorm
    round_no          INTEGER NOT NULL,
    swept_variable    TEXT NOT NULL,                                 -- 本轮唯一扫的变量（opening_hook_3s/intent/...）
    status            TEXT NOT NULL DEFAULT 'open',
    winning_arm_id    UUID,                                          -- 锁定后填（弱引用 experiment_arms.id，避免环 FK）
    baseline_snapshot JSONB,                                         -- 锁定后整份 baseline 快照（防覆盖追溯）
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT experiment_rounds_round_pos CHECK (round_no >= 1),
    CONSTRAINT experiment_rounds_status_check CHECK (status IN ('open', 'locked')),
    CONSTRAINT experiment_rounds_uq UNIQUE (experiment_id, round_no)
);
CREATE INDEX IF NOT EXISTS idx_exp_rounds_experiment
    ON pipeline.experiment_rounds (experiment_id, round_no);

COMMENT ON TABLE pipeline.experiment_rounds IS
    '一行=一个 flight=只扫一个变量；UNIQUE(experiment_id,round_no) 强制单变量纪律。';

-- ────────────────────────────────────────────────────────
-- ③ arm（一行 = 某 round 某臂 = 一个变量取值 = 一条 director_brief；一臂多视频归属走 assets.experiment_arm_id）
-- ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline.experiment_arms (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    round_id           UUID NOT NULL REFERENCES pipeline.experiment_rounds(id) ON DELETE CASCADE,
    experiment_id      UUID NOT NULL,                                -- denorm 双跳
    sku_id             VARCHAR(64) NOT NULL,                         -- denorm
    round_no           INTEGER NOT NULL,
    swept_variable     TEXT NOT NULL,
    variable_value     TEXT NOT NULL,                                -- 该臂的变量取值（如"悬念式钩子"）
    arm_label          TEXT NOT NULL,                                -- A/B/C...
    script_id          UUID REFERENCES pipeline.scripts(id) ON DELETE SET NULL,  -- 该臂的 director_brief
    hypothesis         TEXT,                                         -- LLM 填，不参与判定
    is_winner          BOOLEAN NOT NULL DEFAULT FALSE,
    is_baseline_locked BOOLEAN NOT NULL DEFAULT FALSE,
    forced             BOOLEAN NOT NULL DEFAULT FALSE,               -- R-15：n<5 强行锁 winner 留痕
    decided_reason     TEXT,                                         -- 只允许确定性串（R-14，禁因果）
    notes              TEXT,
    actor_id           VARCHAR(64) DEFAULT 'yark',
    adopted_by         VARCHAR(64) DEFAULT 'yark',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT experiment_arms_round_pos CHECK (round_no >= 1),
    CONSTRAINT experiment_arms_label_check CHECK (arm_label ~ '^[A-Z]$'),
    CONSTRAINT experiment_arms_uq UNIQUE (round_id, arm_label)
);
CREATE INDEX IF NOT EXISTS idx_arms_experiment
    ON pipeline.experiment_arms (experiment_id, round_no, arm_label);
CREATE INDEX IF NOT EXISTS idx_arms_script
    ON pipeline.experiment_arms (script_id) WHERE script_id IS NOT NULL;

COMMENT ON TABLE pipeline.experiment_arms IS
    '一行=一臂=一个变量取值=一条 director_brief；一臂可挂多条视频（归属走 assets.experiment_arm_id 一对多）。';

-- ────────────────────────────────────────────────────────
-- ④ assets：denorm 实验维度（一对多：一臂多视频；ad_metrics 投后真值已在本表）
-- ────────────────────────────────────────────────────────
ALTER TABLE pipeline.assets
    ADD COLUMN IF NOT EXISTS experiment_id     UUID REFERENCES pipeline.experiments(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS experiment_arm_id UUID REFERENCES pipeline.experiment_arms(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_assets_experiment_arm
    ON pipeline.assets (experiment_arm_id) WHERE experiment_arm_id IS NOT NULL;

-- ────────────────────────────────────────────────────────
-- ⑤ scripts：intent 维度（director_brief 专属；可被 A/B 当变量扫；generic=无意图历史行）
-- ────────────────────────────────────────────────────────
ALTER TABLE pipeline.scripts ADD COLUMN IF NOT EXISTS intent TEXT;
ALTER TABLE pipeline.scripts DROP CONSTRAINT IF EXISTS scripts_intent_check;
ALTER TABLE pipeline.scripts ADD CONSTRAINT scripts_intent_check
    CHECK (intent IS NULL OR intent IN ('planting', 'harvest', 'soft_ad', 'hard_ad', 'generic'));
CREATE INDEX IF NOT EXISTS idx_scripts_intent
    ON pipeline.scripts (sku_id, intent, created_at DESC) WHERE intent IS NOT NULL;
COMMENT ON COLUMN pipeline.scripts.intent IS
    'director_brief 投放意图：planting/harvest/soft_ad/hard_ad（generic=无意图历史行）；可被实验当单变量扫。';

-- ────────────────────────────────────────────────────────
-- ⑥ prompt_rules：市场数据→规则桥的判重锚（软引用无 FK，对齐 051 source_tool_call_id）
-- ────────────────────────────────────────────────────────
ALTER TABLE knowledge.prompt_rules
    ADD COLUMN IF NOT EXISTS source_experiment_id UUID,
    ADD COLUMN IF NOT EXISTS source_round_var TEXT;
CREATE INDEX IF NOT EXISTS idx_prompt_rules_source_experiment
    ON knowledge.prompt_rules(source_experiment_id) WHERE source_experiment_id IS NOT NULL;
COMMENT ON COLUMN knowledge.prompt_rules.source_experiment_id IS
    '若规则源自某实验沉淀（experiment_distill），记 experiment_id；配 source_round_var 做判重（同实验同变量不重复提炼）。无 FK（跨 schema）。';

-- ────────────────────────────────────────────────────────
-- ⑦ 汇总视图：按 north_star_metric 动态从 ad_metrics JSONB 取真值，winner 排序唯一口径=avg
--    n_videos<5 标 preliminary（R-15）；只算 status IN ('published','adopted') 的 asset。
-- ────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW pipeline.v_experiment_round_results AS
WITH arm_assets AS (
    SELECT
        e.id   AS experiment_id,
        e.sku_id,
        e.intent,
        e.north_star_metric,
        e.north_star_direction,
        arm.id AS arm_id,
        arm.round_no,
        arm.arm_label,
        arm.swept_variable,
        arm.variable_value,
        arm.hypothesis,
        arm.script_id,
        arm.is_winner,
        arm.is_baseline_locked,
        arm.forced,
        a.id   AS asset_id,
        CASE
            WHEN a.ad_metrics ? e.north_star_metric
                 AND (a.ad_metrics ->> e.north_star_metric) ~ '^-?[0-9]+(\.[0-9]+)?%?$'
            THEN rtrim(a.ad_metrics ->> e.north_star_metric, '%')::numeric
            ELSE NULL
        END AS ns_value
    FROM pipeline.experiments e
    JOIN pipeline.experiment_arms arm ON arm.experiment_id = e.id
    LEFT JOIN pipeline.assets a
           ON a.experiment_arm_id = arm.id
          AND a.status IN ('published', 'adopted')
)
SELECT
    experiment_id, sku_id, intent, round_no, arm_id, arm_label,
    swept_variable, variable_value, hypothesis, script_id,
    north_star_metric, north_star_direction,
    is_winner, is_baseline_locked, forced,
    count(ns_value)            AS n_videos,        -- 有效回传的视频条数
    round(avg(ns_value), 4)    AS north_star_avg,  -- winner 排序唯一口径
    round(sum(ns_value), 4)    AS north_star_sum,  -- 仅展示，不排序
    CASE WHEN count(ns_value) < 5 THEN 'preliminary' ELSE 'sufficient' END AS sample_status
FROM arm_assets
GROUP BY
    experiment_id, sku_id, intent, round_no, arm_id, arm_label,
    swept_variable, variable_value, hypothesis, script_id,
    north_star_metric, north_star_direction, is_winner, is_baseline_locked, forced
ORDER BY experiment_id, round_no, arm_label;

COMMENT ON VIEW pipeline.v_experiment_round_results IS
    '实验每轮每臂的北极星汇总：avg=winner 排序唯一口径，n_videos<5 标 preliminary（R-15 工程门槛，非统计显著）。';

-- ────────────────────────────────────────────────────────
-- ⑧ v_asset_full_lineage 重建：纯加法补实验维度 + scripts.intent
-- ────────────────────────────────────────────────────────
-- DROP + CREATE（不用 CREATE OR REPLACE：新列必须追加在末尾，否则报"不能改列名"）
DROP VIEW IF EXISTS pipeline.v_asset_full_lineage;
CREATE VIEW pipeline.v_asset_full_lineage AS
SELECT
    a.id AS asset_id,
    a.sku_id,
    a.asset_type,
    a.file_url,
    a.external_video_id,
    a.external_creative_id,
    a.ad_metrics,
    a.status AS asset_status,
    a.created_at AS asset_created_at,

    s.id AS script_id,
    s.script_md,
    s.target_purpose,

    p.id AS audience_pack_id,
    p.pack_md,
    p.dmp_tags,

    r.id AS audience_record_id,
    r.name AS audience_name,
    r.kb_doc AS audience_kb_doc,
    r.layer_tags AS audience_layer_tags,

    ar.id AS audience_run_id,
    ar.recall_meta AS audience_recall_meta,

    mr.id AS matrix_run_id,
    mr.matrix_md,

    sku.name AS sku_name,
    sku.category AS sku_category,

    -- 实验维度（052 新增，追加在末尾保兼容）
    a.experiment_id,
    a.experiment_arm_id,
    exp.intent              AS experiment_intent,
    exp.north_star_metric   AS experiment_north_star,
    exarm.arm_label,
    exarm.swept_variable,
    exarm.variable_value,
    exarm.is_winner,
    s.intent                AS script_intent
FROM pipeline.assets a
LEFT JOIN pipeline.scripts s ON s.id = a.script_id
LEFT JOIN pipeline.audience_packs p ON p.id = a.audience_pack_id
LEFT JOIN pipeline.audience_records r ON r.id = a.audience_record_id
LEFT JOIN pipeline.audience_runs ar ON ar.id = r.audience_run_id
LEFT JOIN pipeline.matrix_runs mr ON mr.id = a.matrix_run_id
LEFT JOIN pipeline.experiments exp ON exp.id = a.experiment_id
LEFT JOIN pipeline.experiment_arms exarm ON exarm.id = a.experiment_arm_id
LEFT JOIN public.mvp_sku sku ON sku.id = a.sku_id;

COMMENT ON VIEW pipeline.v_asset_full_lineage IS
    '投后回传 ad_metrics 后按 asset_id 一句 SELECT 拉 SKU/卖点/人群/圈包/脚本全链路（052 补实验维度 intent/arm/is_winner）';

-- ────────────────────────────────────────────────────────
-- ⑨ updated_at 触发器（3 新表，照抄 021/047 防御式：函数存在才挂）
-- ────────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_pipeline_experiments_touch ON pipeline.experiments;
        CREATE TRIGGER trg_pipeline_experiments_touch
            BEFORE UPDATE ON pipeline.experiments
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_pipeline_experiment_rounds_touch ON pipeline.experiment_rounds;
        CREATE TRIGGER trg_pipeline_experiment_rounds_touch
            BEFORE UPDATE ON pipeline.experiment_rounds
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_pipeline_experiment_arms_touch ON pipeline.experiment_arms;
        CREATE TRIGGER trg_pipeline_experiment_arms_touch
            BEFORE UPDATE ON pipeline.experiment_arms
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;
