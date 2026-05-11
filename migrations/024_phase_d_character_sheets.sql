-- W4-B 切片 14.4 phase D：脚本=单一创意源 + character_sheet 锁脸
-- pipeline.scripts 加 character_sheets JSONB（顶部"第 3.5 部分 角色清单"解析后存）
-- pipeline.assets 加 character_role TEXT（asset_type='character_sheet' 时填 daughter/mother 等）

ALTER TABLE pipeline.scripts
    ADD COLUMN IF NOT EXISTS character_sheets JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN pipeline.scripts.character_sheets IS
'解析自 script_md 第 3.5 部分角色清单。每条 [{role_id, name, age, gender, appearance_keywords, aura, audience_anchor}]。step 6.5 拿这个清单生成每个角色的白底正面像。';

ALTER TABLE pipeline.assets
    ADD COLUMN IF NOT EXISTS character_role TEXT;

COMMENT ON COLUMN pipeline.assets.character_role IS
'仅 asset_type=character_sheet 时填，对应 scripts.character_sheets[].role_id（如 daughter / mother / friend）。step 6 跑分镜图时按 scene.characters_in_scene 找同 script 的 character_sheet asset url 当 face_refs。';

-- 扩展 asset_type CHECK 约束加 character_sheet
DO $$
BEGIN
    -- 先 drop 旧约束（可能还没建 — IF EXISTS）
    ALTER TABLE pipeline.assets DROP CONSTRAINT IF EXISTS assets_type_check;
    ALTER TABLE pipeline.assets ADD CONSTRAINT assets_type_check
        CHECK (asset_type IN ('image', 'video', 'character_sheet'));
END $$;

CREATE INDEX IF NOT EXISTS idx_assets_character_role
    ON pipeline.assets (script_id, character_role)
    WHERE character_role IS NOT NULL;
