-- Migration 013: SKU → brief → 视频 → 投放回传 的反馈飞轮
--
-- 目标：把"内容生成 → 投放 → 数据回传 → 反馈优化"打通到 SKU/brief 维度
-- 关系链：sku ──► briefs(sku_id) ──► pipelines(brief_id, sku_id) ──► 视频
--                                                                      │
--                                                                  上线投放
--                                                                      │
--                                  ad_review.materials(brief_id, sku_id, pipeline_id)
--                                                                      │
--                              prompt_feedbacks.input_ref = {brief_id, sku_id, material_id}

-- ═══ 1. briefs 复合索引：按 SKU 倒序拉历史 ═══
-- 路径 A 内容工作台 tab 要按 sku_id 倒序列 brief 列表，复合索引比单列索引更直接
CREATE INDEX IF NOT EXISTS idx_briefs_sku_created
    ON content_studio.briefs (sku_id, created_at DESC)
    WHERE sku_id IS NOT NULL;

-- ═══ 2. ad_review.materials 加 brief_id / sku_id / pipeline_id ═══
-- materials 表是投放回传数据的落点，加这三列后才能按 SKU/brief 维度切片做复盘
ALTER TABLE IF EXISTS ad_review.materials
    ADD COLUMN IF NOT EXISTS brief_id UUID,
    ADD COLUMN IF NOT EXISTS sku_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS pipeline_id UUID;

COMMENT ON COLUMN ad_review.materials.brief_id IS
    '回链 content_studio.briefs.id；这条投放素材是基于哪份 brief 生成的';
COMMENT ON COLUMN ad_review.materials.sku_id IS
    '回链 mvp_sku.id；冗余存储方便按 SKU 维度复盘（不用 join brief 拿）';
COMMENT ON COLUMN ad_review.materials.pipeline_id IS
    '回链 content_studio.pipelines.id；这条投放素材来自哪条生成 pipeline';

CREATE INDEX IF NOT EXISTS idx_materials_brief
    ON ad_review.materials (brief_id) WHERE brief_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_sku
    ON ad_review.materials (sku_id, created_at DESC) WHERE sku_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_pipeline
    ON ad_review.materials (pipeline_id) WHERE pipeline_id IS NOT NULL;
