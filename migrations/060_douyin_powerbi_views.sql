-- Migration 059: 抖店 Power BI 数据层（对标京东 055/056/057，做整套）
--
-- Power BI Desktop（Import 模式）直连 postgres 读这些视图——不直读裸表。
-- 抖店原始数据比京东丰富（店级长表 90+ 指标 + per-SKU 商品 + 达人/爆品/直播/价格带/
-- 搜索词/竞品 7 张榜单 + 同行标杆），这里一次铺成一整套 v_douyin_* 视图。
--
-- 设计要点：
--   * 维度模型：mvp_metric_dim（指标维表：中文名/单位/方向/分类）让 Power BI 按
--     「流量/转化/成交/人群5A/搜索/体验服务/排名/品牌心智/…」分类切片 + 按 direction
--     做红绿条件格式。维表由 scripts/seed_metric_dim.py 从 metric_registry.py 投影
--     （单一来源，零手抄、零漂移）。
--   * 长表直读（date×metric×value），Power BI 自己透视，不行转宽（长表是 Power BI 舒适区）。
--   * 店级（_SHOP_）与 per-SKU 分两个视图，避免在同一指标里混店级/商品级被误 SUM。
--   * 口径已在落库层固定（金额=元、rate 0-1、rank 越小越好），Power BI 端不做换算。
--
-- 老板手动：装 Power BI Desktop → PostgreSQL connector → localhost:5432 / omni_vibe_db /
--   omni_user 直连 → Import 模式 → 选 v_douyin_* 视图建报表（连接+报表指南见 docs/）。

-- ───────────────────────────────────────────────────────────────────────────
-- 0. 指标维表（星型模型的 dim；fact = mvp_daily_metric）
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.mvp_metric_dim (
    metric_name VARCHAR(64) PRIMARY KEY,        -- 与 mvp_daily_metric.metric_name 关联（jd_ 前缀不撞抖音名）
    platform    VARCHAR(16) NOT NULL DEFAULT 'douyin',
    metric_cn   TEXT,                           -- 中文名（来源 metric_registry.cn）
    unit        VARCHAR(16),                    -- 元/人/单/比率/分/名/条/次…
    direction   VARCHAR(16),                    -- up_good / down_good / neutral（Power BI 红绿条件格式用）
    category    VARCHAR(32)                     -- 流量/转化/成交/人群5A/搜索/体验服务/排名/品牌心智/货品结构/投放/达人/商品榜/商品卡/直播/履约售后/其他
);
COMMENT ON TABLE public.mvp_metric_dim IS
    'Power BI 指标维表：metric_name → 中文名/单位/方向/分类。由 scripts/seed_metric_dim.py 从 metric_registry.py 投影（单一来源，重跑幂等）。';

-- ───────────────────────────────────────────────────────────────────────────
-- 1. 店级日报长表（90+ 指标 × date × value + 维度），对标 v_jd_daily_metric
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_daily_metric AS
SELECT
    m.date,
    m.metric_name,
    COALESCE(d.metric_cn, m.metric_name) AS metric_cn,
    d.category,
    d.unit,
    d.direction,
    m.value
FROM public.mvp_daily_metric m
LEFT JOIN public.mvp_metric_dim d ON d.metric_name = m.metric_name
WHERE m.platform = 'douyin'
  AND m.sku_id = '_SHOP_';

COMMENT ON VIEW public.v_douyin_daily_metric IS
    'Power BI 抖店店级日报：platform=douyin 全店(_SHOP_)长表 + 指标维度（中文名/分类/方向）。date×metric×value 前端透视。';

-- ───────────────────────────────────────────────────────────────────────────
-- 2. 商品带货榜（per-SKU 宽表，JOIN mvp_sku 拿真实商品名），对标 v_jd_product_top
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_product_top AS
SELECT
    m.date,
    m.sku_id,
    s.name      AS product_name,
    s.category  AS sku_category,
    s.status    AS sku_status,
    s.price_min,
    s.price_max,
    MAX(m.value) FILTER (WHERE m.metric_name = 'gmv_paid')           AS gmv_paid,
    MAX(m.value) FILTER (WHERE m.metric_name = 'gmv_net')            AS gmv_net,
    MAX(m.value) FILTER (WHERE m.metric_name = 'gmv_paid_wow_ratio') AS gmv_wow_ratio
FROM public.mvp_daily_metric m
LEFT JOIN public.mvp_sku s ON s.id = m.sku_id
WHERE m.platform = 'douyin'
  AND m.sku_id <> '_SHOP_'
GROUP BY m.date, m.sku_id, s.name, s.category, s.status, s.price_min, s.price_max;

COMMENT ON VIEW public.v_douyin_product_top IS
    'Power BI 抖店商品带货榜：per-SKU 宽表（真实商品名 × 支付额/净额/环比），按 date 切片、gmv_paid 排序。';

-- ───────────────────────────────────────────────────────────────────────────
-- 3. 达人带货榜（长表透传，含昵称）
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_author_top AS
SELECT
    date,
    author_id,
    nickname,
    aweme_id,
    metric_name,
    value
FROM public.mvp_author_daily_metric
WHERE platform = 'douyin';

COMMENT ON VIEW public.v_douyin_author_top IS
    'Power BI 抖店达人带货榜：长表（达人昵称 × 指标 × 值），Power BI 透视/排序。';

-- ───────────────────────────────────────────────────────────────────────────
-- 4. 行业爆品榜（同行在卖啥）
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_bestseller AS
SELECT
    snapshot_date AS date,
    dimension,
    rank,
    spu_id,
    spu_name,
    display_price,
    category_l1,
    category_l2,
    category_l3,
    image_url
FROM public.mvp_industry_bestseller
WHERE platform = 'douyin';

COMMENT ON VIEW public.v_douyin_bestseller IS
    'Power BI 抖店行业爆品榜：同行畅销 SPU（名/价/类目/图），按 snapshot_date + dimension 切片。';

-- ───────────────────────────────────────────────────────────────────────────
-- 5. 直播间带货榜
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_live_top AS
SELECT
    date,
    rank,
    author_name,
    live_pay_amt,
    live_pay_ratio
FROM public.mvp_live_room_rank
WHERE platform = 'douyin';

COMMENT ON VIEW public.v_douyin_live_top IS
    'Power BI 抖店直播间带货榜：直播间支付额/占比，按 date 切片。';

-- ───────────────────────────────────────────────────────────────────────────
-- 6. 价格带分布（你在哪档、主力价格带是哪档）
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_price_band AS
SELECT
    date,
    band_label,
    rank,
    product_id,
    product_name,
    product_image_url,
    gmv_lower_yuan,
    gmv_upper_yuan,
    addable
FROM public.mvp_price_band_product
WHERE platform = 'douyin';

COMMENT ON VIEW public.v_douyin_price_band IS
    'Power BI 抖店价格带分布：各价格带畅销品 + GMV 区间（脱敏上下界），看主力价格带。';

-- ───────────────────────────────────────────────────────────────────────────
-- 7. 搜索词榜（用户搜啥进来）
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_search_words AS
SELECT
    keyword,
    stat_date_start,
    stat_date_end,
    rank,
    pay_amt,
    product_show_ucnt,
    prod_show_click_ratio,
    prod_click_pay_ratio
FROM public.mvp_search_keyword_rank
WHERE platform = 'douyin';

COMMENT ON VIEW public.v_douyin_search_words IS
    'Power BI 抖店搜索词榜：关键词 × 支付额/曝光人数/点击率/转化率，按时间窗切片。';

-- ───────────────────────────────────────────────────────────────────────────
-- 8. 竞品成交区间（同行竞品脱敏成交带）
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_compete AS
SELECT
    date,
    rank,
    comp_product_id,
    comp_name,
    pay_amt_lower,
    pay_amt_upper,
    pay_ucnt
FROM public.mvp_compete_product
WHERE platform = 'douyin';

COMMENT ON VIEW public.v_douyin_compete IS
    'Power BI 抖店竞品成交区间：竞品名 + 脱敏支付额上下界 + 支付人数，按 date 切片。';

-- ───────────────────────────────────────────────────────────────────────────
-- 9. 你 vs 同行（同行标杆）
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_douyin_industry_benchmark AS
SELECT
    b.date,
    b.metric_name,
    COALESCE(d.metric_cn, b.metric_name) AS metric_cn,
    d.category,
    d.unit,
    b.industry_avg,
    b.industry_top,
    b.shop_value,
    b.percentile,
    b.industry_rank
FROM public.mvp_industry_benchmark b
LEFT JOIN public.mvp_metric_dim d ON d.metric_name = b.metric_name
WHERE b.category_id = '14';   -- 调味品行业（抖音生态"你 vs 同行"）

COMMENT ON VIEW public.v_douyin_industry_benchmark IS
    'Power BI 抖店你 vs 同行：同行均值/TOP/你的值/分位/排名（category_id=14 调味品）。';

-- ───────────────────────────────────────────────────────────────────────────
-- 10. 跨平台对比（抖音 vs 京东，055 的扩展版：5 个核心同义口径）
-- ───────────────────────────────────────────────────────────────────────────
-- DROP+CREATE（不是 OR REPLACE）：055 旧版列集不同，OR REPLACE 不允许改列集。
DROP VIEW IF EXISTS public.v_bi_cross_platform_daily;
CREATE VIEW public.v_bi_cross_platform_daily AS
SELECT
    date,
    CASE platform WHEN 'jd' THEN '京东' WHEN 'douyin' THEN '抖音' ELSE platform END AS platform_cn,
    platform,
    CASE
        WHEN metric_name IN ('jd_gmv', 'gmv_paid')                         THEN '成交金额'
        WHEN metric_name IN ('jd_order_cnt', 'pay_order_cnt')              THEN '成交订单数'
        WHEN metric_name IN ('jd_buyer_cnt', 'buyer_count')               THEN '成交用户数'
        WHEN metric_name IN ('jd_cvr', 'pay_conversion')                  THEN '成交转化率'
        WHEN metric_name IN ('jd_per_customer_price', 'per_customer_price') THEN '客单价'
    END AS metric_concept,
    value
FROM public.mvp_daily_metric
WHERE sku_id = '_SHOP_'
  AND (
       (platform = 'jd'     AND metric_name IN ('jd_gmv','jd_order_cnt','jd_buyer_cnt','jd_cvr','jd_per_customer_price'))
    OR (platform = 'douyin' AND metric_name IN ('gmv_paid','pay_order_cnt','buyer_count','pay_conversion','per_customer_price'))
  );

COMMENT ON VIEW public.v_bi_cross_platform_daily IS
    'Power BI 跨平台对比：抖音/京东 成交额/订单/用户/转化率/客单价 统一口径名（看趋势形态，绝对值口径不完全可比）。';
