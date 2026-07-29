-- Creator transcript archive and post-approval knowledge extraction.
--
-- This migration is additive: task rows continue to live in the established
-- creator task/reconstruction tables.  The two new modes intentionally have
-- different cost boundaries:
--   transcript_archive     local ASR + durable PDF only
--   knowledge_from_archive explicit owner-approved transcript -> AI/KB
-- Historical knowledge_only, benchmark_full, and cluster rows remain valid.

ALTER TABLE content_studio.template_analysis_tasks
    DROP CONSTRAINT IF EXISTS template_tasks_creator_mode_check;
ALTER TABLE content_studio.template_analysis_tasks
    ADD CONSTRAINT template_tasks_creator_mode_check
        CHECK (
            mode IS NULL OR mode IN (
                'knowledge_only', 'benchmark_full', 'cluster',
                'transcript_archive', 'knowledge_from_archive'
            )
        );

ALTER TABLE content_studio.creator_video_tasks
    DROP CONSTRAINT IF EXISTS creator_video_tasks_mode_check;
ALTER TABLE content_studio.creator_video_tasks
    ADD CONSTRAINT creator_video_tasks_mode_check
        CHECK (
            mode IN (
                'knowledge_only', 'benchmark_full', 'cluster',
                'transcript_archive', 'knowledge_from_archive'
            )
        );

ALTER TABLE content_studio.material_reconstructions
    DROP CONSTRAINT IF EXISTS material_reconstructions_mode_check;
ALTER TABLE content_studio.material_reconstructions
    ADD CONSTRAINT material_reconstructions_mode_check
        CHECK (
            mode IS NULL OR mode IN (
                'knowledge_only', 'benchmark_full',
                'transcript_archive', 'knowledge_from_archive'
            )
        );

-- Rollback is operational rather than destructive: stop admitting the two
-- new modes first.  Do not remove the constraints or evidence rows while
-- archive/knowledge tasks exist, because that would make retained audit data
-- invalid.  A future down migration may narrow these constraints only after
-- those rows are explicitly archived under a user-approved retention policy.
