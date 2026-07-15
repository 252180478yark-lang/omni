-- Migration 068: AI planting content contracts, governed generation sets,
-- and raw-count experiment rollups. Additive and safe to rerun.

ALTER TABLE pipeline.scripts
    ADD COLUMN IF NOT EXISTS content_contract JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE pipeline.experiments
    ADD COLUMN IF NOT EXISTS evaluation_policy JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.scripts'::regclass
          AND conname = 'scripts_content_contract_object_check'
    ) THEN
        ALTER TABLE pipeline.scripts
            ADD CONSTRAINT scripts_content_contract_object_check
            CHECK (jsonb_typeof(content_contract) = 'object');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.experiments'::regclass
          AND conname = 'experiments_evaluation_policy_object_check'
    ) THEN
        ALTER TABLE pipeline.experiments
            ADD CONSTRAINT experiments_evaluation_policy_object_check
            CHECK (jsonb_typeof(evaluation_policy) = 'object');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS pipeline.video_generation_sets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id VARCHAR(64) NOT NULL,
    script_id UUID NOT NULL REFERENCES pipeline.scripts(id) ON DELETE CASCADE,
    experiment_id UUID NOT NULL REFERENCES pipeline.experiments(id) ON DELETE CASCADE,
    experiment_arm_id UUID NOT NULL REFERENCES pipeline.experiment_arms(id) ON DELETE CASCADE,
    expected_segment_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_assets JSONB NOT NULL DEFAULT '[]'::jsonb,
    reference_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    pre_video_group_gate JSONB NOT NULL DEFAULT '{}'::jsonb,
    post_video_group_gate JSONB NOT NULL DEFAULT '{}'::jsonb,
    profile_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT video_generation_sets_expected_segment_manifest_check
        CHECK (jsonb_typeof(expected_segment_manifest) = 'array'),
    CONSTRAINT video_generation_sets_selected_assets_check
        CHECK (jsonb_typeof(selected_assets) = 'array'),
    CONSTRAINT video_generation_sets_reference_manifest_check
        CHECK (jsonb_typeof(reference_manifest) = 'object'),
    CONSTRAINT video_generation_sets_pre_video_group_gate_check
        CHECK (jsonb_typeof(pre_video_group_gate) = 'object'),
    CONSTRAINT video_generation_sets_post_video_group_gate_check
        CHECK (jsonb_typeof(post_video_group_gate) = 'object'),
    CONSTRAINT video_generation_sets_profile_version_check
        CHECK (btrim(profile_version) <> ''),
    CONSTRAINT video_generation_sets_status_check
        CHECK (status IN ('draft', 'ready', 'adopted', 'discarded'))
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio'
          AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_video_generation_sets_touch
            ON pipeline.video_generation_sets;
        CREATE TRIGGER trg_video_generation_sets_touch
            BEFORE UPDATE ON pipeline.video_generation_sets
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;

ALTER TABLE pipeline.assets
    ADD COLUMN IF NOT EXISTS generation_set_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'pipeline.assets'::regclass
          AND conname = 'assets_generation_set_id_fkey'
    ) THEN
        ALTER TABLE pipeline.assets
            ADD CONSTRAINT assets_generation_set_id_fkey
            FOREIGN KEY (generation_set_id)
            REFERENCES pipeline.video_generation_sets(id)
            ON DELETE RESTRICT;
    END IF;
END $$;

-- Replace only this one constraint. All status, duration, ecommerce, and lineage
-- constraints already present on pipeline.assets remain untouched.
ALTER TABLE pipeline.assets DROP CONSTRAINT IF EXISTS assets_type_check;
ALTER TABLE pipeline.assets ADD CONSTRAINT assets_type_check
    CHECK (asset_type IN (
        'image', 'image_first', 'image_last', 'video', 'character_sheet',
        'product_reference'
    ));

CREATE INDEX IF NOT EXISTS idx_video_generation_sets_arm
    ON pipeline.video_generation_sets (experiment_arm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_generation_set
    ON pipeline.assets (generation_set_id, scene_no)
    WHERE generation_set_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_reference_file
    ON pipeline.assets (file_url)
    WHERE asset_type = 'product_reference'
      AND status <> 'discarded'
      AND file_url IS NOT NULL;

-- Preserve migration 066's first 22 output columns exactly. New columns are
-- appended so dependent migration 065's changelog view remains valid.
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
     AND (
          COALESCE(a.ad_metrics #> '{_validation,suspect}', 'false'::jsonb) = 'false'::jsonb
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
        count(DISTINCT completion_denominator_type_value) AS completion_type_distinct_count,
        min(completion_denominator_type_value) AS raw_completion_denominator_type,
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
                 THEN round(raw_a3_numerator_sum / NULLIF(raw_a3_denominator_sum, 0), 6)
                 ELSE NULL END
        ELSE round(legacy_north_star_avg, 4)
    END AS north_star_avg,
    round(legacy_north_star_sum, 4) AS north_star_sum,
    CASE WHEN n_videos < 5 THEN 'preliminary' ELSE 'sufficient' END AS sample_status,
    production_mode,
    legacy_impressions_sum AS impressions_sum,
    predicted_match_score,
    CASE WHEN a3_coverage_complete THEN raw_a3_numerator_sum ELSE NULL END
        AS a3_numerator_sum,
    CASE WHEN a3_coverage_complete THEN raw_a3_denominator_sum ELSE NULL END
        AS a3_denominator_sum,
    CASE WHEN a3_coverage_complete
         THEN round(raw_a3_numerator_sum / NULLIF(raw_a3_denominator_sum, 0), 6)
         ELSE NULL END AS a3_ratio_pooled,
    CASE WHEN spend_coverage_complete THEN raw_spend_sum ELSE NULL END AS spend_sum,
    CASE WHEN spend_coverage_complete
         THEN round(raw_spend_sum / NULLIF(raw_positive_impression_sum, 0) * 1000, 6)
         ELSE NULL END AS cpm_pooled,
    CASE WHEN play_3s_coverage_complete THEN raw_play_3s_sum ELSE NULL END AS play_3s_sum,
    CASE WHEN play_3s_coverage_complete
         THEN round(raw_play_3s_sum / NULLIF(raw_positive_impression_sum, 0), 6)
         ELSE NULL END AS play_3s_rate_pooled,
    CASE WHEN completion_coverage_complete THEN raw_completion_numerator_sum ELSE NULL END
        AS completion_numerator_sum,
    CASE WHEN completion_coverage_complete THEN raw_completion_denominator_sum ELSE NULL END
        AS completion_denominator_sum,
    CASE WHEN completion_coverage_complete THEN raw_completion_denominator_type ELSE NULL END
        AS completion_denominator_type,
    CASE WHEN completion_coverage_complete
         THEN round(raw_completion_numerator_sum / NULLIF(raw_completion_denominator_sum, 0), 6)
         ELSE NULL END AS completion_rate_pooled,
    a3_coverage_complete AS metric_coverage_complete
FROM evaluated
ORDER BY experiment_id, round_no, arm_label;

COMMENT ON VIEW pipeline.v_experiment_round_results IS
    'Experiment arm metrics: legacy north-star fields plus fail-closed pooled A3, CNY CPM, 3-second play, and completion raw-count diagnostics. Planting north_star_avg uses pooled A3 only when coverage is complete.';
