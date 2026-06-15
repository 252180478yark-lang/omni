-- ============================================================
-- Migration 054: v_experiment_round_results 视图补 production_mode 列
--
-- 053 给 experiment_arms 加了 production_mode，但汇总视图没带出来——前端 mixed 实验
-- （真人 vs AI）要逐臂显示模式只能推导。这里把 arm.production_mode 透进视图（append 在
-- 末尾，CREATE OR REPLACE 列序兼容）。纯加法。
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
    count(ns_value)            AS n_videos,
    round(avg(ns_value), 4)    AS north_star_avg,
    round(sum(ns_value), 4)    AS north_star_sum,
    CASE WHEN count(ns_value) < 5 THEN 'preliminary' ELSE 'sufficient' END AS sample_status,
    production_mode
FROM arm_assets
GROUP BY
    experiment_id, sku_id, intent, round_no, arm_id, arm_label,
    swept_variable, variable_value, hypothesis, script_id,
    north_star_metric, north_star_direction, is_winner, is_baseline_locked, forced,
    production_mode
ORDER BY experiment_id, round_no, arm_label;
