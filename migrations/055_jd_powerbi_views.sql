-- Migration 055: Power BI 数据层视图（京东接入切片 Q/3）
--
-- Power BI Desktop（Import 模式）直连 postgres 读这几个视图——不直读裸表，
-- 视图做好渠道中文名/毛利计算/指标中文名/跨平台口径映射，Power Query 少点几十下。
-- 老板手动：装 Power BI Desktop → PostgreSQL connector → localhost:5432 / omni_vibe_db /
--   omni_user 直连 → Import 模式 → 选下面三个视图建报表（连接+报表指南见 docs/）。

-- ① 三渠道利润测算（切片 Q 第一天就能看的静态报表）：天猫/京东自营/京东POP 出厂价→保本价→标价→实际售价→毛利。
--    components（各渠道特有成本项：快递费/税点/费率/毛保/推广费…）原样带出，Power Query 可按需展开。
CREATE OR REPLACE VIEW accounting.v_channel_product_margin AS
SELECT
    channel,
    CASE channel
        WHEN 'tmall'   THEN '天猫'
        WHEN 'jd_self' THEN '京东自营'
        WHEN 'jd_pop'  THEN '京东POP'
        ELSE channel
    END                                                   AS channel_cn,
    barcode, product_name, category, grade, spec, qty,
    factory_price, breakeven_price, list_price, actual_price,
    (actual_price - breakeven_price)                      AS gross_profit,   -- 保本价含全部成本 → 实际售价-保本价=单位毛利
    CASE WHEN actual_price > 0
         THEN round((actual_price - breakeven_price) / actual_price, 4)
    END                                                   AS gross_margin,    -- 毛利率
    components                                            AS cost_components, -- 原始 jsonb（渠道特有成本项）
    source
FROM accounting.channel_product_costs
WHERE is_active;

COMMENT ON VIEW accounting.v_channel_product_margin IS
    'Power BI 三渠道利润测算（tmall/jd_self/jd_pop）：标量利润链 + 毛利/毛利率 + 原始成本组件 jsonb';

-- ② 京东日级指标长表（切片 3 京东销售日报）：mvp_daily_metric platform='jd' + 指标中文名。
--    长表直读（date × metric × value），Power BI 自己透视，**不行转宽**（长表是 Power BI 舒适区）。
CREATE OR REPLACE VIEW public.v_jd_daily_metric AS
SELECT
    date, sku_id, metric_name,
    CASE metric_name
        WHEN 'jd_gmv'       THEN '成交金额'
        WHEN 'jd_order_cnt' THEN '成交订单数'
        WHEN 'jd_buyer_cnt' THEN '成交用户数'
        WHEN 'jd_sku_qtty'  THEN '成交件数'
        WHEN 'jd_item_pv'   THEN '商品浏览量'
        WHEN 'jd_shop_pv'   THEN '店铺浏览量'
        WHEN 'jd_exposure'  THEN '曝光量'
        WHEN 'jd_cvr'       THEN '成交转化率'
        ELSE metric_name
    END                     AS metric_cn,
    value, source_runbook, created_at
FROM public.mvp_daily_metric
WHERE platform = 'jd';

COMMENT ON VIEW public.v_jd_daily_metric IS
    'Power BI 京东销售日报：platform=jd 长表 + 指标中文名（date×metric×value，前端透视）';

-- ③ 跨平台核心指标对比（切片 3 第三页：抖音 vs 京东 同窗口）：把同义指标映射到统一口径名。
--    ⚠️ 口径提示：京东 gmv 与抖音 gmv_paid 口径不完全一致（退款/单位/时点），对比看趋势形态、别硬比绝对值。
CREATE OR REPLACE VIEW public.v_bi_cross_platform_daily AS
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
  );

COMMENT ON VIEW public.v_bi_cross_platform_daily IS
    'Power BI 跨平台对比：抖音/京东 成交额/订单/买家 统一口径名（看趋势形态，绝对值口径不完全可比）';
