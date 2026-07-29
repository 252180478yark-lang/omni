-- Migration 070: make formal video generation sets immutable, lineage-safe,
-- and impossible to bypass by clearing an asset's generation_set_id.

CREATE OR REPLACE FUNCTION pipeline.guard_video_generation_set()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    manifest_len integer;
    valid_len integer;
    distinct_scenes integer;
    reference_len integer;
    valid_reference_len integer;
    distinct_reference_ids integer;
BEGIN
    IF TG_OP = 'INSERT' AND (
        NEW.status <> 'draft'
        OR NEW.selected_assets <> '[]'::jsonb
        OR NEW.post_video_group_gate <> '{}'::jsonb
    ) THEN
        RAISE EXCEPTION 'video_generation_set_must_start_draft'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE'
       AND (
           NEW.selected_assets IS DISTINCT FROM OLD.selected_assets
           OR NEW.post_video_group_gate IS DISTINCT FROM OLD.post_video_group_gate
           OR NEW.status IS DISTINCT FROM OLD.status
       )
       AND COALESCE(
           current_setting('omni.video_generation_set_transition', true),
           ''
       ) <> 'service' THEN
        RAISE EXCEPTION 'video_generation_set_transition_requires_service'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' AND (
        NEW.sku_id IS DISTINCT FROM OLD.sku_id
        OR NEW.script_id IS DISTINCT FROM OLD.script_id
        OR NEW.experiment_id IS DISTINCT FROM OLD.experiment_id
        OR NEW.experiment_arm_id IS DISTINCT FROM OLD.experiment_arm_id
        OR NEW.expected_segment_manifest IS DISTINCT FROM OLD.expected_segment_manifest
        OR NEW.reference_manifest IS DISTINCT FROM OLD.reference_manifest
        OR NEW.pre_video_group_gate IS DISTINCT FROM OLD.pre_video_group_gate
        OR NEW.profile_version IS DISTINCT FROM OLD.profile_version
    ) THEN
        RAISE EXCEPTION 'video_generation_set_identity_immutable'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(NEW.expected_segment_manifest) <> 'array'
       OR jsonb_array_length(NEW.expected_segment_manifest) = 0 THEN
        RAISE EXCEPTION 'generation_set_expected_manifest_empty'
            USING ERRCODE = '23514';
    END IF;

    SELECT
        count(*),
        count(*) FILTER (
            WHERE jsonb_typeof(item) = 'object'
              AND COALESCE(item ->> 'scene_no', '') ~ '^[1-9][0-9]*$'
              AND NULLIF(btrim(item ->> 'final_prompt_hash'), '') IS NOT NULL
              AND COALESCE(item ->> 'duration_seconds', '') ~ '^[0-9]+([.][0-9]+)?$'
              AND (item ->> 'duration_seconds')::numeric > 0
        ),
        count(DISTINCT (item ->> 'scene_no')::integer) FILTER (
            WHERE COALESCE(item ->> 'scene_no', '') ~ '^[1-9][0-9]*$'
        )
    INTO manifest_len, valid_len, distinct_scenes
    FROM jsonb_array_elements(NEW.expected_segment_manifest) AS item;

    IF valid_len <> manifest_len OR distinct_scenes <> manifest_len THEN
        RAISE EXCEPTION 'generation_set_expected_manifest_invalid_or_duplicate'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(NEW.reference_manifest) <> 'object'
       OR jsonb_typeof(NEW.reference_manifest -> 'items') <> 'array'
       OR jsonb_array_length(NEW.reference_manifest -> 'items') = 0 THEN
        RAISE EXCEPTION 'generation_set_reference_manifest_empty'
            USING ERRCODE = '23514';
    END IF;

    SELECT
        count(*),
        count(*) FILTER (
            WHERE jsonb_typeof(item) = 'object'
              AND NULLIF(btrim(item ->> 'id'), '') IS NOT NULL
              AND NULLIF(btrim(item ->> 'sha256'), '') IS NOT NULL
        ),
        count(DISTINCT item ->> 'id') FILTER (
            WHERE jsonb_typeof(item) = 'object'
              AND NULLIF(btrim(item ->> 'id'), '') IS NOT NULL
        )
    INTO reference_len, valid_reference_len, distinct_reference_ids
    FROM jsonb_array_elements(NEW.reference_manifest -> 'items') AS item;

    IF valid_reference_len <> reference_len
       OR distinct_reference_ids <> reference_len THEN
        RAISE EXCEPTION 'generation_set_reference_manifest_invalid_or_duplicate'
            USING ERRCODE = '23514';
    END IF;

    IF NOT (NEW.pre_video_group_gate @> '{"pass": true}'::jsonb) THEN
        RAISE EXCEPTION 'generation_set_pre_video_gate_not_passed'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(NEW.pre_video_group_gate -> 'fingerprint') <> 'object'
       OR jsonb_typeof(
           NEW.pre_video_group_gate #> '{fingerprint,final_prompt_hashes}'
       ) <> 'array'
       OR NEW.pre_video_group_gate #>> '{fingerprint,upstream_fact_hash}' IS NULL
       OR NULLIF(btrim(
           NEW.pre_video_group_gate #>> '{fingerprint,upstream_fact_hash}'
       ), '') IS NULL
       OR NEW.pre_video_group_gate #>> '{fingerprint,intent_profile_version}'
          IS DISTINCT FROM NEW.profile_version
       OR NULLIF(btrim(
           NEW.pre_video_group_gate #>> '{fingerprint,embedding_model}'
       ), '') IS NULL
       OR NULLIF(btrim(
           NEW.pre_video_group_gate #>> '{fingerprint,embedding_version}'
       ), '') IS NULL
       OR NULLIF(btrim(
           NEW.pre_video_group_gate #>> '{fingerprint,fingerprint_hash}'
       ), '') IS NULL
       OR NEW.pre_video_group_gate #> '{fingerprint,final_prompt_hashes}'
          IS DISTINCT FROM (
              SELECT jsonb_agg(to_jsonb(item ->> 'final_prompt_hash') ORDER BY ordinality)
              FROM jsonb_array_elements(NEW.expected_segment_manifest)
                   WITH ORDINALITY AS expected(item, ordinality)
          ) THEN
        RAISE EXCEPTION 'generation_set_pre_video_fingerprint_invalid_or_stale'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pipeline.scripts script
        JOIN pipeline.experiments experiment
          ON experiment.id = NEW.experiment_id
        JOIN pipeline.experiment_arms arm
          ON arm.id = NEW.experiment_arm_id
        WHERE script.id = NEW.script_id
          AND script.sku_id = NEW.sku_id
          AND experiment.sku_id = NEW.sku_id
          AND arm.sku_id = NEW.sku_id
          AND arm.experiment_id = NEW.experiment_id
          AND arm.script_id = NEW.script_id
    ) THEN
        RAISE EXCEPTION 'generation_set_lineage_mismatch'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_video_generation_set
    ON pipeline.video_generation_sets;
CREATE TRIGGER trg_guard_video_generation_set
BEFORE INSERT OR UPDATE ON pipeline.video_generation_sets
FOR EACH ROW EXECUTE FUNCTION pipeline.guard_video_generation_set();

CREATE UNIQUE INDEX IF NOT EXISTS uq_video_generation_sets_active_arm
    ON pipeline.video_generation_sets (experiment_arm_id)
    WHERE status IN ('draft', 'ready', 'adopted');

CREATE OR REPLACE FUNCTION pipeline.guard_generation_set_arm_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(OLD.id::text, 0));
    IF (
        NEW.round_id IS DISTINCT FROM OLD.round_id
        OR NEW.experiment_id IS DISTINCT FROM OLD.experiment_id
        OR NEW.sku_id IS DISTINCT FROM OLD.sku_id
        OR NEW.round_no IS DISTINCT FROM OLD.round_no
        OR NEW.swept_variable IS DISTINCT FROM OLD.swept_variable
        OR NEW.variable_value IS DISTINCT FROM OLD.variable_value
        OR NEW.arm_label IS DISTINCT FROM OLD.arm_label
        OR NEW.script_id IS DISTINCT FROM OLD.script_id
        OR NEW.production_mode IS DISTINCT FROM OLD.production_mode
    ) AND EXISTS (
        SELECT 1
        FROM pipeline.video_generation_sets generation_set
        WHERE generation_set.experiment_arm_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'generation_set_arm_identity_immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_generation_set_arm_identity
    ON pipeline.experiment_arms;
CREATE TRIGGER trg_guard_generation_set_arm_identity
BEFORE UPDATE OF round_id, experiment_id, sku_id, round_no, swept_variable,
    variable_value, arm_label, script_id, production_mode
ON pipeline.experiment_arms
FOR EACH ROW EXECUTE FUNCTION pipeline.guard_generation_set_arm_identity();

CREATE OR REPLACE FUNCTION pipeline.guard_video_generation_asset()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    contract_version text;
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.generation_set_id IS DISTINCT FROM OLD.generation_set_id THEN
        RAISE EXCEPTION 'generation_set_asset_link_immutable'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.generation_set_id IS NOT NULL
       AND (
           NEW.script_id IS DISTINCT FROM OLD.script_id
           OR NEW.experiment_id IS DISTINCT FROM OLD.experiment_id
           OR NEW.experiment_arm_id IS DISTINCT FROM OLD.experiment_arm_id
           OR NEW.sku_id IS DISTINCT FROM OLD.sku_id
           OR NEW.asset_type IS DISTINCT FROM OLD.asset_type
           OR NEW.scene_no IS DISTINCT FROM OLD.scene_no
       ) THEN
        RAISE EXCEPTION 'generation_set_asset_lineage_immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.script_id IS NOT NULL THEN
        SELECT content_contract ->> 'version'
        INTO contract_version
        FROM pipeline.scripts
        WHERE id = NEW.script_id;
    END IF;

    IF NEW.asset_type = 'video'
       AND contract_version = '2026-07-15.v1'
       AND NEW.generation_set_id IS NULL THEN
        RAISE EXCEPTION 'formal_video_requires_generation_set'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.generation_set_id IS NOT NULL THEN
        IF NEW.asset_type <> 'video' OR NEW.scene_no IS NULL THEN
            RAISE EXCEPTION 'generation_set_asset_type_or_scene_invalid'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM pipeline.video_generation_sets generation_set
            WHERE generation_set.id = NEW.generation_set_id
              AND generation_set.sku_id = NEW.sku_id
              AND generation_set.script_id = NEW.script_id
              AND generation_set.experiment_id = NEW.experiment_id
              AND generation_set.experiment_arm_id = NEW.experiment_arm_id
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(
                      generation_set.expected_segment_manifest
                  ) AS expected
                  WHERE (expected ->> 'scene_no')::integer = NEW.scene_no
              )
        ) THEN
            RAISE EXCEPTION 'generation_set_asset_lineage_mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_video_generation_asset
    ON pipeline.assets;
CREATE TRIGGER trg_guard_video_generation_asset
BEFORE INSERT OR UPDATE OF generation_set_id, script_id, experiment_id,
    experiment_arm_id, sku_id, asset_type, scene_no
ON pipeline.assets
FOR EACH ROW EXECUTE FUNCTION pipeline.guard_video_generation_asset();

CREATE OR REPLACE FUNCTION pipeline.guard_formal_script_video_assets()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.content_contract ->> 'version' = '2026-07-15.v1'
       AND OLD.content_contract ->> 'version' IS DISTINCT FROM '2026-07-15.v1'
       AND EXISTS (
           SELECT 1
           FROM pipeline.assets asset
           WHERE asset.script_id = NEW.id
             AND asset.asset_type = 'video'
             AND asset.generation_set_id IS NULL
       ) THEN
        RAISE EXCEPTION 'formal_script_has_legacy_video_assets'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_formal_script_video_assets
    ON pipeline.scripts;
CREATE TRIGGER trg_guard_formal_script_video_assets
BEFORE UPDATE OF content_contract ON pipeline.scripts
FOR EACH ROW EXECUTE FUNCTION pipeline.guard_formal_script_video_assets();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pipeline.assets asset
        JOIN pipeline.scripts script ON script.id = asset.script_id
        WHERE asset.asset_type = 'video'
          AND asset.generation_set_id IS NULL
          AND script.content_contract ->> 'version' = '2026-07-15.v1'
    ) THEN
        RAISE EXCEPTION 'existing_formal_video_without_generation_set'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

COMMENT ON FUNCTION pipeline.guard_video_generation_set() IS
    'Freeze generation-set identity/manifests and validate exact script/experiment/arm lineage.';
COMMENT ON FUNCTION pipeline.guard_generation_set_arm_identity() IS
    'Freeze experiment-arm semantic identity after a formal generation set exists.';
COMMENT ON FUNCTION pipeline.guard_video_generation_asset() IS
    'Prevent formal video set bypass, unlink/rebind, and cross-lineage asset attachment.';
COMMENT ON FUNCTION pipeline.guard_formal_script_video_assets() IS
    'Prevent a legacy null-set video from becoming formal through a later script-contract update.';
