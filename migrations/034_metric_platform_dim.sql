-- migration 034: mvp_daily_metric 加 platform 维 2026-06-01
-- 阶段0 真地基 · 块 1 多平台下钻 schema 的 expand-contract STEP 1（纯加法、可逆）。
-- 设计草案: docs/plans/2026-06-01-阶段0-地基设计草案.md 块 1 §1.2.3 / §1.3 Step 1。
--
-- 现状（实读 009_mvp_tables.sql L35-46 + live DB 147 行）:
--   mvp_daily_metric 无 platform 维, UNIQUE(sku_id, date, metric_name) 把
--   "一个 SKU 一天一个指标" 锁死为单值。京东/抖音同一天同一指标只能存一个 → 多平台对比连存都存不下。
--   现状存量 100% 是抖音数据。
--
-- 本 migration 只做 STEP 1（expand）:
--   1. 加 nullable platform 列（绝不加 NOT NULL）
--   2. 幂等回填存量行 platform='douyin'（现有数据全是抖音）
--   3. 加 (platform, date) 索引供按平台下钻
--
-- 严禁（属 STEP 2，等老板二次确认，列进 needsBossDecision）:
--   - 替换/改 UNIQUE(sku_id,date,metric_name) → UNIQUE(...,platform)
--   - platform 加 NOT NULL / SET DEFAULT
--   - 任何 DROP / 改现有列类型
--
-- 纯加法、可逆: ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS + 仅填新列 NULL 的回填 UPDATE。
-- 不应用（留老板早上 apply）。verified via BEGIN/ROLLBACK 事务（不留痕）。

-- ─── 1. 加 platform 列（nullable，绝不 NOT NULL）──────────────────────────
ALTER TABLE mvp_daily_metric
  ADD COLUMN IF NOT EXISTS platform VARCHAR(32);

COMMENT ON COLUMN mvp_daily_metric.platform IS
  '该指标来自哪个平台（douyin / taobao / jd …）。阶段0 STEP 1 加为 nullable 并回填存量为 douyin；'
  'STEP 2（等老板拍板）才收口 NOT NULL + 把 UNIQUE 约束改成含 platform。';

-- ─── 2. 回填存量行 platform='douyin'（幂等:只填 NULL，重跑不覆盖已填的）──────
-- 现状 147 行全部是抖音数据；小表，回填瞬时完成。重跑只命中仍为 NULL 的行。
UPDATE mvp_daily_metric SET platform = 'douyin' WHERE platform IS NULL;

-- ─── 3. 按平台 + 日期下钻索引 ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_mvp_metric_platform_date
  ON mvp_daily_metric (platform, date DESC);


-- ===== DOWN（手动回滚用）=====
-- 纯可逆: platform 全列删除（回填的 'douyin' 随列一起没，无损——本来全是抖音）。
-- 现有任何代码都不依赖 platform 列（STEP 1 只加不改），删列即回到 migration 前现状。
--
--   DROP INDEX IF EXISTS idx_mvp_metric_platform_date;
--   ALTER TABLE mvp_daily_metric DROP COLUMN IF EXISTS platform;
--
-- 回滚后如需从 schema_migrations 注册表移除（让 apply 脚本认为未应用）:
--   DELETE FROM public.schema_migrations WHERE filename = '034_metric_platform_dim.sql';
