-- W4-B 14.4 step 6 双图：首帧(image) + 尾帧(image_last)
-- 扩展 pipeline.assets asset_type CHECK 约束

DO $$
BEGIN
    ALTER TABLE pipeline.assets DROP CONSTRAINT IF EXISTS assets_type_check;
    ALTER TABLE pipeline.assets ADD CONSTRAINT assets_type_check
        CHECK (asset_type IN ('image', 'image_last', 'video', 'character_sheet'));
END $$;
