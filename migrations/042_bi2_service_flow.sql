-- migration 042: BI 2.0 补 3 张维表 —— 服务健康(差评) + 流量入口结构（2026-06-05）
--
-- 老板"还有需要增加的数据吗" → 全端点对账后定调只补 4 个高价值, 实时重探拿真结构后落 3 张:
--   · mvp_negative_comment_tag  差评原因标签榜 (doudian.getnegativecommenttagscount)
--   · mvp_comment_tag_agg       差评聚合标签×类目 (doudian.allcommenttagaggstat)
--   · mvp_flow_entry_structure  流量入口结构 货架vs内容场 GMV占比 (yuntu.flowentrystructure)
--
-- ★ 纯加法、可逆 ★: 只 CREATE TABLE IF NOT EXISTS + INDEX, 不动既有表。落库桥 dim_ingest 写(fail-open)。
-- 口径: comment_count/aggr_count 计数 int; flowentrystructure value 是 0-1 占比原样存。快照端点无日期 → date=today。

-- ─── 表 1: mvp_negative_comment_tag —— 差评原因标签榜 ───────────────────────────
-- 来源 doudian.getNegativeCommentTagsCount。data[].{tag_id, tag_name, comment_count}。
-- 服务健康真空白: 此前 BI 只有体验分数字, 没有"差在哪"。日级累积 → 同环比靠 date 列。
CREATE TABLE IF NOT EXISTS mvp_negative_comment_tag (
    id            BIGSERIAL    PRIMARY KEY,
    date          DATE         NOT NULL,                 -- ingest 注入(快照无日期)
    platform      VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    tag_id        INT          NOT NULL,
    tag_name      VARCHAR(64)  NOT NULL,
    comment_count INT,
    fetched_at    TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (date, tag_id)
);
COMMENT ON TABLE mvp_negative_comment_tag IS
    '差评原因标签榜(doudian getNegativeCommentTagsCount):tag_name+comment_count。服务健康诊断。'
    'date=ingest today; 日级累积比同环比';
CREATE INDEX IF NOT EXISTS idx_neg_comment_date ON mvp_negative_comment_tag(date DESC, comment_count DESC);

-- ─── 表 2: mvp_comment_tag_agg —— 差评聚合标签 × 类目 ─────────────────────────
-- 来源 doudian.allCommentTagAggStat。data{cat_key:[{tag_key,tag_name,aggr_count,priority}]}。
-- 外层 cat_key(如 '1')是评价类目维度; 配 表1 看"哪类差评聚集"。
CREATE TABLE IF NOT EXISTS mvp_comment_tag_agg (
    id         BIGSERIAL    PRIMARY KEY,
    date       DATE         NOT NULL,
    platform   VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    cat_key    VARCHAR(32)  NOT NULL,                    -- data 外层键(评价类目)
    tag_key    VARCHAR(32)  NOT NULL,
    tag_name   VARCHAR(64),
    aggr_count INT,
    priority   INT,
    fetched_at TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (date, cat_key, tag_key)
);
COMMENT ON TABLE mvp_comment_tag_agg IS
    '差评聚合标签×类目(doudian allCommentTagAggStat):data 外层 cat_key + 内层 tag 聚合数。配 mvp_negative_comment_tag';
CREATE INDEX IF NOT EXISTS idx_comment_agg_date ON mvp_comment_tag_agg(date DESC, aggr_count DESC);

-- ─── 表 3: mvp_flow_entry_structure —— 流量入口结构(货架 vs 内容场) ────────────
-- 来源 yuntu flowEntryStructure。data[].{metricsType, dimension(MALL货架/FEED内容), brandType, value(0-1占比)}。
-- 本店/竞品/行业三方对比 货架场 vs 内容场 GMV 占比 → 看自己内容场是否偏科。
CREATE TABLE IF NOT EXISTS mvp_flow_entry_structure (
    id           BIGSERIAL    PRIMARY KEY,
    date         DATE         NOT NULL,
    platform     VARCHAR(32)  NOT NULL DEFAULT 'douyin',
    metrics_type VARCHAR(32)  NOT NULL,                  -- GMV 等
    dimension    VARCHAR(32)  NOT NULL,                  -- MALL(货架) / FEED(内容)
    brand_type   VARCHAR(32)  NOT NULL,                  -- BRAND(本店)/COMPETITOR_BRAND(竞品)/INDUSTRY_BRAND(行业)
    value        NUMERIC(12,8),                          -- 占比 0-1 原样
    fetched_at   TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (date, metrics_type, dimension, brand_type)
);
COMMENT ON TABLE mvp_flow_entry_structure IS
    '流量入口结构(yuntu flowEntryStructure):货架MALL vs 内容FEED GMV占比, 本店/竞品/行业三方。value 0-1 占比原样';
CREATE INDEX IF NOT EXISTS idx_flow_entry_date ON mvp_flow_entry_structure(date DESC, metrics_type);
