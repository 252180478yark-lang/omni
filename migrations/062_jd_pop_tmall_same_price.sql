-- Migration 062: 京东POP 与天猫同价 → 利润视图回填 POP 实际售价（老板 2026-06-22 确认）
--
-- 背景：产品利润表.xlsx 里京东POP 与天猫**同售价**，但 channel_product_costs 的 jd_pop 行
--   只录了出厂价（→现算保本价），没录实际售价 → 毛利算不出（41 行 0 个有毛利）。
-- 解法：POP 缺 actual_price 时，取天猫同条码同数量的 actual_price 当有效售价，配 POP 自己的
--   成本结构（出厂价+税点+快递+POP扣点3.56%+运营支持费率 → 现算保本价）算真毛利。
-- 纯加法 CREATE OR REPLACE：旧列全保留，新增 actual_price_effective 列；data_completeness
--   加 'derived_tmall' 态（按天猫同价估算的 POP 行，跟自有售价的 'full' 区分，前端标注）。

CREATE OR REPLACE VIEW accounting.v_channel_product_margin AS
WITH pop_fee AS (   -- 京东POP 当前生效扣点（运营支持3.5%+交易服务0.06%=3.56%）
    SELECT COALESCE(MAX(fee_rate),0.0356) AS rate FROM accounting.channel_fees
    WHERE channel='jd_pop' AND fee_type='percentage'
      AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
),
base AS (
    SELECT c.*,
        -- 京东POP 现算保本价：(出厂价+快递费)/(1-税点-POP扣点-运营支持费率)
        CASE WHEN c.channel='jd_pop' AND c.factory_price IS NOT NULL THEN
            round((c.factory_price + COALESCE((c.components->>'快递费')::numeric,0))
              / NULLIF(1 - COALESCE((c.components->>'税点')::numeric,0.13)
                         - (SELECT rate FROM pop_fee)
                         - COALESCE((c.components->>'运营支持费率')::numeric,0),0), 4)
        END AS breakeven_pop,
        -- 京东POP 与天猫同价：POP 缺实际售价时取天猫同条码同数量售价
        CASE WHEN c.channel='jd_pop' AND c.actual_price IS NULL THEN
            (SELECT t.actual_price FROM accounting.channel_product_costs t
              WHERE t.channel='tmall' AND t.barcode=c.barcode AND t.qty=c.qty
                AND t.actual_price IS NOT NULL AND t.is_active
              ORDER BY t.actual_price LIMIT 1)
        END AS tmall_price
    FROM accounting.channel_product_costs c WHERE c.is_active
),
calc AS (
    SELECT b.*,
        COALESCE(b.actual_price, b.tmall_price)      AS actual_price_eff,
        COALESCE(b.breakeven_price, b.breakeven_pop) AS breakeven_eff
    FROM base b
)
SELECT channel,
    CASE channel WHEN 'tmall' THEN '天猫' WHEN 'jd_self' THEN '京东自营'
                 WHEN 'jd_pop' THEN '京东POP' ELSE channel END AS channel_cn,
    barcode, product_name, category, grade, spec, qty,
    factory_price, breakeven_price, list_price, actual_price,
    -- gross_profit：自有售价优先（天猫/自营 components.利润）→ 京东POP 用同价回填售价−有效保本价
    CASE
        WHEN actual_price IS NOT NULL AND actual_price>0
            THEN COALESCE((actual_price-breakeven_price), (components->>'利润')::numeric)
        WHEN channel='jd_pop' AND actual_price_eff IS NOT NULL AND breakeven_eff IS NOT NULL
            THEN round(actual_price_eff - breakeven_eff, 4)
    END                                              AS gross_profit,
    CASE
        WHEN actual_price IS NOT NULL AND actual_price>0
            THEN COALESCE(round((actual_price-breakeven_price)/actual_price,4),
                          round((components->>'利润率')::numeric,4))
        WHEN channel='jd_pop' AND actual_price_eff IS NOT NULL AND actual_price_eff>0 AND breakeven_eff IS NOT NULL
            THEN round((actual_price_eff - breakeven_eff)/actual_price_eff, 4)
    END                                              AS gross_margin,
    components                                       AS cost_components, source,
    breakeven_eff                                    AS breakeven_effective,
    CASE
        WHEN actual_price IS NOT NULL AND actual_price>0 AND breakeven_price IS NOT NULL THEN 'full'
        WHEN channel='jd_self' AND actual_price IS NOT NULL AND actual_price>0 THEN 'full'
        WHEN channel='jd_pop' AND actual_price_eff IS NOT NULL AND breakeven_eff IS NOT NULL THEN 'derived_tmall'
        WHEN breakeven_eff IS NOT NULL THEN 'breakeven_only'
        ELSE 'insufficient'
    END                                              AS data_completeness,
    -- ★新增列必须放末尾★（CREATE OR REPLACE 只能在尾部加列，不能改既有列序）
    actual_price_eff                                 AS actual_price_effective  -- 有效售价（京东POP=天猫同价回填）
FROM calc;

COMMENT ON VIEW accounting.v_channel_product_margin IS
    'Power BI 三渠道利润测算 v3：京东POP 与天猫同价回填售价算 POP 真毛利（data_completeness=derived_tmall）；天猫/自营自有售价=full；新增 actual_price_effective。旧列契约不变。';
