-- migration 046: SKU 组件映射表（accounting schema，纯加法）—— mvp_sku ↔ 工厂单品条码桥
-- 背景：mvp_sku 无 barcode 列，跟三张条码维度字典（product_price_list 出厂价 /
--      product_weight_list 重量 / channel_product_costs 渠道经济账）完全接不上；
--      组合关系只存在 cost_items.notes 自由文本里（如 "2×500ml(¥17.5) + 2×200ml(¥9.5)"）。
-- 用途：BI 经济账面板的前置依赖。一行 = 某 mvp_sku 含某工厂单品（条码）qty 件；
--      JOIN product_price_list 可重算出厂价合计、JOIN product_weight_list 可算单均物流重量档。
-- 种子数据：由 cost_items.notes（2026-06-11 产品利润表批量桥接 + 老板确认行）
--      与 product_price_list 的 product_name/grade/spec/unit_price 逐行对账落出，
--      单价能对上 unit_price 为强证据；对不上 / 字典缺条码的 SKU 不写（见文件尾未映射清单）。

CREATE TABLE IF NOT EXISTS accounting.sku_components (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id      varchar(64) NOT NULL,         -- mvp_sku.id
    barcode     text NOT NULL,                -- accounting.product_price_list.barcode（13 位条码）
    qty         numeric(6,2) NOT NULL DEFAULT 1,  -- 该 SKU 含该工厂单品几件
    notes       text,                         -- 匹配依据（来源 cost_items.notes / 单价对账）
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sku_id, barcode)
);
COMMENT ON TABLE accounting.sku_components IS
    'mvp_sku ↔ 工厂单品条码映射（组合关系）。Σ(qty×product_price_list.unit_price) ≈ cost_items 该 SKU 的「出厂价合计」。无专属 MCP tool，SQL 直查/JOIN 三张条码字典用。⚠ JOIN product_price_list 必须加 p.is_active 过滤（同条码可能留有已停用旧价行，如 6937320700997）。';
CREATE INDEX IF NOT EXISTS idx_skc_barcode ON accounting.sku_components (barcode) WHERE is_active;

-- ============================================================================
-- 种子数据（28 个 active SKU / 35 行；对账基准 = cost_items「出厂价合计」2026-06-11 行）
-- ============================================================================
INSERT INTO accounting.sku_components (sku_id, barcode, qty, notes) VALUES
    -- SKU-367991-0001 有机本酿造特级酱油500ml；出厂价合计 17.5
    ('SKU-367991-0001', '6937320700638', 1, '由 cost_items.notes 解析: 1×有机本酿造日式酱油 特级 500ml(17.5)；对上 price_list 有机本酿造日式酱油/特级/500ml*12 unit_price=17.5'),
    -- SKU-367991-0002 有机本酿造特级酱油 500ml*2+200ml*2；出厂价合计 54 = 2×17.5+2×9.5
    ('SKU-367991-0002', '6937320700638', 2, '由 cost_items.notes 解析: 2×500ml(¥17.5)；对上 price_list 有机本酿造日式酱油/特级/500ml*12 unit_price=17.5'),
    ('SKU-367991-0002', '6937320703387', 2, '由 cost_items.notes 解析: 2×200ml(¥9.5)；对上 price_list 有机本酿造日式酱油/特级/200ml*12 unit_price=9.5'),
    -- SKU-367992-0002 有机5度黑醋（500ml口径）；出厂价合计 17.5
    ('SKU-367992-0002', '6937320700645', 1, '由 cost_items.notes 解析: 1×有机黑醋 5° 500ml(17.5)（链接名无规格,按售价29.9对标500ml口径）；对上 price_list 有机黑醋/酸度5°/500ml*12 unit_price=17.5'),
    -- SKU-367993-0003 有机5度白米醋500ml；出厂价合计 16
    ('SKU-367993-0003', '6937320700669', 1, '由 cost_items.notes 解析: 1×有机白米醋 5° 500ml(16)；对上 price_list 有机白米醋/酸度5°/500ml*12 unit_price=16'),
    -- SKU-367994-0003 有机5度白米醋试吃装2瓶200ml；出厂价合计 19 = 2×9.5
    ('SKU-367994-0003', '6937320703417', 2, '由 cost_items.notes 解析: 2×有机白米醋 5° 200ml(9.5) 试吃装；对上 price_list 有机白米醋/酸度5°/200ml*12 unit_price=9.5'),
    -- SKU-367994-0006 本酿造1L*2瓶；出厂价合计 27 = 2×13.5
    ('SKU-367994-0006', '6937320700133', 2, '由 cost_items.notes 解析: 2×本酿造原汁酱油 特级 1L(13.5)；对上 price_list 宽牌本酿造原汁酱油/特级/1L*15 unit_price=13.5'),
    -- SKU-367995-0002 饺子醋500ml（多规格按单瓶口径）；出厂价合计 6
    ('SKU-367995-0002', '6937320703363', 1, '由 cost_items.notes 解析: 1×饺子醋 酸度4.5° 500ml(6)；对上 price_list 饺子醋/酸度4.5°/500ml*12 unit_price=6'),
    -- SKU-367995-0007 饺子酱油（多规格按单瓶口径）；出厂价合计 6
    ('SKU-367995-0007', '6937320703370', 1, '由 cost_items.notes 解析: 1×饺子酱油 特级 500ml(6)；对上 price_list 饺子酱油/特级/500ml*12 unit_price=6'),
    -- SKU-368029-0000 刺身酱油200ml（多规格按单瓶口径）；出厂价合计 6.5
    ('SKU-368029-0000', '6937320700218', 1, '由 cost_items.notes 解析: 1×刺身酱油 特级 200ml(6.5)；对上 price_list 宽牌刺身酱油/特级/200ml*12 unit_price=6.5'),
    -- SKU-368029-0008 饺子醋×2+饺子酱油×1；出厂价合计 18 = 2×6+1×6（组成=老板确认 2026-06-11）
    ('SKU-368029-0008', '6937320703363', 2, '由 cost_items.notes 解析: 2×饺子醋 酸度4.5° 500ml(6)，组成=老板确认 2026-06-11；对上 price_list 饺子醋/酸度4.5°/500ml*12 unit_price=6'),
    ('SKU-368029-0008', '6937320703370', 1, '由 cost_items.notes 解析: 1×饺子酱油 特级 500ml(6)，组成=老板确认 2026-06-11；对上 price_list 饺子酱油/特级/500ml*12 unit_price=6'),
    -- SKU-368048-0005 有机三件套（酱油+黑醋+白米醋各500ml）；出厂价合计 51 = 17.5+17.5+16（组成=老板确认 2026-06-11）
    ('SKU-368048-0005', '6937320700638', 1, '由 cost_items.notes 解析: 1×有机本酿造日式酱油 特级 500ml(17.5)，组成=老板确认 2026-06-11；对上 price_list unit_price=17.5'),
    ('SKU-368048-0005', '6937320700645', 1, '由 cost_items.notes 解析: 1×有机黑醋 5° 500ml(17.5)，组成=老板确认 2026-06-11；对上 price_list unit_price=17.5'),
    ('SKU-368048-0005', '6937320700669', 1, '由 cost_items.notes 解析: 1×有机白米醋 5° 500ml(16)，组成=老板确认 2026-06-11；对上 price_list unit_price=16'),
    -- SKU-368083-0001 味极鲜1L*2瓶；出厂价合计 18 = 2×9
    ('SKU-368083-0001', '6937320700553', 2, '由 cost_items.notes 解析: 2×味极鲜酱油-特级生抽 1L(9)；对上 price_list 宽牌味极鲜酱油-特级生抽/特级/1L*15 unit_price=9'),
    -- SKU-368306-0000 10度白米醋500ml；出厂价合计 6
    ('SKU-368306-0000', '6937320700461', 1, '由 cost_items.notes 解析: 1×宽牌10°白米醋 500ml(6)；对上 price_list 宽牌10°白米醋/酸度10°/500ml*12 unit_price=6'),
    -- SKU-368978-0004 有机黑醋 500ml*2+200ml*2；出厂价合计 54 = 2×17.5+2×9.5（组成=老板确认 2026-06-11，负毛利链接）
    ('SKU-368978-0004', '6937320700645', 2, '由 cost_items.notes 解析: 2×有机黑醋 5° 500ml(17.5)，组成=老板确认 2026-06-11；对上 price_list 有机黑醋/酸度5°/500ml*12 unit_price=17.5'),
    ('SKU-368978-0004', '6937320703400', 2, '由 cost_items.notes 解析: 2×有机黑醋 200ml(9.5)，组成=老板确认 2026-06-11；对上 price_list 有机黑醋/酸度5°/200ml*12 unit_price=9.5'),
    -- SKU-375753-0001 米糀辣酱油 500ml*2+200ml*2；出厂价合计 18.8 = 2×6.2+2×3.2
    ('SKU-375753-0001', '6937320700942', 2, '由 cost_items.notes 解析: 2×米糀辣酱油 特级 500ml(6.2)；对上 price_list 米糀辣酱油/特级/500ml*12P(辣嘴宽心) unit_price=6.2'),
    ('SKU-375753-0001', '6937320700935', 2, '由 cost_items.notes 解析: 2×米糀辣酱油 特级 200ml(3.2)；对上 price_list 米糀辣酱油/特级/200ml*12P(辣嘴宽心) unit_price=3.2'),
    -- SKU-375763-0000 米糀辣黑醋 500ml*2+200ml*2；出厂价合计 17.4 = 2×5.2+2×3.5
    ('SKU-375763-0000', '6937320701208', 2, '由 cost_items.notes 解析: 2×米糀辣黑醋 5° 500ml(5.2)；对上 price_list 米糀辣黑醋/5°/500ml*12P(辣嘴宽心) unit_price=5.2'),
    ('SKU-375763-0000', '6937320700997', 2, '由 cost_items.notes 解析: 2×米糀辣黑醋 200ml(3.5)（200ml价按利润表3.5 老板拍板 2026-06-11）；对上 price_list 米糀辣黑醋/5°/200ml*12P(辣嘴宽心) unit_price=3.5'),
    -- SKU-376006-0004 有机本酿造日式酱油200ml；出厂价合计 9.5
    ('SKU-376006-0004', '6937320703387', 1, '由 cost_items.notes 解析: 1×有机本酿造日式酱油 特级 200ml(9.5)；对上 price_list 有机本酿造日式酱油/特级/200ml*12 unit_price=9.5'),
    -- SKU-376253-0012 有机本酿造日式酱油200ml（同款另链接）；出厂价合计 9.5
    ('SKU-376253-0012', '6937320703387', 1, '由 cost_items.notes 解析: 1×有机本酿造日式酱油 特级 200ml(9.5)；对上 price_list 有机本酿造日式酱油/特级/200ml*12 unit_price=9.5'),
    -- SKU-378043-0005 有机5度黑醋200ml；出厂价合计 9.5
    ('SKU-378043-0005', '6937320703400', 1, '由 cost_items.notes 解析: 1×有机黑醋 5° 200ml(9.5)；对上 price_list 有机黑醋/酸度5°/200ml*12 unit_price=9.5'),
    -- SKU-378044-0007/0008/0009/0010 有机5度白米醋200ml（同款 4 条链接）；出厂价合计各 9.5
    ('SKU-378044-0007', '6937320703417', 1, '由 cost_items.notes 解析: 1×有机白米醋 5° 200ml(9.5)；对上 price_list 有机白米醋/酸度5°/200ml*12 unit_price=9.5'),
    ('SKU-378044-0008', '6937320703417', 1, '由 cost_items.notes 解析: 1×有机白米醋 5° 200ml(9.5)；对上 price_list 有机白米醋/酸度5°/200ml*12 unit_price=9.5'),
    ('SKU-378044-0009', '6937320703417', 1, '由 cost_items.notes 解析: 1×有机白米醋 5° 200ml(9.5)；对上 price_list 有机白米醋/酸度5°/200ml*12 unit_price=9.5'),
    ('SKU-378044-0010', '6937320703417', 1, '由 cost_items.notes 解析: 1×有机白米醋 5° 200ml(9.5)；对上 price_list 有机白米醋/酸度5°/200ml*12 unit_price=9.5'),
    -- SKU-378044-0011 链接名为黑醋200ml（与同组白米醋链接区分，见 cost_items.notes）；出厂价合计 9.5
    ('SKU-378044-0011', '6937320703400', 1, '由 cost_items.notes 解析: 1×有机黑醋 5° 200ml(9.5)（链接名为黑醋,与同组白米醋区分）；对上 price_list 有机黑醋/酸度5°/200ml*12 unit_price=9.5'),
    -- SKU-378619-0006 / SKU-380920-0006/0007/0011 寿喜烧250ml（同款 4 条链接）；出厂价合计各 8
    ('SKU-378619-0006', '6937320700423', 1, '由 cost_items.notes 解析: 1×寿喜烧 250ml(8)；对上 price_list 寿喜烧/250ml*12P(辣嘴宽心) unit_price=8'),
    ('SKU-380920-0006', '6937320700423', 1, '由 cost_items.notes 解析: 1×寿喜烧 250ml(8)；对上 price_list 寿喜烧/250ml*12P(辣嘴宽心) unit_price=8'),
    ('SKU-380920-0007', '6937320700423', 1, '由 cost_items.notes 解析: 1×寿喜烧 250ml(8)；对上 price_list 寿喜烧/250ml*12P(辣嘴宽心) unit_price=8'),
    ('SKU-380920-0011', '6937320700423', 1, '由 cost_items.notes 解析: 1×寿喜烧 250ml(8)；对上 price_list 寿喜烧/250ml*12P(辣嘴宽心) unit_price=8')
ON CONFLICT (sku_id, barcode) DO NOTHING;

-- ============================================================================
-- 未映射 SKU（active 且有 cost_items 行，但无法 ground 到条码——不写种子，留人工补）
-- ============================================================================
-- SKU-373910-0013 和田宽外卖酱油包小包 辣酱油10ml*10包：
--   cost_items.notes = "1×米糀辣酱油(减盐)外卖袋装 10ml*10(2)"。
--   product_price_list 有完全匹配行（米糀辣酱油（减盐）/特级/10m1*10袋/unit_price=2.0，
--   vendor=和田宽产品），单价对得上，但该行 barcode 为 NULL（源价格表外卖袋装无条码），
--   本表 barcode NOT NULL 落不了行。待价格表补条码后人工 INSERT。
