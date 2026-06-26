-- ============================================================
-- Migration 066: 内容↔人群向量匹配（投前预测分）+ 北极星闭环（同时升级）
--
-- 老板要"向量相似度 + 北极星匹配度 同时升级"：投前用内容(文字/画面/音乐)↔人群的
-- 余弦相似度做预测匹配分（排候选臂、少烧广告费），投后北极星做真值，两者配对在臂上
-- 形成闭环（投后校准投前向量信任度/权重）。
--
-- 复用现成 embedding 基建（embed_texts → gemini 1536 维；pgvector + HNSW + <=> 余弦，
-- 已在 KB 检索跑生产）。本 migration 只加 2 张向量表 + 臂级预测分列 + 视图加列。纯加法。
-- 铁律：预测分只是投前冷启动代理，winner 永远只认北极星，预测分只当旁证列（同曝光量旁证）。
-- ============================================================

-- ① 人群向量（一画像一行，upsert）：embed 画像「1.3 算法信号原料」段
CREATE TABLE IF NOT EXISTS pipeline.audience_vectors (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portrait_id UUID NOT NULL REFERENCES pipeline.audience_portraits(id) ON DELETE CASCADE,
    sku_id      VARCHAR(64) NOT NULL,
    source_text TEXT NOT NULL,                 -- 被 embed 的原文（算法信号原料段）
    embedding   vector(1536) NOT NULL,          -- gemini-embedding-2-preview，与 KB 同空间
    model       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT audience_vectors_uq UNIQUE (portrait_id)
);
CREATE INDEX IF NOT EXISTS idx_audience_vectors_sku ON pipeline.audience_vectors (sku_id);
CREATE INDEX IF NOT EXISTS idx_audience_vectors_hnsw
    ON pipeline.audience_vectors USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);

COMMENT ON TABLE pipeline.audience_vectors IS
    '人群算法信号 embed 向量（一画像一行）；投前匹配分用，与内容向量同 1536 维空间算余弦。';

-- ② 内容向量（一脚本三路三行，track 区分，按 (script_id,track) upsert）
CREATE TABLE IF NOT EXISTS pipeline.content_vectors (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    script_id    UUID NOT NULL REFERENCES pipeline.scripts(id) ON DELETE CASCADE,
    sku_id       VARCHAR(64) NOT NULL,
    track        TEXT NOT NULL,                 -- text / visual / music
    source_field TEXT,                          -- 这路文本从哪来（三向量段名/scenes字段/whole_prompt）
    source_text  TEXT NOT NULL,
    embedding    vector(1536) NOT NULL,
    model        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT content_vectors_track_check CHECK (track IN ('text', 'visual', 'music')),
    CONSTRAINT content_vectors_uq UNIQUE (script_id, track)
);
CREATE INDEX IF NOT EXISTS idx_content_vectors_sku ON pipeline.content_vectors (sku_id);
CREATE INDEX IF NOT EXISTS idx_content_vectors_script ON pipeline.content_vectors (script_id);
CREATE INDEX IF NOT EXISTS idx_content_vectors_hnsw
    ON pipeline.content_vectors USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);

COMMENT ON TABLE pipeline.content_vectors IS
    '内容三路(文字/画面/音乐) embed 向量（一脚本三行）；投前各路 vs 人群向量算余弦，分开看 + 简单平均。';

-- ③ 臂级投前预测匹配分（旁证，不判 winner；对齐 053 加 visual_prescreen 的纯加法）
ALTER TABLE pipeline.experiment_arms
    ADD COLUMN IF NOT EXISTS predicted_match_score NUMERIC,   -- 三路简单平均（0-1）
    ADD COLUMN IF NOT EXISTS predicted_match_meta  JSONB;     -- {tracks:{text,visual,music}, portrait_id, weights}

-- ④ v_experiment_round_results 加 predicted_match_score（跟北极星并排 + 闭环配对锚）
--    重建自 064 版（含 impressions_sum），末尾追加 predicted_match_score（CREATE OR REPLACE 列序兼容）
CREATE OR REPLACE VIEW pipeline.v_experiment_round_results AS
WITH arm_assets AS (
    SELECT
        e.id   AS experiment_id, e.sku_id, e.intent,
        e.north_star_metric, e.north_star_direction,
        arm.id AS arm_id, arm.round_no, arm.arm_label,
        arm.swept_variable, arm.variable_value, arm.hypothesis, arm.script_id,
        arm.is_winner, arm.is_baseline_locked, arm.forced, arm.production_mode,
        arm.predicted_match_score,
        a.id   AS asset_id,
        CASE
            WHEN a.ad_metrics ? e.north_star_metric
                 AND (a.ad_metrics ->> e.north_star_metric) ~ '^-?[0-9]+(\.[0-9]+)?%?$'
            THEN rtrim(a.ad_metrics ->> e.north_star_metric, '%')::numeric
            ELSE NULL
        END AS ns_value,
        CASE
            WHEN a.ad_metrics ? 'impressions'
                 AND (a.ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'impressions')::numeric
            ELSE NULL
        END AS imp_value
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
    count(ns_value)            AS n_videos,
    round(avg(ns_value), 4)    AS north_star_avg,
    round(sum(ns_value), 4)    AS north_star_sum,
    CASE WHEN count(ns_value) < 5 THEN 'preliminary' ELSE 'sufficient' END AS sample_status,
    production_mode,
    sum(imp_value)             AS impressions_sum,
    predicted_match_score                          -- 066 追加：投前向量预测分（旁证，不判 winner）
FROM arm_assets
GROUP BY
    experiment_id, sku_id, intent, round_no, arm_id, arm_label,
    swept_variable, variable_value, hypothesis, script_id,
    north_star_metric, north_star_direction, is_winner, is_baseline_locked, forced,
    production_mode, predicted_match_score
ORDER BY experiment_id, round_no, arm_label;

COMMENT ON VIEW pipeline.v_experiment_round_results IS
    '实验每轮每臂北极星汇总：avg=winner 唯一口径；064 加曝光量旁证、066 加投前向量预测分(predicted_match_score) 旁证——两旁证都只辅助判断、不参与排 winner。';
