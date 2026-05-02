-- Content Pipeline v2 — multi-character avatar mapping
-- Idempotent; column NULLable.

ALTER TABLE content_studio.pipelines
    ADD COLUMN IF NOT EXISTS character_avatar_map JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Optional comment for clarity
COMMENT ON COLUMN content_studio.pipelines.character_avatar_map IS
    '多角色场景：scene 中 character name -> digital_human_id（uuid 字符串）映射';
