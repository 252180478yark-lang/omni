-- Migration 061: 京东月度商品利润真账（6 个月真实成交/成本/毛利 + 店铺月度盈亏）
--
-- 数据源：F:\和田宽电商\京东+淘宝月报\<月>\京东N月销售商品成本与毛利.xls(x)
--   （7/8/9/11/12月=2025，1月=2026；和田宽京东 POP 自营店月度结算单）。
-- 抽取器 .pbi-work/load_jd_monthly.py → CSV → \copy 载入（静态历史，重载先 TRUNCATE）。
-- 口径：金额=元；毛利额=成交金额−总成本（总成本含出厂/服务费/佣金/快递/包材，不含推广）；
--   店铺净利=Σ毛利−月度总推广费；gross/net_margin 存 0-1。
-- 价值：补上「月度真实利润趋势」——比 v_channel_product_margin 的单品单位成本截面更全更准，
--   且揭示 6 个月全部净亏（推广费>毛利）的经营真相。挂 dim_date.period_first 做时间维。

-- ████ 1. 每商品月度利润真账 ████
CREATE TABLE IF NOT EXISTS accounting.jd_monthly_product_profit (
    id                  BIGSERIAL PRIMARY KEY,
    year_month          TEXT        NOT NULL,        -- '2025-11' 关联 dim_date.year_month
    period_first        DATE        NOT NULL,        -- 当月首日 关联 dim_date.date
    jd_product_id       TEXT,                        -- 京东商品ID（item.jd.com/<id>.html）
    product_name        TEXT        NOT NULL,
    sales_qty           NUMERIC(18,2),               -- 成交件数
    sales_amt           NUMERIC(18,2),               -- 成交金额(元)
    unit_purchase_cost  NUMERIC(14,4),               -- 出厂成本(元/件)
    total_cost          NUMERIC(18,4),               -- 总成本(元，含服务费/佣金/快递/包材)
    gross_profit        NUMERIC(18,4),               -- 毛利额(元)=成交金额−总成本(不含推广)
    gross_margin        NUMERIC(8,4),                -- 毛利率 0-1
    source              TEXT        NOT NULL DEFAULT 'jd_monthly_report',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (year_month, jd_product_id)
);
CREATE INDEX IF NOT EXISTS idx_jmpp_ym  ON accounting.jd_monthly_product_profit (year_month);
CREATE INDEX IF NOT EXISTS idx_jmpp_pid ON accounting.jd_monthly_product_profit (jd_product_id);
COMMENT ON TABLE accounting.jd_monthly_product_profit IS
    '京东月度商品利润真账（6个月，源京东月度结算单）：月×商品 成交/成本/毛利。毛利不含推广费。';

-- ████ 2. 店铺月度盈亏（毛利−推广=净利，老板「这月赚没赚」一眼看） ████
CREATE TABLE IF NOT EXISTS accounting.jd_monthly_shop_pnl (
    year_month     TEXT        PRIMARY KEY,          -- '2025-11'
    period_first   DATE        NOT NULL,
    gmv            NUMERIC(18,2),                    -- 当月成交金额合计(元)
    total_cost     NUMERIC(18,2),                    -- 当月总成本合计(元)
    gross_profit   NUMERIC(18,2),                    -- 当月毛利合计(元)
    promo_fee      NUMERIC(18,2),                    -- 当月总推广费(元)
    net_profit     NUMERIC(18,2),                    -- 当月净利=毛利−推广(元)
    product_count  INTEGER,
    source         TEXT        NOT NULL DEFAULT 'jd_monthly_report',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE accounting.jd_monthly_shop_pnl IS
    '京东店铺月度盈亏：GMV/成本/毛利/推广/净利。净利=毛利−推广，6个月全负=推广费>毛利。';

-- ████ 3. Power BI 视图（挂 dim_date 时间维 + 派生率） ████
CREATE OR REPLACE VIEW public.v_jd_monthly_profit AS
SELECT p.year_month, p.period_first, d.month_cn, d.quarter_cn,
       p.jd_product_id, p.product_name, p.sales_qty, p.sales_amt,
       p.unit_purchase_cost, p.total_cost, p.gross_profit, p.gross_margin,
       'https://item.jd.com/' || p.jd_product_id || '.html' AS product_url
FROM accounting.jd_monthly_product_profit p
LEFT JOIN public.dim_date d ON d.date = p.period_first;
COMMENT ON VIEW public.v_jd_monthly_profit IS
    'Power BI 京东月度商品利润：月×商品真实毛利+月名/季+商品链接。挂 dim_date。';

CREATE OR REPLACE VIEW public.v_jd_monthly_pnl AS
SELECT s.year_month, s.period_first, d.month_cn, d.quarter_cn,
       s.gmv, s.total_cost, s.gross_profit, s.promo_fee, s.net_profit, s.product_count,
       round(s.gross_profit / NULLIF(s.gmv,0), 4) AS gross_margin,   -- 毛利率
       round(s.net_profit   / NULLIF(s.gmv,0), 4) AS net_margin,     -- 净利率(负=亏)
       round(s.promo_fee    / NULLIF(s.gross_profit,0), 4) AS promo_to_gp_ratio, -- 推广吃掉几倍毛利
       (s.net_profit >= 0) AS is_profitable
FROM accounting.jd_monthly_shop_pnl s
LEFT JOIN public.dim_date d ON d.date = s.period_first;
COMMENT ON VIEW public.v_jd_monthly_pnl IS
    'Power BI 京东店铺月度盈亏：净利/净利率/推广吃毛利倍数/是否盈利。揭示推广费>毛利的亏损结构。';
