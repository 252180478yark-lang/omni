-- ============================================================
-- Migration 065: v_content_version_changelog 视图（内容版本迭代闭环·块C）
--
-- 老板要"记录做了哪些变化"——每版（每轮）相对上一版改了哪个变量、取值定成啥、这版赢面多少，
-- 串成演化树。纯派生视图（零写入）：靠 experiment_rounds（每轮扫什么 + 锁定快照）+ 获胜臂
-- + v_experiment_round_results（赢面 avg/n/曝光）拼出。"从X→到Y"的 diff 在 tool 层（experiment_changelog）
-- 按相邻轮 baseline_snapshot 算（SQL 不便做前后对比）。
-- ============================================================

CREATE OR REPLACE VIEW pipeline.v_content_version_changelog AS
SELECT
    r.experiment_id,
    r.sku_id,
    r.round_no,
    r.swept_variable,
    r.status,                                  -- open / locked
    r.winning_arm_id,
    r.baseline_snapshot,                       -- 锁定时整份 baseline 快照（diff 用）
    wa.arm_label       AS winner_label,
    wa.variable_value  AS winner_value,
    wa.forced          AS winner_forced,
    res.north_star_avg AS winner_north_star_avg,
    res.n_videos       AS winner_n_videos,
    res.impressions_sum AS winner_impressions,
    (SELECT count(*) FROM pipeline.experiment_arms a2 WHERE a2.round_id = r.id) AS n_arms,
    r.updated_at       AS locked_at            -- 锁定触发 updated_at（touch_updated_at 触发器）
FROM pipeline.experiment_rounds r
LEFT JOIN pipeline.experiment_arms wa
       ON wa.id = r.winning_arm_id
LEFT JOIN pipeline.v_experiment_round_results res
       ON res.experiment_id = r.experiment_id
      AND res.round_no = r.round_no
      AND res.arm_id = r.winning_arm_id
ORDER BY r.experiment_id, r.round_no;

COMMENT ON VIEW pipeline.v_content_version_changelog IS
    '内容版本变更日志（块C）：逐轮 swept_variable + 获胜取值 + 赢面(avg/n/曝光) + baseline 快照；"X→Y" diff 在 experiment_changelog tool 按相邻轮快照算。纯派生。';
