-- ============================================================================
-- Migration 063: 京东 BI 五路数据源汇总（流量来源/体验分/推广/货款结算/对标增强）
-- 纯加法：CREATE TABLE IF NOT EXISTS + CREATE OR REPLACE VIEW，零破坏现有 059/061/062。
-- 口径铁律（对齐 CLAUDE.md/059）：金额元；rate/占比存原始 0-1；体验分排名率/星级是平台
--   已算好的 0-100 / 0-5 原值（特例，不÷100）；rank 越小越好；缺数标缺不补 0 不编值。
-- mvp_daily_metric upsert 口径 ON CONFLICT(sku_id,date,metric_name,platform)（同 jd_ingest）。
-- 可直接 psql -f 063_jd_bi_consolidated.sql 执行。
-- ============================================================================


-- ████ 1. 流量来源结构日表 + 视图（切片5·最高价值新维度：流量从哪来、哪个渠道真带货）████
-- 源 szgateway flowSummary/productFlow/getFlowSrcTop.ajax。date×渠道宽表（长表装不下渠道维）。
-- channel_code 稳定主键（2008搜索/2005频道/3002我的京东/3001购物车），channel_name 冗余存防中文漂移。
CREATE TABLE IF NOT EXISTS public.mvp_jd_flow_source (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE        NOT NULL,
    channel_code    VARCHAR(16) NOT NULL,        -- 渠道 code（jdr_..._rmad_sz_2）
    channel_name    TEXT,                         -- 渠道中文名（响应 name）
    parent_name     TEXT,                         -- 父级场域（站内场域/站外/付费）
    rank            SMALLINT,                     -- 当日名次（按访客）
    visitor_cnt     NUMERIC(20,6),                -- 访客数 UV
    visitor_cnt_pre NUMERIC(20,6),                -- 访客数上期值（##compareValue）
    visitor_mom     NUMERIC(12,6),                -- 访客数环比 0-1（##compare）
    intro_gmv       NUMERIC(20,6),                -- 引入成交额 元
    intro_gmv_pre   NUMERIC(20,6),                -- 引入成交额上期值
    intro_gmv_mom   NUMERIC(12,6),                -- 引入成交额环比 0-1
    flow_share      NUMERIC(12,6),                -- 占流量比 0-1（customProportion 访客÷全店商品访客）
    gmv_share       NUMERIC(12,6),                -- 占成交比 0-1（customProportion 引入成交÷全店成交）
    source_runbook  VARCHAR(128) NOT NULL DEFAULT 'jd_passive_capture',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (date, channel_code)
);
CREATE INDEX IF NOT EXISTS idx_jd_flow_source_date ON public.mvp_jd_flow_source (date DESC);
CREATE INDEX IF NOT EXISTS idx_jd_flow_source_chan ON public.mvp_jd_flow_source (channel_code, date DESC);
COMMENT ON TABLE public.mvp_jd_flow_source IS
  '京东流量来源结构日表（切片5）：date×渠道 访客+引入成交+占流量比+占成交比+双环比。源 getFlowSrcTop.ajax。当日快照，趋势靠cron累积。';

CREATE OR REPLACE VIEW public.v_jd_flow_source AS
SELECT
    date, channel_code,
    channel_name                          AS 渠道,
    parent_name                           AS 场域,
    rank                                  AS 名次,
    visitor_cnt                           AS 访客数,
    visitor_mom                           AS 访客环比,
    intro_gmv                             AS 引入成交额,
    intro_gmv_mom                         AS 成交环比,
    flow_share                            AS 占流量比,
    gmv_share                             AS 占成交比,
    -- 单访客引入成交额（哪个渠道访客更值钱）
    CASE WHEN visitor_cnt > 0 THEN round(intro_gmv / visitor_cnt, 2) END AS 访客引入成交效率,
    -- 带货杠杆=占成交比÷占流量比 >1=带货效率高于全店均值，<1=只来人不下单
    CASE WHEN flow_share > 0 THEN round((gmv_share / flow_share)::numeric, 2) END AS 成交流量杠杆
FROM public.mvp_jd_flow_source;
COMMENT ON VIEW public.v_jd_flow_source IS
  '京东流量来源结构：渠道访客/引入成交/占比/双环比 + 访客引入效率 + 成交流量杠杆(>1高效带货)。';


-- ████ 2. 店铺体验分红线视图（切片·健康红线）████████████████████████████████████
-- 复用 mvp_daily_metric 长表（评分类 snap，jd_exp_ 前缀店级 _SHOP_，无新表）。
-- 阈值口径：单项分<8 红(处罚线)/<9 黄(预警)，行业经验值可调；排名率/星级是平台 0-100/0-5 原值。
-- 把散落的 jd_exp_* 行转「一天一行」宽表 + 派生 redline_status/weakest_dimension。
CREATE OR REPLACE VIEW public.v_jd_shop_experience AS
WITH latest AS (
    SELECT max(date) AS d FROM public.mvp_daily_metric
     WHERE platform='jd' AND metric_name LIKE 'jd_exp_%'
),
pivoted AS (
    SELECT
        date,
        MAX(value) FILTER (WHERE metric_name='jd_exp_consult_score')          AS consult_score,
        MAX(value) FILTER (WHERE metric_name='jd_exp_afterservice_score')     AS afterservice_score,
        MAX(value) FILTER (WHERE metric_name='jd_exp_logistics_score')        AS logistics_score,
        MAX(value) FILTER (WHERE metric_name='jd_exp_evaluate_score')         AS evaluate_score,
        MAX(value) FILTER (WHERE metric_name='jd_exp_score_rank_rate')        AS score_rank_rate,
        MAX(value) FILTER (WHERE metric_name='jd_exp_consult_rank_rate')      AS consult_rank_rate,
        MAX(value) FILTER (WHERE metric_name='jd_exp_afterservice_rank_rate') AS afterservice_rank_rate,
        MAX(value) FILTER (WHERE metric_name='jd_exp_logistics_rank_rate')    AS logistics_rank_rate,
        MAX(value) FILTER (WHERE metric_name='jd_exp_evaluate_rank_rate')     AS evaluate_rank_rate,
        MAX(value) FILTER (WHERE metric_name='jd_exp_score_grade')            AS score_grade,
        MAX(value) FILTER (WHERE metric_name='jd_exp_redgreen_pass')          AS redgreen_pass,
        MAX(value) FILTER (WHERE metric_name='jd_exp_valid_order_num')        AS valid_order_num
    FROM public.mvp_daily_metric
    WHERE platform='jd' AND sku_id='_SHOP_' AND metric_name LIKE 'jd_exp_%'
    GROUP BY date
)
SELECT
    p.date,
    p.consult_score, p.afterservice_score, p.logistics_score, p.evaluate_score,
    p.consult_rank_rate, p.afterservice_rank_rate, p.logistics_rank_rate, p.evaluate_rank_rate,
    p.score_rank_rate, p.score_grade, p.valid_order_num,
    (p.redgreen_pass = 1)                                                       AS is_redgreen_pass,
    LEAST(p.consult_score, p.afterservice_score, p.logistics_score, p.evaluate_score) AS min_score,
    CASE
        WHEN LEAST(p.consult_score,p.afterservice_score,p.logistics_score,p.evaluate_score) < 8 THEN 'red'
        WHEN LEAST(p.consult_score,p.afterservice_score,p.logistics_score,p.evaluate_score) < 9 THEN 'amber'
        ELSE 'green'
    END                                                                        AS redline_status,
    CASE LEAST(p.consult_score,p.afterservice_score,p.logistics_score,p.evaluate_score)
        WHEN p.logistics_score    THEN '物流履约'
        WHEN p.afterservice_score THEN '售后服务'
        WHEN p.evaluate_score     THEN '用户评价'
        WHEN p.consult_score      THEN '客服咨询'
    END                                                                        AS weakest_dimension,
    (p.date = l.d)                                                             AS is_latest
FROM pivoted p CROSS JOIN latest l;
COMMENT ON VIEW public.v_jd_shop_experience IS
  '京东店铺体验分红线 v1：四项体验分+各项排名率+综合排名率/星级+红绿灯+有效订单(样本量)+派生redline_status(分<8红/<9黄,经验阈值可调)/weakest_dimension。评分类snap每天一行。';


-- ████ 3. 推广效果视图（切片·京准通快车，现状停投全0）████████████████████████████
-- 复用 mvp_daily_metric 长表（jd_ad_ 前缀店级 _SHOP_，无新表）。
-- ad_status 三态诚实区分：active(花费>0) / paused(花费=0确认停投) / no_data(没抓到)。
CREATE OR REPLACE VIEW public.v_jd_ad_performance AS
WITH ad AS (
    SELECT date,
        MAX(value) FILTER (WHERE metric_name='jd_ad_cost')        AS ad_cost,
        MAX(value) FILTER (WHERE metric_name='jd_ad_order_sum')   AS ad_order_sum,
        MAX(value) FILTER (WHERE metric_name='jd_ad_roi')         AS ad_roi,
        MAX(value) FILTER (WHERE metric_name='jd_ad_impressions') AS ad_impressions,
        MAX(value) FILTER (WHERE metric_name='jd_ad_clicks')      AS ad_clicks,
        MAX(value) FILTER (WHERE metric_name='jd_ad_ctr')         AS ad_ctr,
        MAX(value) FILTER (WHERE metric_name='jd_ad_cpc')         AS ad_cpc,
        MAX(value) FILTER (WHERE metric_name='jd_ad_cpm')         AS ad_cpm,
        MAX(value) FILTER (WHERE metric_name='jd_ad_order_cnt')   AS ad_order_cnt
    FROM public.mvp_daily_metric
    WHERE platform='jd' AND sku_id='_SHOP_' AND metric_name LIKE 'jd_ad_%'
    GROUP BY date
),
gmv AS (
    SELECT date, MAX(value) FILTER (WHERE metric_name='jd_gmv') AS shop_gmv
    FROM public.mvp_daily_metric WHERE platform='jd' AND sku_id='_SHOP_' GROUP BY date
)
SELECT
    a.date,
    a.ad_cost, a.ad_order_sum, a.ad_roi, a.ad_impressions, a.ad_clicks,
    a.ad_ctr, a.ad_cpc, a.ad_cpm, a.ad_order_cnt, g.shop_gmv,
    round(a.ad_order_sum / NULLIF(g.shop_gmv,0), 4)    AS ad_order_share,
    round(a.ad_clicks / NULLIF(a.ad_impressions,0), 4) AS ctr_derived,
    CASE
        WHEN a.ad_cost IS NULL          THEN 'no_data'
        WHEN COALESCE(a.ad_cost,0)=0    THEN 'paused'
        ELSE 'active'
    END                                                AS ad_status
FROM ad a LEFT JOIN gmv g ON g.date = a.date;
COMMENT ON VIEW public.v_jd_ad_performance IS
  '京东推广效果 v1：每天一行 花费/订单额/ROI/展现/点击/CTR/CPC/CPM + 推广订单占比 + ad_status(active/paused/no_data)。现状停投paused花费0。';


-- ████ 4. 货款结算流水（切片·京东POP资金，已抓真数据）████████████████████████████
-- 资金台账三数额同日强相关，走宽表（非拆3行长表）；同时镜像 jd_bill_* 进 mvp_daily_metric 复用问数。
CREATE TABLE IF NOT EXISTS public.mvp_jd_daily_bill (
    id              BIGSERIAL PRIMARY KEY,
    set_date        DATE        NOT NULL,        -- 结算日(打款日，主键口径)
    acc_date        DATE,                        -- 账务日(出账日，通常 set_date+1)
    debit_amt       NUMERIC(18,2),               -- 货款收入(元，未扣平台费)
    credit_amt      NUMERIC(18,2),               -- 平台扣费(元)
    actual_settle   NUMERIC(18,2),               -- 实际结算(元)=debit-credit(到账金额，非净利)
    set_status      SMALLINT,                    -- 结算状态码(实测0=已结算)
    bill_id         BIGINT,                      -- 京东侧明细行id
    detail_file_url TEXT,                        -- 当日对账zip链接(s3内网，仅留URL)
    source_runbook  VARCHAR(128) NOT NULL DEFAULT 'jd_bill_capture',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (set_date)
);
CREATE INDEX IF NOT EXISTS idx_jd_daily_bill_setdate ON public.mvp_jd_daily_bill (set_date DESC);
COMMENT ON TABLE public.mvp_jd_daily_bill IS
  '京东POP货款结算流水(源 dailyBillDsmProvider.queryDailyBillByPage)：日级 货款收入/平台扣费/实际结算。⚠️实际结算=货款−平台费，未扣进货成本/推广费，非最终净利，勿与 v_jd_monthly_pnl 净利混。';

-- 平台扣费支出明细（queryBillDetailByDate 当前 harvest 未抓到，先建表占位，抓到自动填）
CREATE TABLE IF NOT EXISTS public.mvp_jd_bill_expense (
    id             BIGSERIAL PRIMARY KEY,
    set_date       DATE        NOT NULL,
    expense_name   TEXT        NOT NULL,         -- 商品技术服务费/退款佣金/运费/交易服务费
    amount         NUMERIC(18,2),
    source_runbook VARCHAR(128) NOT NULL DEFAULT 'jd_bill_detail_capture',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (set_date, expense_name)
);
CREATE INDEX IF NOT EXISTS idx_jd_bill_expense_date ON public.mvp_jd_bill_expense (set_date DESC);
COMMENT ON TABLE public.mvp_jd_bill_expense IS
  '京东POP平台扣费支出明细(源 FinHomePageDsmProvider.queryBillDetailByDate)：日×分项。Σamount≈当日 credit_amt。当前 harvest 未抓到，表为空待抓。';

CREATE OR REPLACE VIEW public.v_jd_daily_bill AS
SELECT b.set_date,
       d.year_month, d.month_cn, d.weekday_cn, d.is_weekend,
       b.acc_date,
       b.debit_amt      AS 货款收入,
       b.credit_amt     AS 平台扣费,
       b.actual_settle  AS 实际结算,
       round(b.credit_amt   / NULLIF(b.debit_amt,0), 4) AS 扣费率,   -- 0-1
       round(b.actual_settle/ NULLIF(b.debit_amt,0), 4) AS 到账率,   -- 0-1
       b.set_status, b.detail_file_url
FROM public.mvp_jd_daily_bill b
LEFT JOIN public.dim_date d ON d.date = b.set_date;
COMMENT ON VIEW public.v_jd_daily_bill IS
  'Power BI 京东货款结算流水：日×货款收入/平台扣费/实际结算 + 扣费率/到账率 + dim_date 月名/周几。⚠️实际结算=到账金额非净利，净利看 v_jd_monthly_pnl。';

CREATE OR REPLACE VIEW public.v_jd_bill_expense AS
SELECT e.set_date, d.year_month, d.month_cn,
       e.expense_name AS 扣费项, e.amount AS 金额
FROM public.mvp_jd_bill_expense e
LEFT JOIN public.dim_date d ON d.date = e.set_date;
COMMENT ON VIEW public.v_jd_bill_expense IS
  'Power BI 京东平台扣费支出明细：日×扣费项。Σ金额≈当日 credit_amt。当前空表待抓。';


-- ████ 5. 京东日报长表挂推广+转化率指标的中文名 + 度量分轴（扩写 059 的 v_jd_daily_metric）████
-- 对外契约：原 7 列全保留，旧 18 指标分支不动；新增 jd_ad_* / jd_cvr 中文名 + kind 分轴。
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
        -- ★ 推广效果新增 ★
        WHEN 'jd_ad_cost'            THEN '推广花费'
        WHEN 'jd_ad_order_sum'       THEN '推广订单金额'
        WHEN 'jd_ad_roi'             THEN '推广投产比'
        WHEN 'jd_ad_impressions'     THEN '推广展现数'
        WHEN 'jd_ad_clicks'          THEN '推广点击数'
        WHEN 'jd_ad_ctr'             THEN '推广点击率'
        WHEN 'jd_ad_cpc'             THEN '推广点击成本(CPC)'
        WHEN 'jd_ad_cpm'             THEN '推广千展成本(CPM)'
        WHEN 'jd_ad_order_cnt'       THEN '推广订单数'
        ELSE metric_name
    END                                                       AS metric_cn,
    value, source_runbook, created_at,
    CASE
        WHEN metric_name IN ('jd_gmv','jd_per_customer_price','jd_uv_value','jd_add_cart_amt',
             'jd_ad_cost','jd_ad_order_sum','jd_ad_cpc','jd_ad_cpm') THEN '金额'
        WHEN metric_name IN ('jd_order_cnt','jd_buyer_cnt','jd_sku_qtty','jd_item_uv','jd_shop_uv',
             'jd_exposure_uv','jd_item_pv','jd_shop_pv','jd_exposure_pv','jd_add_cart_user',
             'jd_ad_impressions','jd_ad_clicks','jd_ad_order_cnt') THEN '计数'
        WHEN metric_name IN ('jd_add_cart_rate','jd_cvr','jd_ad_ctr') THEN '比率'
        WHEN metric_name IN ('jd_ad_roi')                            THEN '比值'
        WHEN metric_name IN ('jd_item_stay_sec','jd_shop_stay_sec')  THEN '时长'
        WHEN metric_name IN ('jd_item_pv_per_uv')                    THEN '效率'
        ELSE '其他'
    END                                                       AS metric_kind,
    CASE WHEN metric_name IN ('jd_add_cart_rate','jd_cvr','jd_ad_ctr')
         THEN round(value * 100, 2) ELSE value END            AS display_value
FROM public.mvp_daily_metric
WHERE platform = 'jd';
COMMENT ON VIEW public.v_jd_daily_metric IS
  'Power BI 京东销售日报 v3：18原指标+9推广+cvr 长表 + 中文名 + metric_kind 分轴/display_value。旧7列契约不变。';


-- ████ 6. 京东 KPI 环比+行业对标宽表视图（切片·对标增强）████████████████████████
-- 料来自 getCoreSummary/getSummary 的 ##compare/##industry/##preIndustry，
-- ingest 把 benchmark 行 upsert 进 mvp_industry_benchmark(category_id='34942' 调味品二级类目)。
-- 缺基准标 NULL 不造分位（getCoreSummary 没给真 percentile）。
CREATE OR REPLACE VIEW public.v_jd_kpi_with_benchmark AS
WITH latest AS (
    SELECT DISTINCT ON (metric_name) metric_name, date, value
      FROM public.mvp_daily_metric
     WHERE platform='jd' AND sku_id='_SHOP_'
     ORDER BY metric_name, date DESC
),
prev AS (
    SELECT m.metric_name, m.value AS prev_value
      FROM public.mvp_daily_metric m
      JOIN (SELECT metric_name, MAX(date) AS d
              FROM public.mvp_daily_metric
             WHERE platform='jd' AND sku_id='_SHOP_'
               AND date < (SELECT MAX(date) FROM public.mvp_daily_metric
                            WHERE platform='jd' AND sku_id='_SHOP_')
             GROUP BY metric_name) p
        ON p.metric_name=m.metric_name AND p.d=m.date
     WHERE m.platform='jd' AND m.sku_id='_SHOP_'
),
bm AS (
    SELECT DISTINCT ON (metric_name) metric_name, industry_avg, industry_top, percentile, industry_rank
      FROM public.mvp_industry_benchmark
     WHERE category_id='34942'
     ORDER BY metric_name, date DESC
)
SELECT
    l.metric_name,
    CASE l.metric_name
        WHEN 'jd_gmv' THEN '成交金额' WHEN 'jd_order_cnt' THEN '成交单量'
        WHEN 'jd_buyer_cnt' THEN '成交客户数' WHEN 'jd_sku_qtty' THEN '成交商品件数'
        WHEN 'jd_per_customer_price' THEN '客单价' WHEN 'jd_cvr' THEN '成交转化率'
        WHEN 'jd_item_uv' THEN '商品访客数' WHEN 'jd_uv_value' THEN 'UV价值'
        ELSE l.metric_name END                                   AS metric_cn,
    l.date                                                       AS as_of,
    l.value                                                      AS shop_value,
    p.prev_value,
    CASE WHEN p.prev_value IS NOT NULL AND p.prev_value<>0
         THEN round((l.value - p.prev_value)/abs(p.prev_value), 4) END  AS mom_pct,
    b.industry_avg, b.industry_top,
    CASE WHEN b.industry_avg IS NOT NULL AND b.industry_avg<>0
         THEN round(l.value / b.industry_avg, 2) END             AS vs_industry_x,
    CASE WHEN b.industry_avg IS NOT NULL AND b.industry_top IS NOT NULL AND b.industry_top>b.industry_avg
         THEN round(greatest(0, least(1, (l.value-b.industry_avg)/(b.industry_top-b.industry_avg))), 4) END
                                                                 AS pos_in_band,
    b.percentile, b.industry_rank
FROM latest l
LEFT JOIN prev p ON p.metric_name=l.metric_name
LEFT JOIN bm   b ON b.metric_name=l.metric_name;
COMMENT ON VIEW public.v_jd_kpi_with_benchmark IS
  '京东核心 KPI + 环比(派生mom)+ 行业对标(行业均/头部/vs倍数/区间位置)。料来自 getCoreSummary/getSummary。缺基准标NULL不造分位。';

-- 行业对标种子（本次 harvest 快照值，ingest 后续会按日 upsert 覆盖；这里手测一条让前端先点亮）
INSERT INTO public.mvp_industry_benchmark
  (date, category_id, metric_name, industry_avg, industry_top, shop_value, percentile, industry_rank, source, raw)
VALUES
  (CURRENT_DATE,'34942','jd_gmv',        221.76, 1250.71, 247.80, NULL, NULL, 'jd_core_summary', '{}'::jsonb),
  (CURRENT_DATE,'34942','jd_order_cnt',    5.80,   34.02,   4,    NULL, NULL, 'jd_core_summary', '{}'::jsonb),
  (CURRENT_DATE,'34942','jd_buyer_cnt',    5.71,   33.37,   4,    NULL, NULL, 'jd_core_summary', '{}'::jsonb),
  (CURRENT_DATE,'34942','jd_sku_qtty',     8.31,   47.55,   4,    NULL, NULL, 'jd_core_summary', '{}'::jsonb),
  (CURRENT_DATE,'34942','jd_item_uv',    103.03,  453.32, 170,    NULL, NULL, 'jd_core_summary', '{}'::jsonb),
  (CURRENT_DATE,'34942','jd_uv_value',     2.15,    2.76,   2.257, NULL, NULL, 'jd_core_summary', '{}'::jsonb),
  (CURRENT_DATE,'34942','jd_cvr',          0.0554,  0.0736, 0.0976, NULL, NULL,'jd_core_summary', '{}'::jsonb)
ON CONFLICT (date, category_id, metric_name) DO UPDATE SET
  industry_avg=EXCLUDED.industry_avg, industry_top=EXCLUDED.industry_top,
  shop_value=EXCLUDED.shop_value, source=EXCLUDED.source, raw=EXCLUDED.raw;

-- ============================================================================
-- 完。新增：2 表(flow_source/daily_bill)+1占位表(bill_expense) + 6 视图 + 长表视图扩写。
-- 零删除、零改 UNIQUE、零动既有视图对外旧列。后续 ingest 落数即全部点亮。
-- ============================================================================