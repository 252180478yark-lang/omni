-- migration 039: 异动引擎 R-18/R-30 地基 —— mvp_anomaly 加新鲜度/平台/基线列 + 预期事件抑制表
-- 2026-06-02 · 三项目"A 异动引擎"的共享 schema 契约（B 诊断官读、C 桌面 BI 读，先落地基）
-- 对应蓝图 §6.1（异常检出命根子）+ R-18（滚动基线/阈值不写死/断更守卫/自学习抑制）+ R-30（数据新鲜度）。
--
-- ★ 纯加法、可逆（expand-only）★：
--   - mvp_anomaly 只 ADD COLUMN IF NOT EXISTS（绝不改现有列/约束/类型）。
--   - mvp_expected_event 是全新表（CREATE TABLE IF NOT EXISTS）。
--   - 现有 anomaly_engine 写入路径不传新列也不报错（全 nullable / 带默认），零回归。
--   - 现状 mvp_anomaly 存量 100% 抖音；platform 回填 'douyin'。
--
-- 不做（避免过度工程 §1.7 + 留老板拍）：不改 mvp_anomaly 现有 handled 语义、
--   不建额外索引矩阵、不动 mvp_daily_metric、不碰任何 UNIQUE。

-- ─── 1. mvp_anomaly 加列（全 nullable / 带默认，零回归）────────────────────
ALTER TABLE mvp_anomaly ADD COLUMN IF NOT EXISTS platform       VARCHAR(32)  DEFAULT 'douyin';
ALTER TABLE mvp_anomaly ADD COLUMN IF NOT EXISTS as_of          TIMESTAMPTZ;            -- R-30 数据新鲜度:该异动所依据数据的最后成功时点
ALTER TABLE mvp_anomaly ADD COLUMN IF NOT EXISTS baseline_days  INTEGER;               -- R-18 透明:用的滚动基线窗口天数
ALTER TABLE mvp_anomaly ADD COLUMN IF NOT EXISTS baseline_value NUMERIC(20, 6);        -- R-18 透明:对比的基线值
ALTER TABLE mvp_anomaly ADD COLUMN IF NOT EXISTS today_value    NUMERIC(20, 6);        -- 当日值(便于前端展示 delta 来源)
ALTER TABLE mvp_anomaly ADD COLUMN IF NOT EXISTS expected       BOOLEAN      DEFAULT FALSE;  -- R-18:老板一键"这是预期的(大促/上新)"

COMMENT ON COLUMN mvp_anomaly.platform IS '该异动来自哪个平台（douyin/taobao/jd…）；存量回填 douyin';
COMMENT ON COLUMN mvp_anomaly.as_of IS 'R-30 数据新鲜度：该异动所依据数据的最后成功抓取/落库时点（前端据此置灰过期）';
COMMENT ON COLUMN mvp_anomaly.expected IS 'R-18 自学习抑制：老板标"这是预期的(大促/上新)"后置 TRUE；可配合 mvp_expected_event 同类抑制';

-- 存量行 platform 回填 'douyin'（幂等：只填 NULL）
UPDATE mvp_anomaly SET platform = 'douyin' WHERE platform IS NULL;

CREATE INDEX IF NOT EXISTS idx_mvp_anomaly_platform_detected ON mvp_anomaly(platform, detected_at DESC);

-- ─── 2. mvp_expected_event —— R-18 自学习抑制表（预期事件，命中则不误报）────────
-- 老板对某条异动点"这是预期的(大促/上新)"→ 落一条 expected_event；anomaly_engine 检出前
-- 先查这表，命中（sku/metric/platform/rule 匹配 + 当日在 [start_date,end_date] 内）则
-- 抑制（不 fire，或 fire 但标 expected=TRUE，由引擎实现决定）。NULL 字段=通配（不限该维度）。
CREATE TABLE IF NOT EXISTS mvp_expected_event (
    id           BIGSERIAL    PRIMARY KEY,
    sku_id       VARCHAR(64)  REFERENCES mvp_sku(id) ON DELETE CASCADE,  -- NULL = 所有 SKU / 大盘级
    metric_name  VARCHAR(64),                                            -- NULL = 所有指标
    platform     VARCHAR(32)  DEFAULT 'douyin',
    rule_id      VARCHAR(64),                                            -- NULL = 所有规则
    start_date   DATE         NOT NULL,
    end_date     DATE,                                                   -- NULL = 开放区间（长期抑制，慎用）
    reason       TEXT,                                                   -- 大促/上新/活动名…
    actor_id     VARCHAR(64)  DEFAULT 'yark',                            -- R-26 操作者预留
    created_at   TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE mvp_expected_event IS
    'R-18 自学习抑制：老板标"这是预期的(大促/上新)"沉淀于此；anomaly_engine 检出前查这表抑制同类误报。'
    'NULL 字段=通配（不限该维度）；命中条件=维度匹配 AND 当日 ∈ [start_date, COALESCE(end_date, 9999-12-31)]';

CREATE INDEX IF NOT EXISTS idx_expected_event_lookup
    ON mvp_expected_event(platform, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_expected_event_sku
    ON mvp_expected_event(sku_id) WHERE sku_id IS NOT NULL;


-- ===== DOWN（手动回滚用，纯可逆）=====
--   DROP TABLE IF EXISTS mvp_expected_event;
--   DROP INDEX IF EXISTS idx_mvp_anomaly_platform_detected;
--   ALTER TABLE mvp_anomaly
--     DROP COLUMN IF EXISTS platform, DROP COLUMN IF EXISTS as_of,
--     DROP COLUMN IF EXISTS baseline_days, DROP COLUMN IF EXISTS baseline_value,
--     DROP COLUMN IF EXISTS today_value, DROP COLUMN IF EXISTS expected;
--   DELETE FROM public.schema_migrations WHERE filename = '039_anomaly_freshness_suppression.sql';
-- 回滚无损：新列回填的 'douyin' 随列删除（本来全是抖音）；expected_event 是新表无存量依赖。
