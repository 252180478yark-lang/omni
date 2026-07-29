-- Durable remote-video-analysis idempotency for creator learning.
--
-- A creator child task may lose its HTTP response after the analyzer has
-- accepted an upload. Persist a stable submission-attempt counter locally and
-- let video_analysis return the pre-existing remote job for the matching
-- Idempotency-Key. The counter advances only after a confirmed terminal
-- remote failure, not after an expired worker lease.

ALTER TABLE content_studio.creator_video_tasks
    ADD COLUMN IF NOT EXISTS analysis_submission_attempt INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid='content_studio.creator_video_tasks'::regclass
          AND conname='creator_video_tasks_analysis_submission_attempt_check'
    ) THEN
        ALTER TABLE content_studio.creator_video_tasks
            ADD CONSTRAINT creator_video_tasks_analysis_submission_attempt_check
            CHECK (analysis_submission_attempt >= 0);
    END IF;

    IF to_regclass('video_analysis.videos') IS NOT NULL THEN
        ALTER TABLE video_analysis.videos
            ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
        EXECUTE '
            CREATE UNIQUE INDEX IF NOT EXISTS uq_video_analysis_videos_idempotency_key
            ON video_analysis.videos (idempotency_key)
            WHERE idempotency_key IS NOT NULL
        ';
    END IF;
END $$;

-- Rollback is operational: stop accepting new creator analysis submissions
-- before removing these additive fields. Existing remote analysis evidence
-- and idempotency mappings must remain available for audit and recovery.
