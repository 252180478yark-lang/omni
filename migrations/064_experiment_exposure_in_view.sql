-- ============================================================
-- Migration 064: v_experiment_round_results 视图补 impressions_sum（曝光量）
--
-- 背景（2026-06-26 内容版本迭代闭环·块0b）：判官小组指出 A/B 判 winner 的致命洞——
-- 北极星是【比率】（完播率/cvr），对曝光量完全脱敏：A 臂 800 曝光完播 28%、
-- B 臂 6 万曝光完播 26%，按 avg 排名 A 赢，但扛住 30 倍体量的 B 才是真赢。
-- 曝光量是判断"这个比率可不可信"的唯一旁证。本 migration 把每臂的 impressions 汇总
-- （sum）透进视图，experiment_status 据此露出曝光列 + "臂间曝光差≥3 倍 winner 存疑"提示。
--
-- impressions 早在 ad_metrics 白名单（ad_metrics_validation._WHITELIST，count 类）；
-- 这里只是把它从 ad_metrics JSONB 聚合出来。纯加法：impressions_sum 追加在视图末尾
-- （CREATE OR REPLACE 列序兼容，同 054 production_mode 的加法手法）。
-- ============================================================

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
        arm.production_mode,
        a.id   AS asset_id,
        CASE
            WHEN a.ad_metrics ? e.north_star_metric
                 AND (a.ad_metrics ->> e.north_star_metric) ~ '^-?[0-9]+(\.[0-9]+)?%?$'
            THEN rtrim(a.ad_metrics ->> e.north_star_metric, '%')::numeric
            ELSE NULL
        END AS ns_value,
        -- 曝光量（整数，无 %）：用于判断北极星比率的可信度（旁证），不参与 winner 排序
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
    sum(imp_value)             AS impressions_sum   -- 064 追加：曝光量旁证（NULL=该臂没回传曝光）
FROM arm_assets
GROUP BY
    experiment_id, sku_id, intent, round_no, arm_id, arm_label,
    swept_variable, variable_value, hypothesis, script_id,
    north_star_metric, north_star_direction, is_winner, is_baseline_locked, forced,
    production_mode
ORDER BY experiment_id, round_no, arm_label;

COMMENT ON VIEW pipeline.v_experiment_round_results IS
    '实验每轮每臂的北极星汇总：avg=winner 排序唯一口径，n_videos<5 标 preliminary（R-15）；064 加 impressions_sum 作比率可信度旁证（臂间曝光差≥3 倍则 winner 存疑）。';
