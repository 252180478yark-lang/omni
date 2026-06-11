-- migration 044: 物流运价字典 + 单瓶重量字典（accounting schema，纯加法）
-- 来源：Desktop\和田宽\物流价格单.xlsx（省×重量段快递价）
--      + 京东自营价格计算表(1).xlsx（条码挂钩单瓶克重/箱规/整箱重）
--      + 线上销售产品单瓶重量（现有产品）20240328.xlsx（名称口径补充）
-- 用途：把 cost_items 里「默认运费 5 元」兜底精化成按省×重量段真值；
--      重量字典 × 运价字典 = 单均物流成本测算（如 2×500ml 玻璃瓶 ≈ 1.9kg → 1.01-2KG 档）。
-- 数据导入走独立 SQL（与 product_price_list 的 import 脚本同模式），本文件只管 schema。

CREATE TABLE IF NOT EXISTS accounting.logistics_price_list (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    origin          text NOT NULL,                -- 始发仓（如 北京中心/京南中心/唐山中心）
    dest_province   text NOT NULL,                -- 目的省份/区段（内蒙按城市群拆三行，川西等例外区单列）
    weight_from_kg  numeric(6,2) NOT NULL,        -- 重量段下限（不含）
    weight_to_kg    numeric(6,2),                 -- 重量段上限（含）；NULL = 续重档无上限
    price           numeric(8,2) NOT NULL,
    price_basis     text NOT NULL CHECK (price_basis IN ('per_order', 'per_kg_extra')),
                                                  -- per_order=元/票；per_kg_extra=大于3KG续重 元/KG
    carrier         text,                         -- 中通/韵达
    valid_from      date NOT NULL DEFAULT CURRENT_DATE,
    valid_to        date,
    is_active       boolean NOT NULL DEFAULT true,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE accounting.logistics_price_list IS
    '快递运价字典（始发仓×目的省×重量段）。续重档(per_kg_extra)口径以快递合同为准：表头原文「大于3KG续重 元/KG」。';
CREATE INDEX IF NOT EXISTS idx_lpl_dest ON accounting.logistics_price_list (dest_province) WHERE is_active;

CREATE TABLE IF NOT EXISTS accounting.product_weight_list (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    barcode         text,                         -- 13 位条码；名称口径来源行为 NULL
    product_name    text NOT NULL,
    grade           text,
    spec            text,                         -- 单瓶规格（200ml/500ml/1L...）
    bottle_weight_g numeric(8,1),                 -- 单瓶毛重（克）；源表缺值为 NULL
    case_pack       integer,                      -- 箱规（瓶/箱）
    case_weight_kg  numeric(8,2),                 -- 整箱重量（含箱）
    material        text,                         -- 玻璃瓶/PET
    source          text NOT NULL,                -- 京东自营价格计算表 / 单瓶重量表20240328
    is_active       boolean NOT NULL DEFAULT true,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE accounting.product_weight_list IS
    '产品重量字典。条码行(京东自营价格计算表)优先；名称口径行(单瓶重量表)做补充，barcode 为 NULL。';
CREATE INDEX IF NOT EXISTS idx_pwl_barcode ON accounting.product_weight_list (barcode) WHERE barcode IS NOT NULL;
