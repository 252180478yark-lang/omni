-- Migration 012: mvp_sku 加规格字段
-- 目标：老板视角输入再加一个"产品规格"自由文本字段，喂给内容编排器的 LLM
-- 适用：路径 A v1.5 + SKU 内容编排（migration 011 之后）

ALTER TABLE IF EXISTS public.mvp_sku
    ADD COLUMN IF NOT EXISTS specifications TEXT;

COMMENT ON COLUMN public.mvp_sku.specifications IS
    '老板手填的产品规格（自由文本，调味品场景示例："500ml*2瓶 送200ml*2瓶 / 200ml试吃装 / 外卖小包10ml*10")';
