-- Content Pipeline v2 — extras (extra_reference_images / version metadata / indexes)
-- Idempotent. All ALTER use IF NOT EXISTS, all new columns NULLable, no data migration.

-- 1) pipelines: 临时上传的人脸/产品参考图（不落 Avatar/产品库）
ALTER TABLE content_studio.pipelines
    ADD COLUMN IF NOT EXISTS extra_reference_images JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS audience_package       JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_pipelines_product
    ON content_studio.pipelines (product_id);

-- 2) briefs: parent_brief_id 索引；version 字段已存在
CREATE INDEX IF NOT EXISTS idx_briefs_parent
    ON content_studio.briefs (parent_brief_id);
CREATE INDEX IF NOT EXISTS idx_briefs_status
    ON content_studio.briefs (status);

-- 3) digital_humans: 经常按 quality_score / ctr_avg 排序
CREATE INDEX IF NOT EXISTS idx_digital_humans_quality
    ON content_studio.digital_humans (quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_digital_humans_ctr
    ON content_studio.digital_humans (ctr_avg DESC);

-- 4) ad_review.materials: pipeline_id 关联（campaign 级关联已在 003 里建好，
--    这里再补一个素材级关联，回灌时按 material 而非按 campaign 也能找到）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'ad_review' AND table_name = 'materials'
    ) THEN
        EXECUTE 'ALTER TABLE ad_review.materials
                 ADD COLUMN IF NOT EXISTS pipeline_id UUID NULL';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_materials_pipeline
                 ON ad_review.materials (pipeline_id)';
    END IF;
END $$;
