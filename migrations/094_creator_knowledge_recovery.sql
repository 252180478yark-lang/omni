-- Durable recovery anchors for post-approval creator knowledge extraction.
--
-- A creator video task can outlive its in-process finalizer. Persisting the
-- knowledge reconstruction and deterministic ingestion task UUID lets a
-- restarted worker resume polling the same ingestion work instead of creating
-- a second embedding/KB submission. The ingestion UUID intentionally has no
-- foreign key: it is reserved before the corresponding knowledge.tasks row is
-- inserted, closing the submit-then-crash window.

ALTER TABLE content_studio.creator_video_tasks
    ADD COLUMN IF NOT EXISTS knowledge_reconstruction_id UUID,
    ADD COLUMN IF NOT EXISTS knowledge_ingestion_task_id UUID,
    ADD COLUMN IF NOT EXISTS knowledge_ingestion_state TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid='content_studio.creator_video_tasks'::regclass
          AND conname='creator_video_tasks_knowledge_reconstruction_fkey'
    ) THEN
        ALTER TABLE content_studio.creator_video_tasks
            ADD CONSTRAINT creator_video_tasks_knowledge_reconstruction_fkey
            FOREIGN KEY (knowledge_reconstruction_id)
            REFERENCES content_studio.material_reconstructions(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid='content_studio.creator_video_tasks'::regclass
          AND conname='creator_video_tasks_knowledge_ingestion_state_check'
    ) THEN
        ALTER TABLE content_studio.creator_video_tasks
            ADD CONSTRAINT creator_video_tasks_knowledge_ingestion_state_check
            CHECK (
                knowledge_ingestion_state IS NULL
                OR knowledge_ingestion_state IN (
                    'reserved', 'submitted', 'running', 'succeeded', 'failed'
                )
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_video_tasks_knowledge_ingestion_task
    ON content_studio.creator_video_tasks (knowledge_ingestion_task_id)
    WHERE knowledge_ingestion_task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_creator_video_tasks_knowledge_recovery
    ON content_studio.creator_video_tasks (knowledge_ingestion_state, updated_at ASC)
    WHERE knowledge_ingestion_task_id IS NOT NULL;

-- Rollback is operational: stop admitting knowledge_from_archive work before
-- dropping these additive recovery pointers. Existing evidence and ingestion
-- tasks remain valid and must not be deleted as part of a code rollback.
