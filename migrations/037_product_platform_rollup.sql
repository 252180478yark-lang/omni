-- migration 037: product/SPU 主体 + platform_listing 映射 + roll-up 视图 2026-06-01
-- 阶段0 地基 · 设计草案"块 1"(E:\agent\omni\docs\plans\2026-06-01-阶段0-地基设计草案.md)
--
-- 目标:把"SKU 身份"和"平台上架"解耦——一个平台无关商品主体(product/SPU)可在 N 个
--   平台各有一条 listing,为接淘宝/京东留形状。**懒填策略**:抖音存量继续走 mvp_sku 老路,
--   product 是"将来多平台才填满"的占位抽象,platform_listing 抖音行先直接挂 mvp_sku_id。
--
-- ★ expand-contract STEP 1 ★ 纯加法、可逆:
--   只 CREATE TABLE/VIEW(全部 IF NOT EXISTS / OR REPLACE),**绝不 ALTER mvp_sku**、
--   不动 mvp_sku 主键/列、不动 mvp_daily_metric 既有列、不改任何 UNIQUE 约束。
--   抖音存量 100% 不动、零回归。
--
-- ⚠️ 应用顺序依赖:本 migration 的 v_metric_rollup 视图读 mvp_daily_metric.platform 列,
--   该列由 migration 034 添加(设计草案 §1.2.3)。**037 必须在 034 之后应用**。
--   视图体内对 platform 用 COALESCE(..., 'douyin') 兜底:存量行 platform 为 NULL 时
--   仍归到 'douyin'(现状 100% 是抖音数据),不依赖 034 的回填先跑完。
--
-- 不应用(留老板 apply)、不接 cron、不回填 product(懒填,避免净增录入负担)。
-- 设计草案标 needs_boss 的(cost_items actor / 替换 mvp_daily_metric UNIQUE 约束 /
--   GMV·ROI 归一口径)**本 migration 一律不做**,见文件末尾 needs_boss 清单。

-- ─── 新表 A:product —— 平台无关商品主体 / SPU ──────────────────────────
-- 起步阶段可与 mvp_sku 1:1 甚至留空;不强制现在给每个抖音 SKU 建 product 行(懒填)。
CREATE TABLE IF NOT EXISTS product (
    id          VARCHAR(64)  PRIMARY KEY,            -- SPU 主键(如 'SPU-酱油-特级-500ml' 老板可读,或 uuid 文本)
    name        VARCHAR(200) NOT NULL,               -- 跨平台统一品名
    category    VARCHAR(100),                        -- 品类(roll-up 归一用)
    brand_id    VARCHAR(64),                         -- 品牌(对齐 5A/品牌心智的 brand_id)
    status      VARCHAR(32)  DEFAULT 'active',
    metadata    JSONB        DEFAULT '{}',           -- 规格/条码等扩展
    -- 操作者预留(设计草案块 3 §R-26:单人→小团队只填字段不改表);单人期默认 'yark'
    actor_id    VARCHAR(64)  DEFAULT 'yark',
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE product IS
    '平台无关商品主体(SPU):盖在 mvp_sku 之上的多平台抽象。懒填——抖音单平台时可留空,'
    'platform_listing 直接挂 mvp_sku;将来接淘宝/京东时一个 SPU 下挂多条 platform_listing';
COMMENT ON COLUMN product.actor_id IS
    '操作者预留字段(设计草案【R-26】单人→小团队只填字段不改表);单人期默认 yark';

CREATE INDEX IF NOT EXISTS idx_product_category ON product(category);
CREATE INDEX IF NOT EXISTS idx_product_brand    ON product(brand_id);

-- ─── 新表 B:platform_listing —— 每平台上架映射(解绑核心) ─────────────────
-- 把"商品在某平台的身份"从 mvp_sku 里抽出来。抖音存量回填指向现有 mvp_sku 行;
-- 淘宝/京东新 listing 没有对应 mvp_sku(mvp_sku 是抖音独有形状)→ mvp_sku_id 留空,挂 product。
CREATE TABLE IF NOT EXISTS platform_listing (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- SPU(可后补,不阻塞):懒填策略下抖音行可先只挂 mvp_sku_id、product_id 留空
    product_id           VARCHAR(64)  REFERENCES product(id) ON DELETE SET NULL,
    platform             VARCHAR(32)  NOT NULL,      -- douyin / taobao / jd …
    external_product_id  VARCHAR(128) NOT NULL,      -- 该平台商品 ID(抖音=douyin_product_id,淘宝=item_id…)
    -- 抖音存量回填指向现有 mvp_sku 行;非抖音平台为空(mvp_sku 是抖音独有形状)
    mvp_sku_id           VARCHAR(64)  REFERENCES mvp_sku(id) ON DELETE SET NULL,
    listing_url          TEXT,
    status               VARCHAR(32)  DEFAULT 'active',
    -- 操作者预留(同 product)
    actor_id             VARCHAR(64)  DEFAULT 'yark',
    created_at           TIMESTAMPTZ  DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  DEFAULT NOW(),
    -- 平台内商品唯一,跨平台不冲突(抖音和淘宝可有同名 external_product_id 各占一行)
    UNIQUE (platform, external_product_id)
);

COMMENT ON TABLE platform_listing IS
    '每平台上架映射:一个 product/SPU 在某平台一条。抖音存量回填挂 mvp_sku_id(走老路零改动),'
    '淘宝/京东新 listing 挂 product_id、mvp_sku_id 留空。UNIQUE(platform,external_product_id) 平台内唯一';
COMMENT ON COLUMN platform_listing.mvp_sku_id IS
    'nullable:抖音 listing 回填指向现有 mvp_sku 行;非抖音平台无对应 mvp_sku 留空,挂 product 即可';
COMMENT ON COLUMN platform_listing.actor_id IS
    '操作者预留字段(设计草案【R-26】);单人期默认 yark';

CREATE INDEX IF NOT EXISTS idx_listing_product  ON platform_listing(product_id);
CREATE INDEX IF NOT EXISTS idx_listing_platform ON platform_listing(platform, status);
CREATE INDEX IF NOT EXISTS idx_listing_mvp_sku  ON platform_listing(mvp_sku_id)
    WHERE mvp_sku_id IS NOT NULL;

-- ─── roll-up 只读视图:平台 → 品类 → SKU 三层聚合 ────────────────────────
-- 设计草案 §6.1 下钻命脉:"总盘掉了 → 哪个平台 → 哪个品类 → 哪个 SKU"。
-- 读 mvp_daily_metric JOIN mvp_sku,按 (platform, category, sku) 聚合。
-- platform 来自 mvp_daily_metric.platform(034 添加);COALESCE 兜底:NULL → 'douyin'
--   (现状存量 100% 抖音),所以即便 034 回填还没跑,视图也能出数。
-- ⚠️ 依赖 034:该列不存在时本 CREATE 会报 "column m.platform does not exist"——
--   这是 037 须在 034 之后应用的硬依赖(见文件头注释 + needs_boss)。
CREATE OR REPLACE VIEW v_metric_rollup AS
SELECT
    COALESCE(m.platform, 'douyin')  AS platform,
    s.category                      AS category,
    m.sku_id                        AS sku_id,
    s.name                          AS sku_name,
    m.date                          AS date,
    m.metric_name                   AS metric_name,
    COUNT(*)                        AS row_count,
    SUM(m.value)                    AS value_sum,
    AVG(m.value)                    AS value_avg
FROM mvp_daily_metric m
JOIN mvp_sku s ON s.id = m.sku_id
GROUP BY
    COALESCE(m.platform, 'douyin'),
    s.category,
    m.sku_id,
    s.name,
    m.date,
    m.metric_name;

COMMENT ON VIEW v_metric_rollup IS
    '多平台指标 roll-up(平台×品类×SKU×日期×指标聚合):分析面下钻读这视图;'
    'platform 来自 mvp_daily_metric.platform(migration 034 添加),COALESCE 兜底 douyin。'
    '只读视图,不落库;5A/品牌心智抖音专属指标在各自原表,不并入此聚合';


-- ===== DOWN（手动回滚用）=====
-- 纯加法,纯可逆。逆操作顺序:先删依赖(视图)→ 再删子表(platform_listing 含 FK→product)
--   → 最后删父表(product)。不动 mvp_sku / mvp_daily_metric 任何东西(本 migration 没碰)。
--
-- DROP VIEW IF EXISTS v_metric_rollup;
-- DROP TABLE IF EXISTS platform_listing;   -- 同时删其 idx_listing_* 索引 + UNIQUE + FK
-- DROP TABLE IF EXISTS product;            -- 同时删其 idx_product_* 索引
--
-- 回滚无损:product 懒填未回填数据;platform_listing 若已回填抖音映射,DROP 会丢这些
--   映射行,但它们可由回填脚本(设计草案 §1.4)从 mvp_sku 幂等重建,故无真实损失。
-- 注销 migration 记录(若已 apply):
--   DELETE FROM public.schema_migrations WHERE filename = '037_product_platform_rollup.sql';
