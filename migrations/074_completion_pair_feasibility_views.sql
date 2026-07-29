-- Migration 074: make completion count feasibility a canonical database rule.
--
-- A superficially valid arm aggregate can hide an impossible individual asset
-- (for example 120/100 plus four 0/100 assets = 120/500).  Both public result
-- views therefore fail completion coverage closed unless every included asset
-- has a non-negative numerator no greater than its positive denominator.  The
-- canonical experiment result view deliberately retains its stable 34 columns.

CREATE OR REPLACE VIEW pipeline.v_experiment_arm_pooled_metrics AS
WITH eligible_assets AS (
    SELECT
        arm.id AS arm_id,
        a.id AS asset_id,
        a.generation_set_id,
        a.ad_metrics,
        CASE
            WHEN (a.ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (a.ad_metrics ->> 'impressions')::numeric > 0
            THEN (a.ad_metrics ->> 'impressions')::numeric
        END AS impression_value
    FROM pipeline.experiment_arms arm
    LEFT JOIN pipeline.assets a
      ON a.experiment_arm_id = arm.id
     AND a.status IN ('published', 'adopted')
     AND (
          a.generation_set_id IS NOT NULL
          OR COALESCE(
                 a.ad_metrics #> '{_validation,suspect}',
                 'false'::jsonb
             ) = 'false'::jsonb
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
extracted AS (
    SELECT
        arm_id,
        asset_id,
        impression_value,
        CASE
            WHEN generation_set_id IS NOT NULL
             AND ad_metrics #>> '{_validation,metric_poolability,a3_ratio}' = 'true'
             AND (ad_metrics ->> 'new_a3') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics ->> 'new_a3')::numeric
            WHEN generation_set_id IS NOT NULL
             AND ad_metrics #>> '{_validation,metric_poolability,a3_ratio}' = 'true'
             AND ad_metrics #>> '{_provenance,a3_ratio}' =
                 'derived_from_rate_and_denominator'
             AND (ad_metrics #>> '{_effective_numerators,new_a3}')
                 ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics #>> '{_effective_numerators,new_a3}')::numeric
            WHEN generation_set_id IS NULL
             AND (ad_metrics ->> 'new_a3') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics ->> 'new_a3')::numeric
        END AS a3_numerator_value,
        CASE
            WHEN (
                    generation_set_id IS NULL
                    OR ad_metrics #>>
                        '{_validation,metric_poolability,a3_ratio}' = 'true'
                 )
             AND (ad_metrics ->> 'a3_eligible_users')
                 ~ '^[0-9]+(\.[0-9]+)?$'
             AND (ad_metrics ->> 'a3_eligible_users')::numeric > 0
            THEN (ad_metrics ->> 'a3_eligible_users')::numeric
        END AS a3_denominator_value,
        CASE
            WHEN (
                    generation_set_id IS NULL
                    OR ad_metrics #>> '{_validation,metric_poolability,cpm}' =
                       'true'
                 )
             AND (ad_metrics ->> 'spend') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics ->> 'spend')::numeric
        END AS spend_value,
        CASE
            WHEN (
                    generation_set_id IS NULL
                    OR ad_metrics #>> '{_validation,metric_poolability,cpm}' =
                       'true'
                 )
             AND (ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (ad_metrics ->> 'impressions')::numeric > 0
            THEN (ad_metrics ->> 'impressions')::numeric
        END AS cpm_impression_value,
        CASE
            WHEN (
                    generation_set_id IS NULL
                    OR ad_metrics #>> '{_validation,metric_poolability,cpm}' =
                       'true'
                 )
             AND ad_metrics ->> 'currency' = 'CNY'
            THEN 1
        END AS cny_marker,
        CASE
            WHEN generation_set_id IS NOT NULL
             AND ad_metrics #>>
                 '{_validation,metric_poolability,play_3s_rate}' = 'true'
             AND (ad_metrics ->> 'play_3s') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics ->> 'play_3s')::numeric
            WHEN generation_set_id IS NOT NULL
             AND ad_metrics #>>
                 '{_validation,metric_poolability,play_3s_rate}' = 'true'
             AND ad_metrics #>> '{_provenance,play_3s_rate}' =
                 'derived_from_rate_and_denominator'
             AND (ad_metrics #>> '{_effective_numerators,play_3s}')
                 ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics #>> '{_effective_numerators,play_3s}')::numeric
            WHEN generation_set_id IS NULL
             AND (ad_metrics ->> 'play_3s') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics ->> 'play_3s')::numeric
        END AS play_3s_value,
        CASE
            WHEN (
                    generation_set_id IS NULL
                    OR ad_metrics #>>
                       '{_validation,metric_poolability,play_3s_rate}' = 'true'
                 )
             AND (ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
             AND (ad_metrics ->> 'impressions')::numeric > 0
            THEN (ad_metrics ->> 'impressions')::numeric
        END AS play_3s_impression_value,
        CASE
            WHEN generation_set_id IS NOT NULL
             AND ad_metrics #>>
                 '{_validation,metric_poolability,completion_rate}' = 'true'
             AND (ad_metrics ->> 'play_complete') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics ->> 'play_complete')::numeric
            WHEN generation_set_id IS NOT NULL
             AND ad_metrics #>>
                 '{_validation,metric_poolability,completion_rate}' = 'true'
             AND ad_metrics #>> '{_provenance,completion_rate}' =
                 'derived_from_rate_and_denominator'
             AND (ad_metrics #>> '{_effective_numerators,play_complete}')
                 ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics #>>
                  '{_effective_numerators,play_complete}')::numeric
            WHEN generation_set_id IS NULL
             AND (ad_metrics ->> 'play_complete') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (ad_metrics ->> 'play_complete')::numeric
        END AS completion_numerator_candidate,
        CASE
            WHEN (
                    generation_set_id IS NULL
                    OR ad_metrics #>>
                       '{_validation,metric_poolability,completion_rate}' = 'true'
                 )
             AND (ad_metrics ->> 'completion_denominator')
                 ~ '^[0-9]+(\.[0-9]+)?$'
             AND (ad_metrics ->> 'completion_denominator')::numeric > 0
            THEN (ad_metrics ->> 'completion_denominator')::numeric
        END AS completion_denominator_value,
        CASE
            WHEN (
                    generation_set_id IS NULL
                    OR ad_metrics #>>
                       '{_validation,metric_poolability,completion_rate}' = 'true'
                 )
            THEN NULLIF(
                btrim(ad_metrics ->> 'completion_denominator_type'),
                ''
            )
        END AS completion_denominator_type_value
    FROM eligible_assets
),
feasible AS (
    SELECT
        extracted.*,
        CASE
            WHEN completion_numerator_candidate IS NOT NULL
             AND completion_denominator_value IS NOT NULL
             AND completion_numerator_candidate <= completion_denominator_value
            THEN completion_numerator_candidate
        END AS completion_numerator_value
    FROM extracted
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
        count(DISTINCT completion_denominator_type_value)
            AS completion_type_distinct_count,
        min(completion_denominator_type_value)
            AS raw_completion_denominator_type,
        sum(completion_numerator_value) AS raw_completion_numerator_sum,
        sum(completion_denominator_value) AS raw_completion_denominator_sum
    FROM feasible
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
    CASE WHEN a3_coverage_complete THEN raw_a3_numerator_sum END
        AS a3_numerator_sum,
    CASE WHEN a3_coverage_complete THEN raw_a3_denominator_sum END
        AS a3_denominator_sum,
    CASE WHEN a3_coverage_complete
         THEN round(
             raw_a3_numerator_sum / NULLIF(raw_a3_denominator_sum, 0),
             6
         ) END AS a3_ratio_pooled,
    CASE WHEN cpm_coverage_complete THEN raw_spend_sum END AS spend_sum,
    CASE WHEN cpm_coverage_complete
         THEN round(
             raw_spend_sum / NULLIF(raw_cpm_impression_sum, 0) * 1000,
             6
         ) END AS cpm_pooled,
    CASE WHEN play_3s_coverage_complete THEN raw_play_3s_sum END
        AS play_3s_sum,
    CASE WHEN play_3s_coverage_complete
         THEN round(
             raw_play_3s_sum / NULLIF(raw_play_3s_impression_sum, 0),
             6
         ) END AS play_3s_rate_pooled,
    CASE WHEN completion_coverage_complete
         THEN raw_completion_numerator_sum END AS completion_numerator_sum,
    CASE WHEN completion_coverage_complete
         THEN raw_completion_denominator_sum END AS completion_denominator_sum,
    CASE WHEN completion_coverage_complete
         THEN raw_completion_denominator_type END AS completion_denominator_type,
    CASE WHEN completion_coverage_complete
         THEN round(
             raw_completion_numerator_sum
             / NULLIF(raw_completion_denominator_sum, 0),
             6
         ) END AS completion_rate_pooled,
    a3_coverage_complete AS metric_coverage_complete,
    cpm_coverage_complete,
    play_3s_coverage_complete,
    completion_coverage_complete,
    CASE WHEN impression_count = eligible_asset_count
          AND eligible_asset_count > 0
         THEN raw_impression_sum END AS impressions_sum
FROM evaluated;

COMMENT ON VIEW pipeline.v_experiment_arm_pooled_metrics IS
    'Arm-level formal metric pool. Completion coverage additionally requires every asset numerator to be no greater than its positive denominator.';

CREATE OR REPLACE VIEW pipeline.v_experiment_round_results AS
WITH legacy_assets AS (
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
             AND (a.ad_metrics ->> e.north_star_metric)
                 ~ '^-?[0-9]+(\.[0-9]+)?%?$'
            THEN rtrim(
                a.ad_metrics ->> e.north_star_metric,
                '%'
            )::numeric
        END AS ns_value,
        CASE
            WHEN (a.ad_metrics ->> 'impressions') ~ '^[0-9]+(\.[0-9]+)?$'
            THEN (a.ad_metrics ->> 'impressions')::numeric
        END AS impression_value
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
              a.ad_metrics #>>
                  ARRAY[
                      '_validation',
                      'metric_poolability',
                      e.north_star_metric
                  ] = 'true'
          WHEN a.ad_metrics #> '{_validation,suspect}' IS NULL THEN TRUE
          WHEN a.ad_metrics #> '{_validation,suspect}' = 'false'::jsonb
              THEN TRUE
          WHEN jsonb_typeof(
                   a.ad_metrics #> '{_validation,suspect}'
               ) = 'object'
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
legacy_rollup AS (
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
        count(asset_id) AS eligible_asset_count,
        count(ns_value) AS n_videos,
        avg(ns_value) AS legacy_north_star_avg,
        sum(ns_value) AS legacy_north_star_sum,
        sum(impression_value) AS legacy_impressions_sum
    FROM legacy_assets
    GROUP BY
        experiment_id, sku_id, intent, round_no, arm_id, arm_label,
        swept_variable, variable_value, hypothesis, script_id,
        north_star_metric, north_star_direction,
        is_winner, is_baseline_locked, forced,
        production_mode, predicted_match_score
)
SELECT
    r.experiment_id,
    r.sku_id,
    r.intent,
    r.round_no,
    r.arm_id,
    r.arm_label,
    r.swept_variable,
    r.variable_value,
    r.hypothesis,
    r.script_id,
    r.north_star_metric,
    r.north_star_direction,
    r.is_winner,
    r.is_baseline_locked,
    r.forced,
    CASE
        WHEN r.intent = 'soft_ad'
         AND r.north_star_metric = 'completion_rate'
        THEN r.eligible_asset_count
        ELSE r.n_videos
    END AS n_videos,
    CASE
        WHEN r.intent = 'planting' THEN p.a3_ratio_pooled
        WHEN r.intent = 'soft_ad'
         AND r.north_star_metric = 'completion_rate'
        THEN p.completion_rate_pooled
        ELSE round(r.legacy_north_star_avg, 4)
    END AS north_star_avg,
    CASE
        WHEN r.intent = 'soft_ad'
         AND r.north_star_metric = 'completion_rate'
        THEN p.completion_numerator_sum
        ELSE round(r.legacy_north_star_sum, 4)
    END AS north_star_sum,
    CASE
        WHEN (
                CASE
                    WHEN r.intent = 'soft_ad'
                     AND r.north_star_metric = 'completion_rate'
                    THEN r.eligible_asset_count
                    ELSE r.n_videos
                END
             ) < 5
        THEN 'preliminary'
        ELSE 'sufficient'
    END AS sample_status,
    r.production_mode,
    r.legacy_impressions_sum AS impressions_sum,
    r.predicted_match_score,
    p.a3_numerator_sum,
    p.a3_denominator_sum,
    p.a3_ratio_pooled,
    p.spend_sum,
    p.cpm_pooled,
    p.play_3s_sum,
    p.play_3s_rate_pooled,
    p.completion_numerator_sum,
    p.completion_denominator_sum,
    p.completion_denominator_type,
    p.completion_rate_pooled,
    CASE
        WHEN r.intent = 'soft_ad'
         AND r.north_star_metric = 'completion_rate'
        THEN p.completion_coverage_complete
        ELSE p.metric_coverage_complete
    END AS metric_coverage_complete
FROM legacy_rollup r
JOIN pipeline.v_experiment_arm_pooled_metrics p
  ON p.arm_id = r.arm_id
ORDER BY r.experiment_id, r.round_no, r.arm_label;

COMMENT ON VIEW pipeline.v_experiment_round_results IS
    'Stable 34-column experiment results. Planting A3 and soft-ad completion north stars pool feasible per-asset raw count pairs; other intents retain legacy aggregation.';
