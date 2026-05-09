-- Migration 023: pipeline.scripts 升级支持 6 类素材（W4-B 切片 14.4 phase C）
--
-- 14.3 phase A 时 pipeline.scripts 设计为：必须挂 audience_pack/record/matrix_run，
-- 且 target_purpose 只 3 类（awareness/planting/conversion）。
--
-- 14.4 phase C 起：
--   1. 6 类素材：video_soft_ad / video_planting / video_harvest / graphic_harvest /
--      product_main_image / product_detail_page
--   2. 弹性挂：允许只挂 sku_id（绕过 pack/record，老板临时想试主图/收割图文不必先做圈包）
--   3. target_purpose 字段保留向后兼容（视频三档可写入 awareness/planting/conversion；
--      图文/主图/详情页那 3 类不写 target_purpose）

-- 1. 链路三个 NOT NULL 改 NULLABLE（保留 sku_id NOT NULL）
ALTER TABLE pipeline.scripts ALTER COLUMN audience_pack_id DROP NOT NULL;
ALTER TABLE pipeline.scripts ALTER COLUMN audience_record_id DROP NOT NULL;
ALTER TABLE pipeline.scripts ALTER COLUMN matrix_run_id DROP NOT NULL;

-- 2. 加 kind 字段（不 NOT NULL，允许历史行为空）
ALTER TABLE pipeline.scripts ADD COLUMN IF NOT EXISTS kind TEXT;

-- 3. kind CHECK 6 enum 值（允许 NULL 用于历史行 / 边缘情况）
ALTER TABLE pipeline.scripts DROP CONSTRAINT IF EXISTS scripts_kind_check;
ALTER TABLE pipeline.scripts ADD CONSTRAINT scripts_kind_check
    CHECK (kind IS NULL OR kind IN (
        'video_soft_ad',         -- 视频 · 软广（A2 触动 / 内容娱乐化软植入）
        'video_planting',        -- 视频 · 种草（A3 共鸣 / 讲产品力 + 我懂你）
        'video_harvest',         -- 视频 · 收割（A4 行动 / 限时 + 价格 + CTA）
        'graphic_harvest',       -- 图文 · 收割（小红书/抖店图文，转化导向）
        'product_main_image',    -- 商品视觉 · 主图（5-9 张冲击力 + 卖点叠加）
        'product_detail_page'    -- 商品视觉 · 详情页（叙事长图，卖点闭环）
    ));

-- 4. 索引：按 sku + kind 查最近创意
CREATE INDEX IF NOT EXISTS idx_scripts_sku_kind
    ON pipeline.scripts (sku_id, kind, created_at DESC) WHERE kind IS NOT NULL;

COMMENT ON COLUMN pipeline.scripts.kind IS '素材类型：6 类素材（video_soft_ad/planting/harvest, graphic_harvest, product_main_image, product_detail_page）；NULL 表示历史行（14.3 phase A 时建表，未启用）';
COMMENT ON COLUMN pipeline.scripts.audience_pack_id IS '可选：挂 step 4 圈包；老板临时想试主图/收割图文时可绕过';
COMMENT ON COLUMN pipeline.scripts.audience_record_id IS '可选：挂 step 3 单条人群（弹性挂，绕过 step 4 也行）';
COMMENT ON COLUMN pipeline.scripts.matrix_run_id IS '可选：挂 step 2 卖点矩阵（最弱约束，单 SKU 也能跑）';
