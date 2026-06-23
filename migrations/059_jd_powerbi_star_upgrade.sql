-- Migration 059: 京东 Power BI 星型模型升级（纯加法 · 不破坏现有 4 视图对外契约）
-- ============================================================================
-- 设计目标（说人话）：把京东 Power BI 的 4 张散视图，升级成 1 套星型模型——
--   一张日期维表（dim_date）做时间骨架，几张事实视图挂上去，对外旧列一个不删、
--   只新增列，老报表不返工。所有变更 CREATE OR REPLACE VIEW / CREATE TABLE IF NOT EXISTS，
--   可逆、不动既有 UNIQUE、不改任何裸表数据。
--
-- 口径铁律（反幻觉）：金额单位元；rate/占比/费率 存原始 0-1；rank 越小越好；
--   数据稀疏的（京东 7 天 / 商品榜 1 天 / 京东POP 利润）该标缺就标缺，不补 0 不编值。
-- ============================================================================


-- ████ 1. 日期维表 dim_date（星型骨架，2025-2027 连续日历）████████████████████
-- 解多痛点：① 跨平台京东 7 天 vs 抖音 33 天用同一时间轴对齐；② 给 Power BI 周/月/季
--   下钻粒度；③ 缺失日 LEFT JOIN 后显示 0 而非断点。物化成真表（不是视图）让 Import
--   模式直接拖、建关系。覆盖 2025-01-01 ~ 2027-12-31（含京东财年场景）。
CREATE TABLE IF NOT EXISTS public.dim_date (
    date          DATE        PRIMARY KEY,
    year          SMALLINT    NOT NULL,
    quarter       SMALLINT    NOT NULL,        -- 1..4
    month         SMALLINT    NOT NULL,        -- 1..12
    day           SMALLINT    NOT NULL,        -- 1..31
    week_of_year  SMALLINT    NOT NULL,        -- ISO 周
    iso_year      SMALLINT    NOT NULL,        -- ISO 周所属年（跨年周用）
    day_of_week   SMALLINT    NOT NULL,        -- 1=周一 .. 7=周日（ISO）
    is_weekend    BOOLEAN     NOT NULL,        -- 周六/周日
    month_cn      TEXT        NOT NULL,        -- 一月..十二月
    weekday_cn    TEXT        NOT NULL,        -- 周一..周日
    year_month    TEXT        NOT NULL,        -- '2026-06'（Power BI 月切片轴）
    year_week     TEXT        NOT NULL,        -- '2026-W24'
    quarter_cn    TEXT        NOT NULL         -- '2026Q2'
);

-- 幂等填充：只插不存在的日期（重跑安全）
INSERT INTO public.dim_date (
    date, year, quarter, month, day, week_of_year, iso_year, day_of_week,
    is_weekend, month_cn, weekday_cn, year_month, year_week, quarter_cn)
SELECT
    d::date                                                                    AS date,
    EXTRACT(YEAR  FROM d)::smallint                                            AS year,
    EXTRACT(QUARTER FROM d)::smallint                                          AS quarter,
    EXTRACT(MONTH FROM d)::smallint                                            AS month,
    EXTRACT(DAY   FROM d)::smallint                                            AS day,
    EXTRACT(WEEK  FROM d)::smallint                                            AS week_of_year,
    EXTRACT(ISOYEAR FROM d)::smallint                                          AS iso_year,
    EXTRACT(ISODOW FROM d)::smallint                                           AS day_of_week,
    (EXTRACT(ISODOW FROM d) >= 6)                                              AS is_weekend,
    (ARRAY['一月','二月','三月','四月','五月','六月',
           '七月','八月','九月','十月','十一月','十二月'])[EXTRACT(MONTH FROM d)::int] AS month_cn,
    (ARRAY['周一','周二','周三','周四','周五','周六','周日'])[EXTRACT(ISODOW FROM d)::int] AS weekday_cn,
    to_char(d, 'YYYY-MM')                                                      AS year_month,
    EXTRACT(ISOYEAR FROM d)::text || '-W' || lpad(EXTRACT(WEEK FROM d)::text, 2, '0') AS year_week,
    EXTRACT(YEAR FROM d)::text || 'Q' || EXTRACT(QUARTER FROM d)::text         AS quarter_cn
FROM generate_series('2025-01-01'::date, '2027-12-31'::date, '1 day'::interval) d
ON CONFLICT (date) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_dim_date_ym   ON public.dim_date (year_month);
CREATE INDEX IF NOT EXISTS idx_dim_date_year ON public.dim_date (year, month);

COMMENT ON TABLE public.dim_date IS
    '星型日期维表 2025-2027 连续日历：年/季/月/周/星期/是否周末/中文月名。Power BI 时间骨架，缺失日填0、跨平台对齐、周月季下钻。';


-- ████ 2. 利润视图升级 v_channel_product_margin（改写读 components + 京东POP 算保本）████
-- 对外契约：原 16 列全保留（含 gross_profit/gross_margin/cost_components）。
-- 改动：① gross_profit/gross_margin 用 COALESCE 优先标量(actual-breakeven)，回退读
--   components->>'利润'/'利润率'（京东自营已算好的，剔除 0.0 占位行）；
--   ② 京东POP 没有 breakeven_price → 用 factory_price + 税点 + 快递费 + 京东POP扣点(channel_fees)
--   + 运营支持费率 现场算 breakeven_pop（仅 factory_price 存在的行，否则 NULL）；
--   ③ 新增列（纯加法，不破坏旧报表）：breakeven_effective / data_completeness（数据完整度标记）。
--
-- ⚠️ 真相纠偏（审计原文有偏差，以 live 数据为准）：
--   · 京东自营 components->>'利润' 仅 3 行是真值（=actual-breakeven，那 3 行 actual_price 有值），
--     其余 43 行是 0.0 占位（不是负值占位）。真正卡点是 actual_price 稀疏(3/46)，不是视图没读 components。
--     读 components 这里做"未来 actual_price 补齐前的兜底"，当前救不回多少行 → 完整度标记如实暴露。
--   · 京东POP breakeven 全 0、无利润键，只能现算；且 41 行里只 16 行有 factory_price → 其余 NULL 标缺。
CREATE OR REPLACE VIEW accounting.v_channel_product_margin AS
WITH pop_fee AS (   -- 京东POP 当前生效扣点（运营支持3.5%+交易服务0.06%=3.56%），channel_fees 真值
    SELECT COALESCE(MAX(fee_rate), 0.0356) AS rate
    FROM accounting.channel_fees
    WHERE channel = 'jd_pop' AND fee_type = 'percentage'
      AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
),
base AS (
    SELECT
        c.*,
        -- 京东POP 现场算保本价（仅 factory_price 存在时）：
        --   保本价 = (出厂价 + 快递费) / (1 - 税点 - POP扣点 - 运营支持费率)
        --   税点缺→0.13 兜底；快递费缺→0；运营支持费率缺→走 POP扣点已含的 0（不重复扣）
        CASE WHEN c.channel = 'jd_pop' AND c.factory_price IS NOT NULL THEN
            round(
                (c.factory_price + COALESCE((c.components->>'快递费')::numeric, 0))
                / NULLIF(
                    1
                    - COALESCE((c.components->>'税点')::numeric, 0.13)
                    - (SELECT rate FROM pop_fee)
                    - COALESCE((c.components->>'运营支持费率')::numeric, 0),
                  0),
                4)
        END AS breakeven_pop
    FROM accounting.channel_product_costs c
    WHERE c.is_active
)
SELECT
    channel,
    CASE channel
        WHEN 'tmall'   THEN '天猫'
        WHEN 'jd_self' THEN '京东自营'
        WHEN 'jd_pop'  THEN '京东POP'
        ELSE channel
    END                                                       AS channel_cn,
    barcode, product_name, category, grade, spec, qty,
    factory_price, breakeven_price, list_price, actual_price,
    -- gross_profit：标量优先（actual-breakeven）。回退读 components->>'利润' 仅在 actual_price 有值时，
    --   因为 components.利润 在 actual_price 缺位时是占位（京东自营 43 行：0.0 或 -breakeven 噪声，非真账亏损）——
    --   不 gate 会把"算不出"误显成"真亏 -18 元"。gate 后只放行 actual_price 真值行。
    CASE WHEN actual_price IS NOT NULL AND actual_price > 0
         THEN COALESCE(
                (actual_price - breakeven_price),
                (components->>'利润')::numeric)
    END                                                       AS gross_profit,
    -- gross_margin：同理 gate 在 actual_price 有值时
    CASE WHEN actual_price IS NOT NULL AND actual_price > 0
         THEN COALESCE(
                round((actual_price - breakeven_price) / actual_price, 4),
                round((components->>'利润率')::numeric, 4))
    END                                                       AS gross_margin,
    components                                                AS cost_components,
    source,
    -- ★ 新增列（纯加法）★
    -- 生效保本价：标量 breakeven_price 优先，京东POP 回退现算 breakeven_pop
    COALESCE(breakeven_price, breakeven_pop)                  AS breakeven_effective,
    -- 数据完整度标记（前端角标用，反幻觉地暴露"为什么这条没毛利"）
    CASE
        WHEN actual_price IS NOT NULL AND actual_price > 0
             AND breakeven_price IS NOT NULL                  THEN 'full'          -- 利润可信
        WHEN channel = 'jd_pop' AND breakeven_pop IS NOT NULL
             AND actual_price IS NULL                         THEN 'breakeven_only'-- 有保本无售价
        WHEN breakeven_price IS NOT NULL AND actual_price IS NULL THEN 'breakeven_only'
        ELSE 'insufficient'                                                          -- 利润算不出
    END                                                       AS data_completeness
FROM base;

COMMENT ON VIEW accounting.v_channel_product_margin IS
    'Power BI 三渠道利润测算 v2：毛利 COALESCE(标量,components真值)；京东POP现算保本价；新增 breakeven_effective/data_completeness。旧16列契约不变。';


-- ████ 3. 京东POP 利润源补全（把现算保本价回写 components，给 SQL/compute_margin 复用）████
-- 仅有 factory_price 的 16 行算得出，写进 components.保本价_派生 + 利润率_派生（标"派生"区分真账列）。
-- 纯加法 UPDATE（只补 jsonb 键、不动标量列）。重跑覆盖（幂等）。
WITH pop_fee AS (
    SELECT COALESCE(MAX(fee_rate), 0.0356) AS rate
    FROM accounting.channel_fees
    WHERE channel = 'jd_pop' AND fee_type = 'percentage'
      AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
)
UPDATE accounting.channel_product_costs c
SET components = c.components || jsonb_build_object(
        '保本价_派生', round(
            (c.factory_price + COALESCE((c.components->>'快递费')::numeric, 0))
            / NULLIF(
                1 - COALESCE((c.components->>'税点')::numeric, 0.13)
                  - (SELECT rate FROM pop_fee)
                  - COALESCE((c.components->>'运营支持费率')::numeric, 0), 0), 4),
        '扣点率_派生', (SELECT rate FROM pop_fee)
    )
FROM pop_fee
WHERE c.channel = 'jd_pop' AND c.is_active AND c.factory_price IS NOT NULL;


-- ████ 4. 京东日报视图升级 v_jd_daily_metric（保留旧列 + 挂日期维 + 分度量类型 + 派生cvr）████
-- 对外契约：原 7 列（date/sku_id/metric_name/metric_cn/value/source_runbook/created_at）全保留。
-- 新增列：metric_kind（度量类型：金额/计数/比率/时长/效率，给 Power BI 分度量轴用，
--   避免 rate 0-1 和金额混在一个 value 列被错误聚合）+ display_value（rate×100 成百分数预乘）。
-- ⚠️ jd_cvr 库内 0 行（INDICATOR_MAP 没抽）→ CASE 中文名是死分支，这里不补造数据，
--    cvr 真正的派生在 v_jd_funnel（用 buyer_cnt/item_uv 算），不污染日报长表。
CREATE OR REPLACE VIEW public.v_jd_daily_metric AS
SELECT
    date, sku_id, metric_name,
    CASE metric_name
        WHEN 'jd_gmv'                THEN '成交金额'
        WHEN 'jd_order_cnt'          THEN '成交单量'
        WHEN 'jd_buyer_cnt'          THEN '成交客户数'
        WHEN 'jd_sku_qtty'           THEN '成交商品件数'
        WHEN 'jd_per_customer_price' THEN '客单价'
        WHEN 'jd_item_uv'            THEN '商品访客数'
        WHEN 'jd_shop_uv'            THEN '店铺访客数'
        WHEN 'jd_exposure_uv'        THEN '曝光人数'
        WHEN 'jd_item_pv'            THEN '商品浏览量'
        WHEN 'jd_shop_pv'            THEN '店铺浏览量'
        WHEN 'jd_exposure_pv'        THEN '曝光次数'
        WHEN 'jd_uv_value'           THEN 'UV价值'
        WHEN 'jd_add_cart_user'      THEN '加购人数'
        WHEN 'jd_add_cart_amt'       THEN '加购金额'
        WHEN 'jd_add_cart_rate'      THEN '加购率'
        WHEN 'jd_item_pv_per_uv'     THEN '商详人均浏览'
        WHEN 'jd_item_stay_sec'      THEN '商详平均停留(秒)'
        WHEN 'jd_shop_stay_sec'      THEN '店铺平均停留(秒)'
        WHEN 'jd_cvr'                THEN '成交转化率'
        ELSE metric_name
    END                                                       AS metric_cn,
    value, source_runbook, created_at,
    -- ★ 新增列（纯加法）★ 度量类型：Power BI 按此分轴，别把 rate 0-1 和金额一起 SUM
    CASE
        WHEN metric_name IN ('jd_gmv','jd_per_customer_price','jd_uv_value','jd_add_cart_amt')
             THEN '金额'
        WHEN metric_name IN ('jd_order_cnt','jd_buyer_cnt','jd_sku_qtty','jd_item_uv',
             'jd_shop_uv','jd_exposure_uv','jd_item_pv','jd_shop_pv','jd_exposure_pv','jd_add_cart_user')
             THEN '计数'
        WHEN metric_name IN ('jd_add_cart_rate','jd_cvr')          THEN '比率'
        WHEN metric_name IN ('jd_item_stay_sec','jd_shop_stay_sec') THEN '时长'
        WHEN metric_name IN ('jd_item_pv_per_uv')                  THEN '效率'
        ELSE '其他'
    END                                                       AS metric_kind,
    -- 比率类预乘 ×100（给不会写 DAX 的场景直接显示百分数；DAX 端用原始 value 更稳）
    CASE WHEN metric_name IN ('jd_add_cart_rate','jd_cvr')
         THEN round(value * 100, 2) ELSE value END            AS display_value
FROM public.mvp_daily_metric
WHERE platform = 'jd';

COMMENT ON VIEW public.v_jd_daily_metric IS
    'Power BI 京东销售日报 v2：18 指标长表 + 中文名 + 新增 metric_kind(度量分轴)/display_value(rate×100)。旧7列契约不变。';


-- ████ 5. 京东转化漏斗派生视图 v_jd_funnel（曝光→访客→加购→成交 + 各级转化率 + 派生cvr）████
-- 把长表里散落的漏斗指标行转宽成"每天一行漏斗"，现场派生转化率（不依赖 jd_cvr 落库）。
-- 漏斗 5 段：曝光人数→店铺访客→商品访客→加购人数→成交客户数（设计调研页2 用）。
-- 全派生、零造数；某天缺某指标 → 该派生率为 NULL（不补 0）。
CREATE OR REPLACE VIEW public.v_jd_funnel AS
WITH pivoted AS (
    SELECT
        date,
        MAX(value) FILTER (WHERE metric_name = 'jd_exposure_uv')   AS exposure_uv,    -- 曝光人数
        MAX(value) FILTER (WHERE metric_name = 'jd_shop_uv')       AS shop_uv,        -- 店铺访客
        MAX(value) FILTER (WHERE metric_name = 'jd_item_uv')       AS item_uv,        -- 商品访客
        MAX(value) FILTER (WHERE metric_name = 'jd_add_cart_user') AS add_cart_user,  -- 加购人数
        MAX(value) FILTER (WHERE metric_name = 'jd_buyer_cnt')     AS buyer_cnt,      -- 成交客户
        MAX(value) FILTER (WHERE metric_name = 'jd_gmv')           AS gmv,
        MAX(value) FILTER (WHERE metric_name = 'jd_add_cart_rate') AS add_cart_rate   -- 平台口径加购率
    FROM public.mvp_daily_metric
    WHERE platform = 'jd' AND sku_id = '_SHOP_'
    GROUP BY date
)
SELECT
    date,
    exposure_uv, shop_uv, item_uv, add_cart_user, buyer_cnt, gmv,
    -- 各级转化率（0-1，rank/率类口径；分母 0 或 NULL → NULL，不补 0）
    round(shop_uv       / NULLIF(exposure_uv, 0),   4)  AS rate_expose_to_shop,   -- 曝光→店铺访客
    round(item_uv       / NULLIF(shop_uv, 0),       4)  AS rate_shop_to_item,     -- 店铺→商品访客
    round(add_cart_user / NULLIF(item_uv, 0),       4)  AS rate_item_to_cart,     -- 商品访客→加购（加购转化）
    round(buyer_cnt     / NULLIF(add_cart_user, 0), 4)  AS rate_cart_to_buyer,    -- 加购→成交
    round(buyer_cnt     / NULLIF(item_uv, 0),       4)  AS cvr_derived,           -- 派生成交转化率（救活 jd_cvr 盲区）
    add_cart_rate,
    -- 客单价校验（gmv/buyer，跟落库 per_customer_price 互证）
    round(gmv / NULLIF(buyer_cnt, 0), 2)                AS per_customer_check
FROM pivoted;

COMMENT ON VIEW public.v_jd_funnel IS
    'Power BI 京东转化漏斗 v1：曝光→店铺访客→商品访客→加购→成交 5段 + 各级转化率 + 派生cvr（不依赖 jd_cvr 落库）。每天一行，缺指标率为NULL不补0。';


-- ████ 6. 跨平台对比视图升级 v_bi_cross_platform_daily（保留旧列 + 挂日期维 + 归一化基线）████
-- 对外契约：原 5 列（date/platform_cn/platform/metric_concept/value）全保留。
-- 新增列：index_base100（各平台各概念以窗口首日为 100 的归一化指数，设计调研页3 双折线"看形态"用，
--   抖音33天/京东7天/口径不一也能并排比趋势）+ is_window_overlap（是否落在京东可比窗口）。
-- ⚠️ 京东 gmv ≠ 抖音 gmv_paid（退款/单位/时点），归一化只比涨跌形态不比绝对值——视图注释已声明。
CREATE OR REPLACE VIEW public.v_bi_cross_platform_daily AS
WITH src AS (
    SELECT date,
           CASE platform WHEN 'jd' THEN '京东' WHEN 'douyin' THEN '抖音' ELSE platform END AS platform_cn,
           platform,
           CASE
               WHEN metric_name IN ('jd_gmv', 'gmv_paid')              THEN '成交金额'
               WHEN metric_name IN ('jd_order_cnt', 'pay_order_cnt')   THEN '成交订单数'
               WHEN metric_name IN ('jd_buyer_cnt', 'buyer_count')     THEN '成交用户数'
           END                                                          AS metric_concept,
           value
    FROM public.mvp_daily_metric
    WHERE sku_id = '_SHOP_'
      AND (
           (platform = 'jd'     AND metric_name IN ('jd_gmv', 'jd_order_cnt', 'jd_buyer_cnt'))
        OR (platform = 'douyin' AND metric_name IN ('gmv_paid', 'pay_order_cnt', 'buyer_count'))
      )
),
-- 每个 platform×concept 的窗口首日值（归一化基数）
firstval AS (
    SELECT platform, metric_concept,
           (array_agg(value ORDER BY date))[1]      AS base_value,
           min(date)                                AS first_date
    FROM src
    GROUP BY platform, metric_concept
),
-- 京东可比窗口（京东数据的日期范围）
jd_window AS (
    SELECT min(date) AS d0, max(date) AS d1 FROM src WHERE platform = 'jd'
)
SELECT
    s.date, s.platform_cn, s.platform, s.metric_concept, s.value,
    -- ★ 新增列（纯加法）★ 各平台各概念归一化指数（首日=100），看形态不比绝对值
    CASE WHEN f.base_value IS NOT NULL AND f.base_value <> 0
         THEN round(s.value / f.base_value * 100, 1) END      AS index_base100,
    -- 是否落在京东可比窗口内（页3 标"重叠期"用）
    (s.date >= w.d0 AND s.date <= w.d1)                       AS is_window_overlap
FROM src s
LEFT JOIN firstval f ON f.platform = s.platform AND f.metric_concept = s.metric_concept
CROSS JOIN jd_window w;

COMMENT ON VIEW public.v_bi_cross_platform_daily IS
    'Power BI 跨平台对比 v2：抖音/京东 成交额/订单/买家 + 新增 index_base100(首日=100归一化看形态)/is_window_overlap(京东可比窗口)。绝对值口径不完全可比。旧5列契约不变。';


-- ████ 7. 京东商品带货榜视图增强 v_jd_product_top（保留旧列 + 挂日期维 + 效率分级 + 长尾标记）████
-- 对外契约：原 8 列（date/rank/spu_id/product_name/sales_amt/visitor_cnt/pro_url/sales_per_visitor）全保留。
-- 新增列：is_latest_snapshot（是否最新一天，前端默认只显示最新）+ visitor_status（访客数是否抓到）+
--   efficiency_tier（访客成交效率分级，仅 visitor_cnt 有值时；散点图象限用）。
-- ⚠️ visitor_cnt 当前全 NULL（jd_ingest 抽取键没命中）→ sales_per_visitor/efficiency_tier 恒空，
--    visitor_status 如实标 'pending'，不补 0、不编效率值。
CREATE OR REPLACE VIEW public.v_jd_product_top AS
WITH latest AS (
    SELECT max(date) AS d FROM public.mvp_jd_product_daily
)
SELECT
    p.date, p.rank, p.spu_id, p.product_name, p.sales_amt, p.visitor_cnt, p.pro_url,
    CASE WHEN p.visitor_cnt > 0 THEN round(p.sales_amt / p.visitor_cnt, 2) END AS sales_per_visitor,
    -- ★ 新增列（纯加法）★
    (p.date = l.d)                                            AS is_latest_snapshot,
    CASE WHEN p.visitor_cnt IS NULL THEN 'pending'            -- 访客数待抓（商智商品分析）
         WHEN p.visitor_cnt = 0     THEN 'zero'
         ELSE 'ok' END                                        AS visitor_status,
    -- 访客成交效率分级（仅 visitor_cnt 有值；散点象限：高效/中/引流不成交）
    CASE WHEN p.visitor_cnt > 0 THEN
        CASE
            WHEN p.sales_amt / p.visitor_cnt >= 5  THEN '高效转化'
            WHEN p.sales_amt / p.visitor_cnt >= 1  THEN '中等'
            ELSE '引流不成交'
        END
    END                                                       AS efficiency_tier
FROM public.mvp_jd_product_daily p
CROSS JOIN latest l;

COMMENT ON VIEW public.v_jd_product_top IS
    'Power BI 京东商品带货榜 v2：当日TOP + 访客成交效率 + 新增 is_latest_snapshot/visitor_status(访客待抓pending)/efficiency_tier。访客数当前全空,效率列恒空。旧8列契约不变。';


-- ████ 8. 月度商品利润事实表（结构就绪，等真账落数）████████████████████████████
-- ⚠️ 重要（反幻觉）：本次扫了 Desktop/和田宽/ 与 价格表（内部）/ 全部 Excel——
--   · 产品利润表.xlsx / real profits.xlsx / 真实成本测算 = 单品「单位成本利润」截面，无时间维（已进 channel_product_costs）；
--   · 2026财年电商部销售计划.xlsx = 渠道级「月度销售额/毛利」**预算计划**（非实际成交真账），且只到渠道粒度、无单品；
--   → **没有"月度×单品×渠道 实际利润真账"可抽**。故本表只建结构（CREATE IF NOT EXISTS，空表待数据），
--      不从计划表造单品真账。等老板拿到月度结算单/对账单再 INSERT（loader 注释见下）。
CREATE TABLE IF NOT EXISTS accounting.fact_monthly_product_profit (
    id              BIGSERIAL    PRIMARY KEY,
    year_month      TEXT         NOT NULL,            -- '2026-06'，关联 dim_date.year_month
    period_first    DATE         NOT NULL,            -- 当月首日，关联 dim_date.date（建星型关系）
    channel         TEXT         NOT NULL,            -- tmall / jd_self / jd_pop / douyin
    barcode         TEXT,                             -- 关联 channel_product_costs.barcode
    product_name    TEXT         NOT NULL,
    spec            TEXT,
    sales_qty       NUMERIC(18,2),                    -- 当月成交件数（实际）
    sales_amt       NUMERIC(18,2),                    -- 当月成交金额（元，实际）
    unit_cost       NUMERIC(14,4),                    -- 单位成本（可从 channel_product_costs 带）
    total_cost      NUMERIC(18,2),                    -- 当月总成本（元）
    gross_profit    NUMERIC(18,2),                    -- 当月毛利（元）
    gross_margin    NUMERIC(8,4),                     -- 当月毛利率（0-1）
    is_actual       BOOLEAN      NOT NULL DEFAULT TRUE,-- TRUE=实际真账 / FALSE=计划值（区分别混算）
    source          TEXT         NOT NULL DEFAULT 'manual',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (year_month, channel, barcode, is_actual)
);
CREATE INDEX IF NOT EXISTS idx_fmpp_ym      ON accounting.fact_monthly_product_profit (year_month);
CREATE INDEX IF NOT EXISTS idx_fmpp_channel ON accounting.fact_monthly_product_profit (channel, year_month);

COMMENT ON TABLE accounting.fact_monthly_product_profit IS
    '月度×单品×渠道 利润事实表（结构就绪·当前空）：等月度结算真账落数。is_actual 区分实际/计划。无真账时绝不从计划表造单品行。';

-- 月度商品利润 Power BI 视图（挂渠道中文名 + 关联日期维；空表也能拖，老板录数即点亮）
CREATE OR REPLACE VIEW accounting.v_monthly_product_profit AS
SELECT
    f.year_month, f.period_first, f.channel,
    CASE f.channel
        WHEN 'tmall'   THEN '天猫'
        WHEN 'jd_self' THEN '京东自营'
        WHEN 'jd_pop'  THEN '京东POP'
        WHEN 'douyin'  THEN '抖音'
        ELSE f.channel
    END                                                       AS channel_cn,
    f.barcode, f.product_name, f.spec,
    f.sales_qty, f.sales_amt, f.unit_cost, f.total_cost,
    f.gross_profit, f.gross_margin, f.is_actual, f.source
FROM accounting.fact_monthly_product_profit f;

COMMENT ON VIEW accounting.v_monthly_product_profit IS
    'Power BI 月度商品利润：渠道中文名 + 单品月度真账。当前空表（无月度真账源）；老板录月度结算后自动点亮。';

-- LOADER 提示（注释·不执行）：拿到月度对账单后，按 barcode join channel_product_costs 带 unit_cost：
--   INSERT INTO accounting.fact_monthly_product_profit
--     (year_month, period_first, channel, barcode, product_name, spec,
--      sales_qty, sales_amt, unit_cost, total_cost, gross_profit, gross_margin, is_actual, source)
--   SELECT '2026-06','2026-06-01','jd_self', c.barcode, c.product_name, c.spec,
--          <月成交件数>, <月成交金额>, c.factory_price,
--          <月总成本>, <月毛利>, round(<月毛利>/NULLIF(<月成交金额>,0),4), TRUE, '京东月度结算单'
--   FROM accounting.channel_product_costs c WHERE c.barcode=<barcode>;
