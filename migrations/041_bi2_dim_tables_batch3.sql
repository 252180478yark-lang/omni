-- migration 041: 全量 BI 2.0 第3批维表（2026-06-03）
-- 榜单/明细类维度：直播间榜 / 行业达人榜 / 品牌心智词 / 平台罚单 / 同类竞品 / 视频看后搜 / 实时热词。
-- 自家流量源(flow_source_detail) 复用 040 的 mvp_flow_source_metric(entity_type='self_channel')，不新建。
-- ★ 纯加法可逆 ★ 全 IF NOT EXISTS + UNIQUE + 索引。口径同 040（金额÷100元、rate 0-1、rank越小越好）。

-- 1. 直播间榜（compass.top_list）
CREATE TABLE IF NOT EXISTS mvp_live_room_rank (
    id            BIGSERIAL PRIMARY KEY,
    date          DATE        NOT NULL,
    platform      VARCHAR(32) NOT NULL DEFAULT 'douyin',
    rank          INT         NOT NULL,
    author_name   VARCHAR(200),
    live_pay_amt  NUMERIC(20,6),         -- 直播支付金额(元)
    live_pay_ratio NUMERIC(10,6),        -- 占比 0-1
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, rank)
);
CREATE INDEX IF NOT EXISTS idx_live_room_date ON mvp_live_room_rank(date DESC, rank);

-- 2. 行业达人榜（yuntu.bestsellingauthor，profile 无 GMV）
CREATE TABLE IF NOT EXISTS mvp_industry_author_rank (
    id            BIGSERIAL PRIMARY KEY,
    snapshot_date DATE        NOT NULL,
    platform      VARCHAR(32) NOT NULL DEFAULT 'douyin',
    rank          INT         NOT NULL,
    author_id     VARCHAR(64),
    author_name   VARCHAR(200),
    fans_num      BIGINT,
    main_category VARCHAR(200),
    price_range   VARCHAR(64),
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (snapshot_date, rank)
);
CREATE INDEX IF NOT EXISTS idx_ind_author_date ON mvp_industry_author_rank(snapshot_date DESC, rank);

-- 3. 品牌心智词（yuntu.listbrandtopkeyword）
CREATE TABLE IF NOT EXISTS mvp_brand_keyword (
    id            BIGSERIAL PRIMARY KEY,
    date          DATE        NOT NULL,
    platform      VARCHAR(32) NOT NULL DEFAULT 'douyin',
    keyword       VARCHAR(200) NOT NULL,
    association_cnt INT, content_cnt INT, engagement_cnt INT, search_cnt INT,
    brand_assoc_rank INT, industry_assoc_rank INT,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, keyword)
);
CREATE INDEX IF NOT EXISTS idx_brand_kw_date ON mvp_brand_keyword(date DESC);

-- 4. 平台罚单（doudian.get_ticket_list）
CREATE TABLE IF NOT EXISTS mvp_shop_ticket (
    id            BIGSERIAL PRIMARY KEY,
    ticket_id     VARCHAR(64) NOT NULL,
    platform      VARCHAR(32) NOT NULL DEFAULT 'douyin',
    ticket_type   INT,
    standard_ticket_type VARCHAR(64),
    violation_reason TEXT,
    circumstances_level INT,
    ticket_status INT,
    object_name   VARCHAR(200),
    create_date   DATE,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticket_id)
);
CREATE INDEX IF NOT EXISTS idx_ticket_date ON mvp_shop_ticket(create_date DESC NULLS LAST);

-- 5. 同类竞品（compass.good_compete_product_list，GMV 脱敏区间）
CREATE TABLE IF NOT EXISTS mvp_compete_product (
    id            BIGSERIAL PRIMARY KEY,
    date          DATE        NOT NULL,
    platform      VARCHAR(32) NOT NULL DEFAULT 'douyin',
    rank          INT         NOT NULL,
    comp_product_id VARCHAR(128),
    comp_name     VARCHAR(300),
    pay_amt_lower NUMERIC(20,6),  -- 脱敏区间÷100元(禁当精确值)
    pay_amt_upper NUMERIC(20,6),
    pay_ucnt      INT,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, rank, comp_product_id)
);
CREATE INDEX IF NOT EXISTS idx_compete_date ON mvp_compete_product(date DESC, rank);

-- 6. 视频看后搜（compass.shop_video_list）
CREATE TABLE IF NOT EXISTS mvp_video_aftersearch (
    id            BIGSERIAL PRIMARY KEY,
    date          DATE        NOT NULL,
    platform      VARCHAR(32) NOT NULL DEFAULT 'douyin',
    video_id      VARCHAR(64) NOT NULL,
    video_title   VARCHAR(300),
    aftersearch_uv INT,
    aftersearch_rate NUMERIC(10,6),  -- 看后搜率 0-1
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, video_id)
);
CREATE INDEX IF NOT EXISTS idx_video_as_date ON mvp_video_aftersearch(date DESC);

-- 7. 实时热词机会（compass.realtime_word_overview_v2）
CREATE TABLE IF NOT EXISTS mvp_realtime_hotword (
    id            BIGSERIAL PRIMARY KEY,
    date          DATE        NOT NULL,
    platform      VARCHAR(32) NOT NULL DEFAULT 'douyin',
    keyword       VARCHAR(200) NOT NULL,
    opportunity_score NUMERIC(12,6),
    search_index  BIGINT,
    rank          INT,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, keyword)
);
CREATE INDEX IF NOT EXISTS idx_hotword_date ON mvp_realtime_hotword(date DESC, rank);

-- ===== DOWN（手动回滚）=====
-- DROP TABLE IF EXISTS mvp_live_room_rank, mvp_industry_author_rank, mvp_brand_keyword,
--   mvp_shop_ticket, mvp_compete_product, mvp_video_aftersearch, mvp_realtime_hotword;
-- 注销: DELETE FROM public.schema_migrations WHERE filename='041_bi2_dim_tables_batch3.sql';
