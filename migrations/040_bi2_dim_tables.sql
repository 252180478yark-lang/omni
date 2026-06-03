-- migration 040: 全量 BI 2.0 七张维表（2026-06-03）
-- 规格: docs/plans/2026-06-03-bi2-full-build-plan.md（workflow 探明 12 端点真实结构产出）
--
-- 目标: 落库桥此前只落全店 _SHOP_ 标量 + per-SKU(进 mvp_daily_metric)。本 migration 建 7 张
--   **非 SKU 维度**的独立维表(流量来源/达人/搜索词/八大人群×5A/价格带竞品/行业畅销)，
--   承载"塞不进 mvp_daily_metric(sku_id,date,metric_name,value) 契约"的多维结构。
--
-- ★ 纯加法、可逆 ★: 只 CREATE TABLE IF NOT EXISTS + INDEX，绝不 ALTER 既有表、不动任何 UNIQUE。
--   抖音存量 100% 不动、零回归。落库桥 dim_ingest.py 写这 7 表(fail-open)。
--
-- 口径铁律(与 mvp_daily_metric 对齐): 金额 compass 多为「分」÷100 为元;但达人榜 compass.list
--   是「¥xxx」元字符串(禁÷100)、云图 bestseller/价格带商品价已是元(禁÷100)——见各表 migration_note。
--   rate/占比存原始 0-1; rank 越小越靠前; 脱敏区间(价格带 GMV)落 lower/upper 不当精确值。
-- 不应用(留老板/agent apply)、apply 后落库桥 restart 才生效(scout 无 --reload)。

-- ─── 表 1: mvp_flow_source_metric —— 流量来源渠道归因 + 单视频带货榜 ──────────
-- 来源 compass.flow_data_v2。一级渠道(video/product_card/live/other_content) + child 下钻
-- (单视频/单直播/达人/搜索词)。entity_id 用 varchar(video_id/author_id 19位超 bigint)。
CREATE TABLE IF NOT EXISTS mvp_flow_source_metric (
    id                  BIGSERIAL    PRIMARY KEY,
    stat_date           DATE         NOT NULL,                 -- ingest 注入(JSON 不自带)
    platform            VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    source_channel_code VARCHAR(64)  NOT NULL,                 -- video/product_card/live/other_content
    source_channel_name VARCHAR(64),
    entity_type         VARCHAR(16)  NOT NULL,                 -- channel/video/live_room/author/sub_source
    entity_id           VARCHAR(128) NOT NULL,                 -- channel级=channel_code; video级=video_id
    entity_name         VARCHAR(300),
    metric_name         VARCHAR(64)  NOT NULL,
    value               NUMERIC(20,6),
    raw                 JSONB        DEFAULT '{}',
    fetched_at          TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (stat_date, source_channel_code, entity_type, entity_id, metric_name)
);
COMMENT ON TABLE mvp_flow_source_metric IS
    '流量来源渠道归因(compass.flow_data_v2):一级渠道+单视频带货榜(含完播率/播放量)。'
    '非SKU维度。金额price类÷100元、ratio类0-1。entity_id varchar(19位ID超bigint)。child遇unit=nan/缺value跳过';
CREATE INDEX IF NOT EXISTS idx_flow_source_date    ON mvp_flow_source_metric(stat_date DESC, source_channel_code);
CREATE INDEX IF NOT EXISTS idx_flow_source_entity  ON mvp_flow_source_metric(entity_type, entity_id);

-- ─── 表 2: mvp_author_daily_metric —— 罗盘达人带货榜 ─────────────────────────
-- 来源 compass.list。每行一个达人×6 指标。金额坑: pay_gmv/refund 是「¥xxx」元字符串 → strip¥ 禁÷100。
CREATE TABLE IF NOT EXISTS mvp_author_daily_metric (
    id          BIGSERIAL    PRIMARY KEY,
    date        DATE         NOT NULL,
    author_id   VARCHAR(64)  NOT NULL,                 -- text! 19位超 bigint
    nickname    VARCHAR(200),                          -- denorm 展示
    aweme_id    VARCHAR(64),                           -- denorm 可空
    metric_name VARCHAR(64)  NOT NULL,
    value       NUMERIC(20,6),
    platform    VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    fetched_at  TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (date, author_id, metric_name)
);
COMMENT ON TABLE mvp_author_daily_metric IS
    '达人带货榜(compass.list):每行一个达人×6指标(GMV/成交人数/件数/商品数/种草人数/退款)。'
    '金额是¥元字符串strip¥禁÷100(同 _yuan_str);翻页到 page_result.total';
CREATE INDEX IF NOT EXISTS idx_author_date ON mvp_author_daily_metric(date DESC, author_id);

-- ─── 表 3: mvp_search_keyword_rank —— 搜索词榜(宽行) ────────────────────────
-- 来源 compass.word_rank。每窗口可达 318 词、词集随时间漂移 → 宽行存比 EAV 省。
CREATE TABLE IF NOT EXISTS mvp_search_keyword_rank (
    id                   BIGSERIAL    PRIMARY KEY,
    keyword              VARCHAR(200) NOT NULL,
    stat_date_start      DATE,
    stat_date_end        DATE         NOT NULL,
    platform             VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    rank                 INT,
    pay_amt              NUMERIC(20,6),                -- ÷100元
    product_show_ucnt    INT,
    prod_show_click_ratio NUMERIC(8,4),               -- 0-1 可>1 原样勿截断
    prod_click_pay_ratio  NUMERIC(8,4),
    shop_product_ids     JSONB        DEFAULT '[]',    -- 关联本店 product_id 数组
    fetched_at           TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (keyword, stat_date_end, platform)
);
COMMENT ON TABLE mvp_search_keyword_rank IS
    '搜索词榜(compass.word_rank,7天滚动窗 snap):5指标+关联本店商品jsonb。'
    '只落聚合行 data[i].metrics.*(child_rows不落);pay_amt÷100;ratio原样可>1;翻页拿全318词;取值走.value.value';
CREATE INDEX IF NOT EXISTS idx_search_kw_date ON mvp_search_keyword_rank(stat_date_end DESC, rank);
CREATE INDEX IF NOT EXISTS idx_search_kw_word ON mvp_search_keyword_rank(keyword);

-- ─── 表 4: mvp_crowd_big8_profile —— 八大人群×5A×7口径 快照 ──────────────────
-- 来源 yuntu.getaudienceassetbig8profile。三维交叉(stage×big8×profile_type)塞不进 daily_metric。
CREATE TABLE IF NOT EXISTS mvp_crowd_big8_profile (
    id           BIGSERIAL    PRIMARY KEY,
    date         DATE         NOT NULL,                 -- ingest 注入 as_of
    platform     VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    stage_idx    SMALLINT     NOT NULL,                 -- 原始 0-5 数字(不猜A标)
    stage_label  VARCHAR(32),                           -- 留空待比对云图UI再锁
    big8_name    VARCHAR(32)  NOT NULL,                 -- 新锐白领/都市银发/精致妈妈/都市蓝领/z世代/小镇青年/资深中产/小镇中老年
    profile_type VARCHAR(16)  NOT NULL,                 -- self/compete/top5/top20/top50/top100/avg
    cover_cnt    BIGINT,
    cover_pct    NUMERIC(10,6),                         -- 0-1
    permeability NUMERIC(12,8),                         -- 0-1
    fetched_at   TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (date, stage_idx, big8_name, profile_type)
);
COMMENT ON TABLE mvp_crowd_big8_profile IS
    '八大人群×5A阶段×7对照口径 快照(yuntu big8profile)。stage_idx存原始0-5(A标待比对UI);'
    'cnt int化;pct/permeab原样0-1;self万级 vs 同行百万级 量纲按profile_type区分不可混算';
CREATE INDEX IF NOT EXISTS idx_crowd_big8_date ON mvp_crowd_big8_profile(date DESC, profile_type);

-- ─── 表 5: mvp_crowd_asset_trend —— 单人群×7口径 30天序列 ────────────────────
-- 来源 yuntu.getaudienceassetbig8trend。补 big8_profile 的时间维。
CREATE TABLE IF NOT EXISTS mvp_crowd_asset_trend (
    id          BIGSERIAL    PRIMARY KEY,
    date        DATE         NOT NULL,                  -- trend[i].date 'YYYYMMDD'→date
    crowd_name  VARCHAR(32)  NOT NULL,                  -- big8_name(当前恒'新锐白领')
    scope       VARCHAR(16)  NOT NULL,                  -- self/compete/top5/top20/top50/top100/avg
    cnt         BIGINT,
    asset_percent NUMERIC(10,6),                        -- 0-1
    permeab     NUMERIC(12,8),                          -- 0-1
    platform    VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    fetched_at  TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (date, crowd_name, scope)
);
COMMENT ON TABLE mvp_crowd_asset_trend IS
    '单人群资产 本店vs同行 30天序列(yuntu big8trend)。trend[]按日期迭代×7 profile;'
    'cnt int化(人数非金额);percent/permeab原始0-1;date YYYYMMDD strptime';
CREATE INDEX IF NOT EXISTS idx_crowd_trend_date ON mvp_crowd_asset_trend(date DESC, scope);

-- ─── 表 6: mvp_price_band_product —— 价格带×竞品商品榜 ───────────────────────
-- 来源 compass.category_overview_price_analysis_product。product_id 多为同行竞品,GMV 是脱敏区间。
CREATE TABLE IF NOT EXISTS mvp_price_band_product (
    id                BIGSERIAL    PRIMARY KEY,
    date              DATE         NOT NULL,
    platform          VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    category_id       VARCHAR(64)  NOT NULL,             -- 外部注入 '14'
    band_label        VARCHAR(32)  NOT NULL,             -- 外部注入(JSON内无)
    rank              INT,
    product_id        VARCHAR(128),
    product_name      VARCHAR(300),
    product_image_url TEXT,
    gmv_lower_yuan    NUMERIC(20,6),                     -- 分÷100
    gmv_upper_yuan    NUMERIC(20,6),                     -- 分÷100
    addable           BOOLEAN,
    fetched_at        TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (date, category_id, band_label, product_id)
);
COMMENT ON TABLE mvp_price_band_product IS
    '价格带×竞品商品榜(compass price_analysis_product):同行竞品池选品情报。'
    'GMV是lower/upper脱敏区间÷100(禁当精确值,违R-14);band_label+category_id从ingest入参注入(payload内无)';
CREATE INDEX IF NOT EXISTS idx_price_band_date ON mvp_price_band_product(date DESC, band_label, rank);

-- ─── 表 7: mvp_industry_bestseller —— 云图行业畅销/新品榜 ────────────────────
-- 来源 yuntu.bestsellingproduct。竞品 SPU 排行情报,无 GMV/销量,信号=rank+展示价+dimension三态。
CREATE TABLE IF NOT EXISTS mvp_industry_bestseller (
    id            BIGSERIAL    PRIMARY KEY,
    snapshot_date DATE         NOT NULL,
    platform      VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    dimension     VARCHAR(32)  NOT NULL,                -- BEST_SELLING_PRODUCT/NEW_ARRIVAL_PRODUCT/NORMAL_PRODUCT
    rank          INT          NOT NULL,                -- 数组下标+1
    spu_id        VARCHAR(128),
    spu_name      VARCHAR(300),
    display_price NUMERIC(20,6),                        -- 已是元(样本带小数)禁÷100
    category_l1   VARCHAR(100),
    category_l2   VARCHAR(100),
    category_l3   VARCHAR(100),
    image_url     TEXT,
    fetched_at    TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (snapshot_date, dimension, rank)
);
COMMENT ON TABLE mvp_industry_bestseller IS
    '云图行业畅销/新品榜(yuntu bestsellingproduct):竞品SPU排行选品参考。'
    'rank=数组下标+1(越小越靠前);display_price已是元禁÷100;category_l1/l2/l3来自categories[0..2];dimension原样存';
CREATE INDEX IF NOT EXISTS idx_bestseller_date ON mvp_industry_bestseller(snapshot_date DESC, dimension);


-- ===== DOWN（手动回滚用）=====
-- 纯加法纯可逆,7 张独立维表无相互 FK,DROP 顺序无关:
-- DROP TABLE IF EXISTS mvp_flow_source_metric;
-- DROP TABLE IF EXISTS mvp_author_daily_metric;
-- DROP TABLE IF EXISTS mvp_search_keyword_rank;
-- DROP TABLE IF EXISTS mvp_crowd_big8_profile;
-- DROP TABLE IF EXISTS mvp_crowd_asset_trend;
-- DROP TABLE IF EXISTS mvp_price_band_product;
-- DROP TABLE IF EXISTS mvp_industry_bestseller;
-- 回滚无损:维表数据由 dim_ingest.py 幂等重建(re-run ingest)。
-- 注销 migration 记录: DELETE FROM public.schema_migrations WHERE filename = '040_bi2_dim_tables.sql';
