-- Migration 071: weighted formal planting metrics can use a platform rate only
-- when strict normalization stored the matching denominator and an effective
-- numerator.  The canonical experiment view keeps its stable 34-column shape;
-- experiment_status joins this additive arm-level view for pooled diagnostics.

CREATE OR REPLACE VIEW pipeline.v_experiment_arm_pooled_metrics AS
WITH eligible_assets AS (
    SELECT
        arm.id AS arm_id,
        a.id AS asset_id,
        CASE
            WHEN (a.ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'impressions')::numeric > 0
            THEN (a.ad_metrics ->> 'impressions')::numeric
            ELSE NULL
        END AS impression_value,
        CASE
            WHEN a.generation_set_id IS NOT NULL
             AND a.ad_metrics #>> '{_validation,metric_poolability,a3_ratio}' = 'true'
             AND (a.ad_metrics ->> 'new_a3') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'new_a3')::numeric
            WHEN a.generation_set_id IS NOT NULL
             AND a.ad_metrics #>> '{_validation,metric_poolability,a3_ratio}' = 'true'
             AND a.ad_metrics #>> '{_provenance,a3_ratio}' = 'derived_from_rate_and_denominator'
             AND (a.ad_metrics #>> '{_effective_numerators,new_a3}') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics #>> '{_effective_numerators,new_a3}')::numeric
            WHEN a.generation_set_id IS NULL
             AND (a.ad_metrics ->> 'new_a3') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'new_a3')::numeric
            ELSE NULL
        END AS a3_numerator_value,
        CASE
            WHEN (
                    a.generation_set_id IS NULL
                    OR a.ad_metrics #>> '{_validation,metric_poolability,a3_ratio}' = 'true'
                 )
             AND (a.ad_metrics ->> 'a3_eligible_users') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'a3_eligible_users')::numeric > 0
            THEN (a.ad_metrics ->> 'a3_eligible_users')::numeric
            ELSE NULL
        END AS a3_denominator_value,
        CASE
            WHEN (
                    a.generation_set_id IS NULL
                    OR a.ad_metrics #>> '{_validation,metric_poolability,cpm}' = 'true'
                 )
             AND (a.ad_metrics ->> 'spend') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'spend')::numeric
            ELSE NULL
        END AS spend_value,
        CASE
            WHEN (
                    a.generation_set_id IS NULL
                    OR a.ad_metrics #>> '{_validation,metric_poolability,cpm}' = 'true'
                 )
             AND (a.ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'impressions')::numeric > 0
            THEN (a.ad_metrics ->> 'impressions')::numeric
            ELSE NULL
        END AS cpm_impression_value,
        CASE
            WHEN (
                    a.generation_set_id IS NULL
                    OR a.ad_metrics #>> '{_validation,metric_poolability,cpm}' = 'true'
                 )
             AND a.ad_metrics ->> 'currency' = 'CNY'
            THEN 1
            ELSE NULL
        END AS cny_marker,
        CASE
            WHEN a.generation_set_id IS NOT NULL
             AND a.ad_metrics #>> '{_validation,metric_poolability,play_3s_rate}' = 'true'
             AND (a.ad_metrics ->> 'play_3s') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'play_3s')::numeric
            WHEN a.generation_set_id IS NOT NULL
             AND a.ad_metrics #>> '{_validation,metric_poolability,play_3s_rate}' = 'true'
             AND a.ad_metrics #>> '{_provenance,play_3s_rate}' = 'derived_from_rate_and_denominator'
             AND (a.ad_metrics #>> '{_effective_numerators,play_3s}') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics #>> '{_effective_numerators,play_3s}')::numeric
            WHEN a.generation_set_id IS NULL
             AND (a.ad_metrics ->> 'play_3s') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'play_3s')::numeric
            ELSE NULL
        END AS play_3s_value,
        CASE
            WHEN (
                    a.generation_set_id IS NULL
                    OR a.ad_metrics #>> '{_validation,metric_poolability,play_3s_rate}' = 'true'
                 )
             AND (a.ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'impressions')::numeric > 0
            THEN (a.ad_metrics ->> 'impressions')::numeric
            ELSE NULL
        END AS play_3s_impression_value,
        CASE
            WHEN a.generation_set_id IS NOT NULL
             AND a.ad_metrics #>> '{_validation,metric_poolability,completion_rate}' = 'true'
             AND (a.ad_metrics ->> 'play_complete') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'play_complete')::numeric
            WHEN a.generation_set_id IS NOT NULL
             AND a.ad_metrics #>> '{_validation,metric_poolability,completion_rate}' = 'true'
             AND a.ad_metrics #>> '{_provenance,completion_rate}' = 'derived_from_rate_and_denominator'
             AND (a.ad_metrics #>> '{_effective_numerators,play_complete}') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics #>> '{_effective_numerators,play_complete}')::numeric
            WHEN a.generation_set_id IS NULL
             AND (a.ad_metrics ->> 'play_complete') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'play_complete')::numeric
            ELSE NULL
        END AS completion_numerator_value,
        CASE
            WHEN (
                    a.generation_set_id IS NULL
                    OR a.ad_metrics #>> '{_validation,metric_poolability,completion_rate}' = 'true'
                 )
             AND (a.ad_metrics ->> 'completion_denominator') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'completion_denominator')::numeric > 0
            THEN (a.ad_metrics ->> 'completion_denominator')::numeric
            ELSE NULL
        END AS completion_denominator_value,
        CASE
            WHEN (
                    a.generation_set_id IS NULL
                    OR a.ad_metrics #>> '{_validation,metric_poolability,completion_rate}' = 'true'
                 )
            THEN NULLIF(btrim(a.ad_metrics ->> 'completion_denominator_type'), '')
            ELSE NULL
        END AS completion_denominator_type_value
    FROM pipeline.experiment_arms arm
    LEFT JOIN pipeline.assets a
      ON a.experiment_arm_id = arm.id
     AND a.status IN ('published', 'adopted')
     AND (
          a.generation_set_id IS NOT NULL
          OR COALESCE(a.ad_metrics #> '{_validation,suspect}', 'false'::jsonb) = 'false'::jsonb
          OR a.ad_metrics #> '{_validation,suspect}' = '{}'::jsonb
     )
     AND (
          a.generation_set_id IS NULL
          OR EXISTS (
              SELECT 1
              FROM pipeline.video_generation_sets gs
              WHERE gs.id = a.generation_set_id
                AND gs.status = 'adopted'
                AND gs.post_video_group_gate @> '{"pass": true}'::jsonb
                AND jsonb_typeof(gs.selected_assets) = 'array'
                AND gs.selected_assets ? a.id::text
          )
     )
),
rollup AS (
    SELECT
        arm_id,
        count(asset_id) AS eligible_asset_count,
        count(impression_value) AS impression_count,
        sum(impression_value) AS raw_impression_sum,
        count(a3_numerator_value) AS a3_numerator_count,
        count(a3_denominator_value) AS a3_denominator_count,
        sum(a3_numerator_value) AS raw_a3_numerator_sum,
        sum(a3_denominator_value) AS raw_a3_denominator_sum,
        count(spend_value) AS spend_count,
        count(cpm_impression_value) AS cpm_impression_count,
        count(cny_marker) AS cny_count,
        sum(spend_value) AS raw_spend_sum,
        sum(cpm_impression_value) AS raw_cpm_impression_sum,
        count(play_3s_value) AS play_3s_count,
        count(play_3s_impression_value) AS play_3s_impression_count,
        sum(play_3s_value) AS raw_play_3s_sum,
        sum(play_3s_impression_value) AS raw_play_3s_impression_sum,
        count(completion_numerator_value) AS completion_numerator_count,
        count(completion_denominator_value) AS completion_denominator_count,
        count(completion_denominator_type_value) AS completion_type_count,
        count(DISTINCT completion_denominator_type_value) AS completion_type_distinct_count,
        min(completion_denominator_type_value) AS raw_completion_denominator_type,
        sum(completion_numerator_value) AS raw_completion_numerator_sum,
        sum(completion_denominator_value) AS raw_completion_denominator_sum
    FROM eligible_assets
    GROUP BY arm_id
),
evaluated AS (
    SELECT
        rollup.*,
        eligible_asset_count > 0
            AND a3_numerator_count = eligible_asset_count
            AND a3_denominator_count = eligible_asset_count
            AS a3_coverage_complete,
        eligible_asset_count > 0
            AND spend_count = eligible_asset_count
            AND cpm_impression_count = eligible_asset_count
            AND cny_count = eligible_asset_count
            AS cpm_coverage_complete,
        eligible_asset_count > 0
            AND play_3s_count = eligible_asset_count
            AND play_3s_impression_count = eligible_asset_count
            AS play_3s_coverage_complete,
        eligible_asset_count > 0
            AND completion_numerator_count = eligible_asset_count
            AND completion_denominator_count = eligible_asset_count
            AND completion_type_count = eligible_asset_count
            AND completion_type_distinct_count = 1
            AS completion_coverage_complete
    FROM rollup
)
SELECT
    arm_id,
    eligible_asset_count,
    CASE WHEN a3_coverage_complete THEN raw_a3_numerator_sum END AS a3_numerator_sum,
    CASE WHEN a3_coverage_complete THEN raw_a3_denominator_sum END AS a3_denominator_sum,
    CASE WHEN a3_coverage_complete
         THEN round(raw_a3_numerator_sum / NULLIF(raw_a3_denominator_sum, 0), 6)
         END AS a3_ratio_pooled,
    CASE WHEN cpm_coverage_complete THEN raw_spend_sum END AS spend_sum,
    CASE WHEN cpm_coverage_complete
         THEN round(raw_spend_sum / NULLIF(raw_cpm_impression_sum, 0) * 1000, 6)
         END AS cpm_pooled,
    CASE WHEN play_3s_coverage_complete THEN raw_play_3s_sum END AS play_3s_sum,
    CASE WHEN play_3s_coverage_complete
         THEN round(raw_play_3s_sum / NULLIF(raw_play_3s_impression_sum, 0), 6)
         END AS play_3s_rate_pooled,
    CASE WHEN completion_coverage_complete THEN raw_completion_numerator_sum END
        AS completion_numerator_sum,
    CASE WHEN completion_coverage_complete THEN raw_completion_denominator_sum END
        AS completion_denominator_sum,
    CASE WHEN completion_coverage_complete THEN raw_completion_denominator_type END
        AS completion_denominator_type,
    CASE WHEN completion_coverage_complete
         THEN round(raw_completion_numerator_sum / NULLIF(raw_completion_denominator_sum, 0), 6)
         END AS completion_rate_pooled,
    a3_coverage_complete AS metric_coverage_complete,
    cpm_coverage_complete,
    play_3s_coverage_complete,
    completion_coverage_complete,
    CASE WHEN impression_count = eligible_asset_count
         AND eligible_asset_count > 0 THEN raw_impression_sum END AS impressions_sum
FROM evaluated;

COMMENT ON VIEW pipeline.v_experiment_arm_pooled_metrics IS
    'Arm-level formal planting metric pool: raw counts first, otherwise strict same-denominator effective numerators; legacy null-generation-set rows keep raw-count compatibility.';

-- Recreate the canonical 34-column experiment view with metric-scoped
-- eligibility for formal generation-set assets.  An unrelated suspect metric
-- (for example hand-filled ROI) must not suppress a valid formal completion
-- rate.  Planting A3 remains stricter because its winner is the separately
-- pooled numerator/denominator rate.  Legacy NULL-set assets deliberately
-- retain the historical whole-row suspect filter.
CREATE OR REPLACE VIEW pipeline.v_experiment_round_results AS
WITH arm_assets AS (
    SELECT
        e.id AS experiment_id,
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
        arm.predicted_match_score,
        a.id AS asset_id,
        CASE
            WHEN a.ad_metrics ? e.north_star_metric
             AND (a.ad_metrics ->> e.north_star_metric) ~ '^-?[0-9]+(\.[0-9]+)?%?$'
            THEN rtrim(a.ad_metrics ->> e.north_star_metric, '%')::numeric
            ELSE NULL
        END AS ns_value,
        CASE
            WHEN (a.ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'impressions')::numeric
            ELSE NULL
        END AS impression_value,
        CASE
            WHEN (a.ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'impressions')::numeric > 0
            THEN (a.ad_metrics ->> 'impressions')::numeric
            ELSE NULL
        END AS positive_impression_value,
        CASE
            WHEN (a.ad_metrics ->> 'new_a3') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'new_a3')::numeric
            ELSE NULL
        END AS a3_numerator_value,
        CASE
            WHEN (a.ad_metrics ->> 'a3_eligible_users') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'a3_eligible_users')::numeric > 0
            THEN (a.ad_metrics ->> 'a3_eligible_users')::numeric
            ELSE NULL
        END AS a3_denominator_value,
        CASE
            WHEN (a.ad_metrics ->> 'spend') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'spend')::numeric
            ELSE NULL
        END AS spend_value,
        CASE
            WHEN a.ad_metrics ->> 'currency' = 'CNY' THEN 1
            ELSE NULL
        END AS cny_marker,
        CASE
            WHEN (a.ad_metrics ->> 'play_3s') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'play_3s')::numeric
            ELSE NULL
        END AS play_3s_value,
        CASE
            WHEN (a.ad_metrics ->> 'play_complete') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'play_complete')::numeric
            ELSE NULL
        END AS completion_numerator_value,
        CASE
            WHEN (a.ad_metrics ->> 'completion_denominator') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'completion_denominator')::numeric > 0
            THEN (a.ad_metrics ->> 'completion_denominator')::numeric
            ELSE NULL
        END AS completion_denominator_value,
        NULLIF(btrim(a.ad_metrics ->> 'completion_denominator_type'), '')
            AS completion_denominator_type_value
    FROM pipeline.experiments e
    JOIN pipeline.experiment_arms arm
      ON arm.experiment_id = e.id
    LEFT JOIN pipeline.assets a
      ON a.experiment_arm_id = arm.id
     AND a.status IN ('published', 'adopted')
     AND CASE
          WHEN a.generation_set_id IS NULL THEN
              COALESCE(
                  a.ad_metrics #> '{_validation,suspect}',
                  'false'::jsonb
              ) = 'false'::jsonb
              OR a.ad_metrics #> '{_validation,suspect}' = '{}'::jsonb
          WHEN e.intent = 'planting'
           AND e.north_star_metric = 'a3_ratio' THEN
              a.ad_metrics #>> ARRAY['_validation','metric_poolability',e.north_star_metric]
                  = 'true'
          WHEN a.ad_metrics #> '{_validation,suspect}' IS NULL THEN TRUE
          WHEN a.ad_metrics #> '{_validation,suspect}' = 'false'::jsonb
              THEN TRUE
          WHEN jsonb_typeof(a.ad_metrics #> '{_validation,suspect}') = 'object'
              THEN NOT (
                  (a.ad_metrics #> '{_validation,suspect}')
                      ? e.north_star_metric
              )
          ELSE FALSE
         END
     AND (
          a.generation_set_id IS NULL
          OR EXISTS (
              SELECT 1
              FROM pipeline.video_generation_sets gs
              WHERE gs.id = a.generation_set_id
                AND gs.status = 'adopted'
                AND gs.post_video_group_gate @> '{"pass": true}'::jsonb
                AND jsonb_typeof(gs.selected_assets) = 'array'
                AND gs.selected_assets ? a.id::text
          )
     )
),
rollup AS (
    SELECT
        experiment_id,
        sku_id,
        intent,
        round_no,
        arm_id,
        arm_label,
        swept_variable,
        variable_value,
        hypothesis,
        script_id,
        north_star_metric,
        north_star_direction,
        is_winner,
        is_baseline_locked,
        forced,
        production_mode,
        predicted_match_score,
        count(ns_value) AS n_videos,
        avg(ns_value) AS legacy_north_star_avg,
        sum(ns_value) AS legacy_north_star_sum,
        sum(impression_value) AS legacy_impressions_sum,
        count(asset_id) AS eligible_asset_count,
        count(a3_numerator_value) AS a3_numerator_count,
        count(a3_denominator_value) AS a3_denominator_count,
        sum(a3_numerator_value) AS raw_a3_numerator_sum,
        sum(a3_denominator_value) AS raw_a3_denominator_sum,
        count(spend_value) AS spend_count,
        count(cny_marker) AS cny_count,
        sum(spend_value) AS raw_spend_sum,
        count(play_3s_value) AS play_3s_count,
        count(positive_impression_value) AS positive_impression_count,
        sum(play_3s_value) AS raw_play_3s_sum,
        sum(positive_impression_value) AS raw_positive_impression_sum,
        count(completion_numerator_value) AS completion_numerator_count,
        count(completion_denominator_value) AS completion_denominator_count,
        count(completion_denominator_type_value) AS completion_type_count,
        count(DISTINCT completion_denominator_type_value)
            AS completion_type_distinct_count,
        min(completion_denominator_type_value)
            AS raw_completion_denominator_type,
        sum(completion_numerator_value) AS raw_completion_numerator_sum,
        sum(completion_denominator_value) AS raw_completion_denominator_sum
    FROM arm_assets
    GROUP BY
        experiment_id, sku_id, intent, round_no, arm_id, arm_label,
        swept_variable, variable_value, hypothesis, script_id,
        north_star_metric, north_star_direction,
        is_winner, is_baseline_locked, forced,
        production_mode, predicted_match_score
),
evaluated AS (
    SELECT
        rollup.*,
        eligible_asset_count > 0
            AND a3_numerator_count = eligible_asset_count
            AND a3_denominator_count = eligible_asset_count
            AS a3_coverage_complete,
        eligible_asset_count > 0
            AND spend_count = eligible_asset_count
            AND positive_impression_count = eligible_asset_count
            AND cny_count = eligible_asset_count
            AS spend_coverage_complete,
        eligible_asset_count > 0
            AND play_3s_count = eligible_asset_count
            AND positive_impression_count = eligible_asset_count
            AS play_3s_coverage_complete,
        eligible_asset_count > 0
            AND completion_numerator_count = eligible_asset_count
            AND completion_denominator_count = eligible_asset_count
            AND completion_type_count = eligible_asset_count
            AND completion_type_distinct_count = 1
            AS completion_coverage_complete
    FROM rollup
)
SELECT
    experiment_id,
    sku_id,
    intent,
    round_no,
    arm_id,
    arm_label,
    swept_variable,
    variable_value,
    hypothesis,
    script_id,
    north_star_metric,
    north_star_direction,
    is_winner,
    is_baseline_locked,
    forced,
    n_videos,
    CASE
        WHEN intent = 'planting' THEN
            CASE WHEN a3_coverage_complete
                 THEN round(
                     raw_a3_numerator_sum
                     / NULLIF(raw_a3_denominator_sum, 0),
                     6
                 )
                 ELSE NULL END
        ELSE round(legacy_north_star_avg, 4)
    END AS north_star_avg,
    round(legacy_north_star_sum, 4) AS north_star_sum,
    CASE WHEN n_videos < 5 THEN 'preliminary' ELSE 'sufficient' END
        AS sample_status,
    production_mode,
    legacy_impressions_sum AS impressions_sum,
    predicted_match_score,
    CASE WHEN a3_coverage_complete THEN raw_a3_numerator_sum ELSE NULL END
        AS a3_numerator_sum,
    CASE WHEN a3_coverage_complete THEN raw_a3_denominator_sum ELSE NULL END
        AS a3_denominator_sum,
    CASE WHEN a3_coverage_complete
         THEN round(
             raw_a3_numerator_sum / NULLIF(raw_a3_denominator_sum, 0),
             6
         )
         ELSE NULL END AS a3_ratio_pooled,
    CASE WHEN spend_coverage_complete THEN raw_spend_sum ELSE NULL END
        AS spend_sum,
    CASE WHEN spend_coverage_complete
         THEN round(
             raw_spend_sum / NULLIF(raw_positive_impression_sum, 0) * 1000,
             6
         )
         ELSE NULL END AS cpm_pooled,
    CASE WHEN play_3s_coverage_complete THEN raw_play_3s_sum ELSE NULL END
        AS play_3s_sum,
    CASE WHEN play_3s_coverage_complete
         THEN round(
             raw_play_3s_sum / NULLIF(raw_positive_impression_sum, 0),
             6
         )
         ELSE NULL END AS play_3s_rate_pooled,
    CASE WHEN completion_coverage_complete
         THEN raw_completion_numerator_sum ELSE NULL END
        AS completion_numerator_sum,
    CASE WHEN completion_coverage_complete
         THEN raw_completion_denominator_sum ELSE NULL END
        AS completion_denominator_sum,
    CASE WHEN completion_coverage_complete
         THEN raw_completion_denominator_type ELSE NULL END
        AS completion_denominator_type,
    CASE WHEN completion_coverage_complete
         THEN round(
             raw_completion_numerator_sum
             / NULLIF(raw_completion_denominator_sum, 0),
             6
         )
         ELSE NULL END AS completion_rate_pooled,
    a3_coverage_complete AS metric_coverage_complete
FROM evaluated
ORDER BY experiment_id, round_no, arm_label;

COMMENT ON VIEW pipeline.v_experiment_round_results IS
    'Stable 34-column experiment results. Formal strict north stars use metric-scoped poolability; legacy NULL-set and unconfigured north stars retain whole-row suspect eligibility.';
