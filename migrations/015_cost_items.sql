-- Migration 015: 成本项结构化表（cost_items）
--
-- 目标：把"公司成本/价格/物流/合作方报价"从 KB 文档型迁出，
--      走结构化查询。配套阶段二 accounting_tool：净利率精确计算
--      （不再走 RAG 模糊匹配）。
--
-- 三类 category：
--   product         产品成本（原料/包装/瓶身/标签/箱/人工等）
--   logistics       物流成本（顺丰华东/京东专线/同城配送等）
--   partner_quote   合作方报价（代工厂报价/服务商报价）
--
-- 关键字段：
--   sku_id            可空 —— 共享成本（如物流费）不绑定 SKU
--   unit + quantity_per_unit  支持"一箱 24 瓶 X 元"折算
--   valid_from/valid_to       价格变更走新行 + 关旧行（保留历史）
--   is_active                 软删除

CREATE SCHEMA IF NOT EXISTS accounting;
COMMENT ON SCHEMA accounting IS 'Accounting data: cost items, margin logs, partner quotes';

CREATE TABLE IF NOT EXISTS accounting.cost_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id VARCHAR(64),
    category TEXT NOT NULL,
    item_name TEXT NOT NULL,
    unit_cost NUMERIC(12,4) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'CNY',
    unit TEXT NOT NULL DEFAULT '件',
    quantity_per_unit NUMERIC(12,4) NOT NULL DEFAULT 1,
    vendor TEXT,
    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_to DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT cost_items_category_check
        CHECK (category IN ('product', 'logistics', 'partner_quote')),
    CONSTRAINT cost_items_unit_cost_nonneg
        CHECK (unit_cost >= 0),
    CONSTRAINT cost_items_quantity_pos
        CHECK (quantity_per_unit > 0),
    CONSTRAINT cost_items_valid_range
        CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE INDEX IF NOT EXISTS idx_cost_items_sku
    ON accounting.cost_items (sku_id) WHERE sku_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cost_items_category
    ON accounting.cost_items (category);
CREATE INDEX IF NOT EXISTS idx_cost_items_valid_from
    ON accounting.cost_items (valid_from DESC);
CREATE INDEX IF NOT EXISTS idx_cost_items_active
    ON accounting.cost_items (is_active) WHERE is_active = TRUE;

-- 复用 content_studio.touch_updated_at（migration 011 已建）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_cost_items_touch ON accounting.cost_items;
        CREATE TRIGGER trg_cost_items_touch
            BEFORE UPDATE ON accounting.cost_items
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;
