-- migration 045: 渠道产品经济账字典（accounting schema，纯加法）
-- 来源：Desktop\和田宽\产品利润表.xlsx 三个 sheet（TM（全）/ 京东自营 / 京东POP），整表结构化导入。
-- 用途：每行 = 某渠道某产品某数量档的完整成本测算（出厂价/包材/运费/人工/发货成本/税/保本价/标价/实际售价
--      + 渠道特有列如京东毛保/推广费/入仓费——特有列进 components jsonb 零丢失）。
--      "等其他 SKU 用的时候再核算"：新 SKU 上天猫/京东时按条码查本表拿全套成本组件，桥接进 cost_items。
-- 数据导入走独立 SQL（与 044 同模式），本文件只管 schema。

CREATE TABLE IF NOT EXISTS accounting.channel_product_costs (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    channel         text NOT NULL CHECK (channel IN ('tmall', 'jd_self', 'jd_pop')),
    barcode         text,                 -- 13 位条码；组合装/无码品为 NULL
    product_name    text NOT NULL,
    category        text,                 -- 酱油/醋/...
    grade           text,
    spec            text,                 -- 规格（200ml/500ml/1L...）
    qty             numeric(6,2),         -- 该行数量档（1=单瓶、2=两瓶、组合=1）
    factory_price   numeric(10,4),        -- 出厂价/生产成本（单件）
    breakeven_price numeric(10,4),        -- 保本价
    list_price      numeric(10,4),        -- 标价
    actual_price    numeric(10,4),        -- 实际售价
    components      jsonb NOT NULL DEFAULT '{}'::jsonb,
                                          -- 该行其余全部列（表头→值）：快递包材/运费/人工分拣/发货成本/税点/税额/
                                          -- 服务费率/交易返点比例/毛保/推广费/入仓费/仓库分拣费/利润/赠品明细...
    source          text NOT NULL,        -- 产品利润表.xlsx#<sheet名>
    is_active       boolean NOT NULL DEFAULT true,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE accounting.channel_product_costs IS
    '渠道产品经济账字典（产品利润表.xlsx 整表导入）。无专属 MCP tool，SQL 直查；新 SKU 核算时按 barcode+channel 查全套成本组件。';
CREATE INDEX IF NOT EXISTS idx_cpc_barcode ON accounting.channel_product_costs (barcode) WHERE barcode IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cpc_channel ON accounting.channel_product_costs (channel) WHERE is_active;
