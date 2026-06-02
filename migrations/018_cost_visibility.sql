-- migrations/018_cost_visibility.sql
-- W4-B 切片 7：成本两版（老板真实成本 vs 员工出厂价）
--
-- 语义：
--   visibility='public'   员工版独占（"出厂价"，可对外）
--   visibility='real'     老板版独占（真实成本，需 passphrase 才查）
--   visibility='shared'   两版共用（如物流费、平台扣点等共用成本）
--
-- 视图过滤规则：
--   view='public' (默认)  WHERE visibility IN ('public', 'shared')
--   view='real'           WHERE visibility IN ('real',   'shared')  + 校验 passphrase

ALTER TABLE accounting.cost_items
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'shared'
        CHECK (visibility IN ('public', 'real', 'shared'));

-- 历史数据默认 'shared'：两版都看到，老板再渐次按 SKU 补录 'public' / 'real' 区分
COMMENT ON COLUMN accounting.cost_items.visibility IS
    '成本可见范围：public=员工版/real=老板真实版/shared=两版共用（默认）';

-- 索引：按 visibility 过滤是高频路径，加部分索引
CREATE INDEX IF NOT EXISTS idx_cost_items_visibility
    ON accounting.cost_items (visibility);
