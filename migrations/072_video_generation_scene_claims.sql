-- Migration 072: cross-process generation and judge leases for one paid call
-- per generation-set scene.  Task 10 owns migration 071.

CREATE TABLE IF NOT EXISTS pipeline.video_generation_claims (
    generation_set_id UUID NOT NULL
        REFERENCES pipeline.video_generation_sets(id) ON DELETE CASCADE,
    scene_no INTEGER NOT NULL,
    claim_token UUID NOT NULL,
    generation_attempt_token UUID NOT NULL,
    status TEXT NOT NULL DEFAULT 'generating',
    lease_expires_at TIMESTAMPTZ NOT NULL,
    attempt_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    asset_id UUID NULL REFERENCES pipeline.assets(id) ON DELETE RESTRICT,
    attempt_no INTEGER NOT NULL DEFAULT 1,
    judge_attempt_no INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (generation_set_id, scene_no),
    CONSTRAINT video_generation_claims_scene_no_check
        CHECK (scene_no > 0),
    CONSTRAINT video_generation_claims_status_check
        CHECK (status IN (
            'generating', 'judge_pending', 'judging', 'judge_unavailable',
            'completed', 'provider_failed', 'content_failed'
        )),
    CONSTRAINT video_generation_claims_attempt_no_check
        CHECK (attempt_no > 0),
    CONSTRAINT video_generation_claims_judge_attempt_no_check
        CHECK (judge_attempt_no >= 0)
);

ALTER TABLE pipeline.video_generation_claims
    ADD COLUMN IF NOT EXISTS generation_attempt_token UUID,
    ADD COLUMN IF NOT EXISTS attempt_started_at TIMESTAMPTZ;

UPDATE pipeline.video_generation_claims
SET generation_attempt_token = COALESCE(generation_attempt_token, claim_token),
    attempt_started_at = COALESCE(attempt_started_at, created_at)
WHERE generation_attempt_token IS NULL OR attempt_started_at IS NULL;

ALTER TABLE pipeline.video_generation_claims
    ALTER COLUMN generation_attempt_token SET NOT NULL,
    ALTER COLUMN attempt_started_at SET NOT NULL;

ALTER TABLE pipeline.video_generation_claims
    DROP CONSTRAINT IF EXISTS video_generation_claims_asset_id_fkey;
ALTER TABLE pipeline.video_generation_claims
    ADD CONSTRAINT video_generation_claims_asset_id_fkey
    FOREIGN KEY (asset_id) REFERENCES pipeline.assets(id) ON DELETE RESTRICT;

ALTER TABLE pipeline.assets
    ADD COLUMN IF NOT EXISTS generation_attempt_token UUID,
    ADD COLUMN IF NOT EXISTS generation_attempt_no INTEGER;

UPDATE pipeline.assets asset
SET generation_attempt_token = claim.generation_attempt_token,
    generation_attempt_no = claim.attempt_no
FROM pipeline.video_generation_claims claim
WHERE claim.asset_id = asset.id
  AND asset.generation_attempt_token IS NULL;

-- ``--rerun`` must converge an already-upgraded database to the current
-- expression.  NOT VALID preserves historical rows while PostgreSQL still
-- enforces the constraint for all new/updated rows.
ALTER TABLE pipeline.video_generation_claims
    DROP CONSTRAINT IF EXISTS video_generation_claims_status_asset_check;
ALTER TABLE pipeline.video_generation_claims
    ADD CONSTRAINT video_generation_claims_status_asset_check
    CHECK (
        (status IN ('generating', 'provider_failed') AND asset_id IS NULL)
        OR
        (status IN (
            'judge_pending', 'judging', 'judge_unavailable',
            'completed', 'content_failed'
        ) AND asset_id IS NOT NULL)
    ) NOT VALID;

ALTER TABLE pipeline.assets
    DROP CONSTRAINT IF EXISTS assets_generation_attempt_identity_check;
ALTER TABLE pipeline.assets
    ADD CONSTRAINT assets_generation_attempt_identity_check
    CHECK (
        generation_set_id IS NULL
        OR asset_type <> 'video'
        -- Historical formal assets predate attempt fencing.  They remain
        -- updateable for ad-metric/status writes; the trigger below rejects
        -- every new or lineage-rebound formal asset without an active claim.
        OR (
            generation_attempt_token IS NULL
            AND generation_attempt_no IS NULL
        )
        OR (
            generation_attempt_token IS NOT NULL
            AND generation_attempt_no IS NOT NULL
            AND generation_attempt_no > 0
        )
    ) NOT VALID;

CREATE UNIQUE INDEX IF NOT EXISTS idx_video_generation_claims_token
    ON pipeline.video_generation_claims (claim_token);
CREATE UNIQUE INDEX IF NOT EXISTS idx_video_generation_attempt_token
    ON pipeline.video_generation_claims (generation_attempt_token);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_generation_attempt_scene
    ON pipeline.assets(
        generation_set_id, scene_no, generation_attempt_token
    )
    WHERE generation_set_id IS NOT NULL
      AND asset_type = 'video'
      AND generation_attempt_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_video_generation_claims_expiry
    ON pipeline.video_generation_claims (lease_expires_at)
    WHERE status IN ('generating', 'judging');

CREATE TABLE IF NOT EXISTS pipeline.video_generation_judge_events (
    id BIGSERIAL PRIMARY KEY,
    generation_set_id UUID NOT NULL
        REFERENCES pipeline.video_generation_sets(id) ON DELETE CASCADE,
    scene_no INTEGER NOT NULL,
    asset_id UUID NULL REFERENCES pipeline.assets(id) ON DELETE RESTRICT,
    claim_token UUID NOT NULL,
    judge_attempt_no INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    previous_gate_error TEXT NULL,
    new_gate_error TEXT NULL,
    fingerprint_hash TEXT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT video_generation_judge_events_scene_check CHECK (scene_no > 0),
    CONSTRAINT video_generation_judge_events_attempt_check
        CHECK (judge_attempt_no > 0),
    CONSTRAINT video_generation_judge_events_detail_check
        CHECK (jsonb_typeof(detail) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_video_generation_judge_events_scene
    ON pipeline.video_generation_judge_events(
        generation_set_id, scene_no, created_at DESC
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_video_generation_judge_events_claim
    ON pipeline.video_generation_judge_events(claim_token);

CREATE OR REPLACE FUNCTION pipeline.validate_video_generation_claim_asset()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    linked RECORD;
BEGIN
    IF NEW.asset_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT generation_set_id, scene_no, asset_type,
           generation_attempt_token, generation_attempt_no
    INTO linked
    FROM pipeline.assets
    WHERE id = NEW.asset_id;
    IF NOT FOUND
       OR linked.generation_set_id IS DISTINCT FROM NEW.generation_set_id
       OR linked.scene_no IS DISTINCT FROM NEW.scene_no
       OR linked.asset_type IS DISTINCT FROM 'video'
       OR linked.generation_attempt_token IS DISTINCT FROM NEW.generation_attempt_token
       OR linked.generation_attempt_no IS DISTINCT FROM NEW.attempt_no THEN
        RAISE EXCEPTION 'video_generation_claim_asset_mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_video_generation_claim_asset
    ON pipeline.video_generation_claims;
CREATE TRIGGER trg_validate_video_generation_claim_asset
    BEFORE INSERT OR UPDATE OF asset_id, generation_set_id, scene_no,
        generation_attempt_token, attempt_no
    ON pipeline.video_generation_claims
    FOR EACH ROW EXECUTE FUNCTION pipeline.validate_video_generation_claim_asset();

CREATE OR REPLACE FUNCTION pipeline.validate_video_asset_generation_attempt()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    active_claim RECORD;
    expected_duration DOUBLE PRECISION;
    duration_tolerance DOUBLE PRECISION;
BEGIN
    IF NEW.generation_set_id IS NULL OR NEW.asset_type <> 'video' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT'
       AND COALESCE(NEW.visual_prescreen, '{}'::jsonb)
           ? 'post_video_vector_gate' THEN
        RAISE EXCEPTION 'formal_video_post_gate_requires_live_judge_claim'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE'
       AND NEW.duration_seconds IS DISTINCT FROM OLD.duration_seconds THEN
        RAISE EXCEPTION 'formal_video_duration_immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT generation_attempt_token, attempt_no, status, lease_expires_at
    INTO active_claim
    FROM pipeline.video_generation_claims
    WHERE generation_set_id = NEW.generation_set_id
      AND scene_no = NEW.scene_no;
    IF NOT FOUND
       OR active_claim.status IS DISTINCT FROM 'generating'
       OR active_claim.lease_expires_at <= CURRENT_TIMESTAMP
       OR active_claim.generation_attempt_token
            IS DISTINCT FROM NEW.generation_attempt_token
       OR active_claim.attempt_no IS DISTINCT FROM NEW.generation_attempt_no THEN
        RAISE EXCEPTION 'video_asset_generation_attempt_mismatch'
            USING ERRCODE = '23514';
    END IF;
    SELECT (item->>'duration_seconds')::DOUBLE PRECISION,
           COALESCE(
               (item->>'duration_tolerance_seconds')::DOUBLE PRECISION,
               GREATEST(
                   0.75,
                   (item->>'duration_seconds')::DOUBLE PRECISION * 0.1
               )
           )
    INTO expected_duration, duration_tolerance
    FROM pipeline.video_generation_sets generation_set,
         LATERAL jsonb_array_elements(
             generation_set.expected_segment_manifest
         ) AS item
    WHERE generation_set.id = NEW.generation_set_id
      AND (item->>'scene_no')::INTEGER = NEW.scene_no;
    IF expected_duration IS NULL
       OR NEW.duration_seconds IS NULL
       OR ABS(NEW.duration_seconds - expected_duration) > duration_tolerance THEN
        RAISE EXCEPTION 'video_asset_duration_mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_video_asset_generation_attempt
    ON pipeline.assets;
CREATE TRIGGER trg_validate_video_asset_generation_attempt
    BEFORE INSERT OR UPDATE OF generation_set_id, scene_no, asset_type,
        generation_attempt_token, generation_attempt_no, duration_seconds
    ON pipeline.assets
    FOR EACH ROW EXECUTE FUNCTION pipeline.validate_video_asset_generation_attempt();

CREATE OR REPLACE FUNCTION pipeline.guard_formal_video_post_gate_write()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    judge_claim_token TEXT;
    judge_claim_owned BOOLEAN := FALSE;
BEGIN
    IF OLD.generation_set_id IS NULL OR OLD.asset_type <> 'video' THEN
        RETURN NEW;
    END IF;

    IF NEW.file_url IS DISTINCT FROM OLD.file_url
       OR NEW.prompt IS DISTINCT FROM OLD.prompt
       OR NEW.duration_seconds IS DISTINCT FROM OLD.duration_seconds THEN
        RAISE EXCEPTION 'formal_video_asset_identity_immutable'
            USING ERRCODE = '23514';
    END IF;

    -- The admission snapshot is immutable.  The judge may append/replace only
    -- its own post_video_vector_gate member under a live claim-token fence.
    IF (
        COALESCE(NEW.visual_prescreen, '{}'::jsonb)
            - 'post_video_vector_gate'
       ) IS DISTINCT FROM (
        COALESCE(OLD.visual_prescreen, '{}'::jsonb)
            - 'post_video_vector_gate'
       ) THEN
        RAISE EXCEPTION 'formal_video_ingest_identity_immutable'
            USING ERRCODE = '23514';
    END IF;

    IF COALESCE(OLD.visual_prescreen, '{}'::jsonb)->'post_video_vector_gate'
       IS DISTINCT FROM
       COALESCE(NEW.visual_prescreen, '{}'::jsonb)->'post_video_vector_gate' THEN
        judge_claim_token := COALESCE(
            current_setting('omni.video_judge_claim_token', true), ''
        );
        SELECT EXISTS (
            SELECT 1
            FROM pipeline.video_generation_claims claim
            WHERE claim.generation_set_id = NEW.generation_set_id
              AND claim.scene_no = NEW.scene_no
              AND claim.asset_id = NEW.id
              AND claim.status = 'judging'
              AND claim.claim_token::text = judge_claim_token
              AND claim.lease_expires_at > CURRENT_TIMESTAMP
        ) INTO judge_claim_owned;
        IF NOT judge_claim_owned THEN
            RAISE EXCEPTION 'formal_video_post_gate_requires_live_judge_claim'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_formal_video_post_gate_write
    ON pipeline.assets;
CREATE TRIGGER trg_guard_formal_video_post_gate_write
    BEFORE UPDATE OF file_url, prompt, duration_seconds, visual_prescreen
    ON pipeline.assets
    FOR EACH ROW EXECUTE FUNCTION pipeline.guard_formal_video_post_gate_write();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio'
          AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_video_generation_claims_touch
            ON pipeline.video_generation_claims;
        CREATE TRIGGER trg_video_generation_claims_touch
            BEFORE UPDATE ON pipeline.video_generation_claims
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;
