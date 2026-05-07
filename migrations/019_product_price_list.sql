-- migrations/019_product_price_list.sql
-- W4-B 切片 8：工厂出厂价字典表（独立于 cost_items）
--
-- 语义：
--   product_price_list = 工厂"原始单品 SKU 出厂价"字典（来源：内部价格表）
--   cost_items         = mvp_sku（抖店渠道商品）维度的成本明细
--
-- 关系：mvp_sku 通常是工厂单品的组合（如套餐、试吃装），组成本时 agent 调
-- list_product_prices 查工厂出厂价 + 组合关系算出 mvp_sku 的总成本，再录到
-- cost_items 里。两表分开避免"渠道维度"与"工厂维度"混同。

CREATE TABLE IF NOT EXISTS accounting.product_price_list (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_name TEXT NOT NULL,            -- 价格表里的产品名（如「宽牌本酿造原汁酱油」）
    grade TEXT,                            -- 等级（如「特级」「酸度5°」「酒度10°」）
    spec TEXT,                             -- 规格（如「500ml*12」「1.8L*6P」）
    pack_size INTEGER,                     -- 箱装数（12/24/6/15...，可空）
    unit_price NUMERIC(12, 4) NOT NULL,    -- 单价（元/瓶，价格表的"单价"列）
    case_price NUMERIC(12, 4),             -- 箱价（可空；通常 = unit_price * pack_size）
    barcode TEXT,                          -- 条码（唯一标识工厂 SKU）
    vendor TEXT NOT NULL,                  -- "和田宽产品" / "辣嘴宽心系列产品"
    visibility TEXT NOT NULL DEFAULT 'public'
        CHECK (visibility IN ('public', 'real', 'shared')),
    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_to DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT product_price_unit_pos CHECK (unit_price >= 0),
    CONSTRAINT product_price_valid_range CHECK (
        valid_to IS NULL OR valid_to >= valid_from
    )
);

CREATE INDEX IF NOT EXISTS idx_ppl_vendor ON accounting.product_price_list (vendor);
CREATE INDEX IF NOT EXISTS idx_ppl_product_name
    ON accounting.product_price_list (product_name);
CREATE INDEX IF NOT EXISTS idx_ppl_barcode
    ON accounting.product_price_list (barcode) WHERE barcode IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ppl_active
    ON accounting.product_price_list (is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_ppl_visibility
    ON accounting.product_price_list (visibility);

-- 复用 content_studio.touch_updated_at 触发器（migration 011 已建）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_ppl_touch ON accounting.product_price_list;
        CREATE TRIGGER trg_ppl_touch
            BEFORE UPDATE ON accounting.product_price_list
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;

COMMENT ON TABLE accounting.product_price_list IS
    '工厂出厂价字典（每条 = 一个工厂单品 SKU 的出厂价）；mvp_sku 组成本时 agent 调 list_product_prices 查';
