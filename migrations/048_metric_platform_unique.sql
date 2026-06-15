-- migration 048: mvp_daily_metric UNIQUE 收口含 platform 2026-06-12
-- 034 的 STEP 2（contract）。老板 2026-06-12 拍板「主线」接京东，本步是落 platform='jd'
-- 数据的硬前置：不换约束，京东同名指标 upsert 会静默覆写抖音行（非报错）。
-- 设计出处: docs/plans/2026-06-12-京东数据接入PowerBI规划.md §3 切片 1 + 034 注释 STEP 2。
--
-- 同批必须一起上的代码改动（约束换了旧 SQL 直接报 no unique constraint matching）:
--   - metric_ingest.py 三处 upsert ON CONFLICT 改四列（:574/:602/:625）
--   - runbook_executor.py 两处（:398/:528）+ csv_parser.py 一处（:233）改四列并补写 platform
--   - 5 处读取点补 WHERE platform（anomaly_engine ×4 / focus_pool_builder / dashboard /
--     verification / skus 序列 API）——防双平台共存后 jd 行混进抖音口径
--   - tests/test_mcp_scout.py 种子 INSERT 补 platform 列
--
-- 口径决定: platform 不 SET DEFAULT —— 所有写入方必须显式带 platform，
-- 漏带 = NOT NULL 立刻报错快暴露；给 DEFAULT 'douyin' 会让将来京东抽取器
-- 忘传 platform 时静默落成抖音行（比报错毒得多）。

-- ─── 1. 防御性回填（034 已回填过；兜住 034 之后插入的 NULL 行，幂等）──────────
UPDATE mvp_daily_metric SET platform = 'douyin' WHERE platform IS NULL;

-- ─── 2. platform 收口 NOT NULL（重跑无害）─────────────────────────────────
ALTER TABLE mvp_daily_metric ALTER COLUMN platform SET NOT NULL;

-- ─── 3. 换 UNIQUE: 三列 → 四列（含 platform）────────────────────────────────
-- 三列唯一 ⊂ 四列唯一，存量数据不可能违反新约束，直接换。
ALTER TABLE mvp_daily_metric
  DROP CONSTRAINT IF EXISTS mvp_daily_metric_sku_id_date_metric_name_key;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'mvp_daily_metric_sku_date_metric_platform_key'
  ) THEN
    ALTER TABLE mvp_daily_metric
      ADD CONSTRAINT mvp_daily_metric_sku_date_metric_platform_key
      UNIQUE (sku_id, date, metric_name, platform);
  END IF;
END $$;


-- ===== DOWN（手动回滚用）=====
-- 仅在尚未落入第二平台数据（SELECT DISTINCT platform 只有 douyin）时可安全回滚；
-- 已有多平台行再回三列约束会因重复键失败。
--
--   ALTER TABLE mvp_daily_metric
--     DROP CONSTRAINT IF EXISTS mvp_daily_metric_sku_date_metric_platform_key;
--   ALTER TABLE mvp_daily_metric
--     ADD CONSTRAINT mvp_daily_metric_sku_id_date_metric_name_key
--     UNIQUE (sku_id, date, metric_name);
--   ALTER TABLE mvp_daily_metric ALTER COLUMN platform DROP NOT NULL;
--   DELETE FROM public.schema_migrations WHERE filename = '048_metric_platform_unique.sql';
