-- W4-B step 6 首尾帧重构：image_first（入帧）独立存储
-- 保留 image 兼容旧数据，新生成用 image_first + image_last

ALTER TABLE pipeline.assets
    DROP CONSTRAINT IF EXISTS assets_type_check;

ALTER TABLE pipeline.assets
    ADD CONSTRAINT assets_type_check
    CHECK (asset_type IN ('image', 'image_first', 'image_last', 'video', 'character_sheet'));
