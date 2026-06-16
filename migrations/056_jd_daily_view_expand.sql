-- Migration 056: v_jd_daily_metric 视图 CASE 扩到全部京东指标中文名（铺次级指标）
-- 配合 jd_ingest.INDICATOR_MAP 18 指标 + metric_registry。口径：cnt=访客数(UV)、qtty=浏览量(PV)。
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
    END                     AS metric_cn,
    value, source_runbook, created_at
FROM public.mvp_daily_metric
WHERE platform = 'jd';
