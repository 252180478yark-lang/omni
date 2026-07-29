-- Durable ordering for the currently refreshed public homepage prefix.
--
-- ``source_rank`` is nullable on purpose: rows from historical/incremental
-- discovery remain auditable, while only a successfully refreshed homepage
-- snapshot owns ranks 0..29.  Writers clear a prior rank only after the new
-- prefix has completed, so a failed browser collection cannot replace the
-- selection shown to the owner.

ALTER TABLE content_studio.seed_materials
    ADD COLUMN IF NOT EXISTS source_rank INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid='content_studio.seed_materials'::regclass
          AND conname='seed_materials_source_rank_nonnegative_check'
    ) THEN
        ALTER TABLE content_studio.seed_materials
            ADD CONSTRAINT seed_materials_source_rank_nonnegative_check
            CHECK (source_rank IS NULL OR source_rank >= 0);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_seed_materials_creator_source_rank
    ON content_studio.seed_materials (source_id, source_rank ASC NULLS LAST, created_at DESC)
    WHERE source_id IS NOT NULL;

-- Rollback is operational: stop using fresh-homepage selection first.  The
-- nullable rank is additive and historical material rows must be retained for
-- audit, not deleted as part of a schema rollback.
