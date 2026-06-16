-- Migration 057: 京东商品维度日榜（切片4 SKU 维度）
--
-- 商品 TOP 是 per-商品快照（spu_id + 商品名 + 引入成交额 + 访客数 + rank），宽表，
-- 不进 mvp_daily_metric（那是店级长表 _SHOP_）。京东 spu 不绑 mvp_sku（抖音形状），独立存。
-- 每天 passive 抓商智「商品分析/流量商品 TOP」→ upsert 当日榜（同 date+spu 覆盖）。

CREATE TABLE IF NOT EXISTS public.mvp_jd_product_daily (
    id            BIGSERIAL PRIMARY KEY,
    date          DATE        NOT NULL,
    spu_id        VARCHAR(64) NOT NULL,         -- 京东 SPU ID（item.jd.com/<spu>.html）
    product_name  TEXT,
    sales_amt     NUMERIC(20, 6),               -- 引入成交金额
    visitor_cnt   NUMERIC(20, 6),               -- 商品访客数(UV)
    rank          SMALLINT,                     -- 当日榜内名次
    pro_url       TEXT,
    source_runbook VARCHAR(128),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (date, spu_id)
);
CREATE INDEX IF NOT EXISTS idx_jd_product_daily_date ON public.mvp_jd_product_daily (date DESC);
CREATE INDEX IF NOT EXISTS idx_jd_product_daily_spu  ON public.mvp_jd_product_daily (spu_id, date DESC);

COMMENT ON TABLE public.mvp_jd_product_daily IS
    '京东商品日榜（切片4）：每日商品 TOP 快照，spu_id+名+引入成交额+访客+rank。京东 spu 独立、不绑 mvp_sku。';

-- Power BI 京东商品带货榜视图（直接拖：rank/商品名/成交额/访客数 + 算转化代理）
CREATE OR REPLACE VIEW public.v_jd_product_top AS
SELECT date, rank, spu_id, product_name, sales_amt, visitor_cnt, pro_url,
       CASE WHEN visitor_cnt > 0 THEN round(sales_amt / visitor_cnt, 2) END AS sales_per_visitor
FROM public.mvp_jd_product_daily;

COMMENT ON VIEW public.v_jd_product_top IS 'Power BI 京东商品带货榜：当日商品 TOP + 访客成交效率';
