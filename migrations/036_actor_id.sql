-- migration 036: actor_id 预留（R-26 单人长到小团队不返工）2026-06-02
-- 阶段0 真地基 · 块3 · 纯加法 STEP 1（expand，无 contract，可逆）
--
-- 背景（设计草案 2026-06-01-阶段0-地基设计草案.md 块3）：
--   蓝图 §1.6【R-26】把"单人系统"定为易变业务假设。当前几乎所有
--   反馈/留痕/决策/pipeline 表都没有 actor 维——团队一扩张就分不清
--   "谁打的差评 / 谁报的 bug / 谁拍的板 / 谁跑/采纳的这版"。
--   现在加 nullable + DEFAULT 'yark' 列成本≈0，将来填真实 actor 即可，零结构变更。
--
-- 口径（草案 3.4）：
--   - 统一形状 VARCHAR(64) DEFAULT 'yark'，nullable，不加 NOT NULL（单人期不强约束）
--   - 人产生的主观/决策/反馈数据加 actor；机器抓的客观指标数据不加（mvp_daily_metric / mvp_5a_* 不在本表清单）
--   - 语义更精确处用专名同形状：tool_calls 评分用 rated_by；pipeline 采纳用 adopted_by；
--     assets 投后回传用 recorded_by（调用本身 AI 发起、行本身机器跑，故区分"创建/评分/采纳/回传"四类人事）
--
-- ⚠️ accounting.cost_items 本次【不加】——草案标 needs_boss（涉钱 + real/public passphrase 可见性），单独评估。
--
-- 现有写入路径零改动仍跑通（不传 → DEFAULT 'yark'）；DROP COLUMN 即回到现状（无代码依赖这些列）。

-- ════════════════════════════════════════════════════════════════
-- 1. 反馈 / 留痕 / 决策表组（mcp schema）—— 统一 actor_id
-- ════════════════════════════════════════════════════════════════

-- mcp.message_feedback（031）：差评是谁打的 → 团队期按人聚类诊断
ALTER TABLE mcp.message_feedback
  ADD COLUMN IF NOT EXISTS actor_id VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN mcp.message_feedback.actor_id IS
  'R-26 预留：谁打的这条反馈，默认 yark；团队期填真实 actor';

-- mcp.tool_calls（016）：调用本身 AI 发起不需 actor，但 user_rating 侧需要"谁评的" → 专名 rated_by
ALTER TABLE mcp.tool_calls
  ADD COLUMN IF NOT EXISTS rated_by VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN mcp.tool_calls.rated_by IS
  'R-26 预留：谁给这次工具调用打的评分(user_rating)，默认 yark；同形状 VARCHAR(64)';

-- mcp.bug_memory（032）：谁报的 bug / 谁标的已修
ALTER TABLE mcp.bug_memory
  ADD COLUMN IF NOT EXISTS actor_id VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN mcp.bug_memory.actor_id IS
  'R-26 预留：谁报/谁标记此 bug，默认 yark';

-- mcp.client_logs（032）：人触发的操作留 actor；自动事件可留空（nullable）
ALTER TABLE mcp.client_logs
  ADD COLUMN IF NOT EXISTS actor_id VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN mcp.client_logs.actor_id IS
  'R-26 预留：人触发的操作留 actor(默认 yark)，纯机器自动事件可置空';

-- mcp.decisions（017）："谁拍的板"是决策的一等属性
ALTER TABLE mcp.decisions
  ADD COLUMN IF NOT EXISTS actor_id VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN mcp.decisions.actor_id IS
  'R-26 预留：谁拍的这个板，默认 yark';

-- mcp.observations（017）：谁创建/拥有这个巡检任务
ALTER TABLE mcp.observations
  ADD COLUMN IF NOT EXISTS actor_id VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN mcp.observations.actor_id IS
  'R-26 预留：谁创建/拥有这个巡检任务，默认 yark';


-- ════════════════════════════════════════════════════════════════
-- 2. pipeline 链路 6 表（pipeline schema）
--    创建者 actor_id + 采纳者 adopted_by（status draft→adopted 两态对应两类人事）
-- ════════════════════════════════════════════════════════════════

-- pipeline.matrix_runs（021，step 2 卖点矩阵）
ALTER TABLE pipeline.matrix_runs
  ADD COLUMN IF NOT EXISTS actor_id   VARCHAR(64) DEFAULT 'yark';
ALTER TABLE pipeline.matrix_runs
  ADD COLUMN IF NOT EXISTS adopted_by VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN pipeline.matrix_runs.actor_id   IS 'R-26 预留：谁跑的这版矩阵，默认 yark';
COMMENT ON COLUMN pipeline.matrix_runs.adopted_by IS 'R-26 预留：谁采纳的这版(status=adopted)，默认 yark';

-- pipeline.audience_runs（021，step 3 人群报告整段）
ALTER TABLE pipeline.audience_runs
  ADD COLUMN IF NOT EXISTS actor_id   VARCHAR(64) DEFAULT 'yark';
ALTER TABLE pipeline.audience_runs
  ADD COLUMN IF NOT EXISTS adopted_by VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN pipeline.audience_runs.actor_id   IS 'R-26 预留：谁跑的这版人群报告，默认 yark';
COMMENT ON COLUMN pipeline.audience_runs.adopted_by IS 'R-26 预留：谁采纳的这版，默认 yark';

-- pipeline.audience_records（021，step 3 拆出的单个人群）
ALTER TABLE pipeline.audience_records
  ADD COLUMN IF NOT EXISTS actor_id   VARCHAR(64) DEFAULT 'yark';
ALTER TABLE pipeline.audience_records
  ADD COLUMN IF NOT EXISTS adopted_by VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN pipeline.audience_records.actor_id   IS 'R-26 预留：谁产生/归属此人群记录，默认 yark';
COMMENT ON COLUMN pipeline.audience_records.adopted_by IS 'R-26 预留：谁勾选采纳此人群挂下游，默认 yark';

-- pipeline.audience_packs（021，step 4 圈包 SOP）
ALTER TABLE pipeline.audience_packs
  ADD COLUMN IF NOT EXISTS actor_id   VARCHAR(64) DEFAULT 'yark';
ALTER TABLE pipeline.audience_packs
  ADD COLUMN IF NOT EXISTS adopted_by VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN pipeline.audience_packs.actor_id   IS 'R-26 预留：谁跑的这版圈包，默认 yark';
COMMENT ON COLUMN pipeline.audience_packs.adopted_by IS 'R-26 预留：谁采纳的这版圈包，默认 yark';

-- pipeline.scripts（021，step 5/6 脚本 + 分镜）
ALTER TABLE pipeline.scripts
  ADD COLUMN IF NOT EXISTS actor_id   VARCHAR(64) DEFAULT 'yark';
ALTER TABLE pipeline.scripts
  ADD COLUMN IF NOT EXISTS adopted_by VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN pipeline.scripts.actor_id   IS 'R-26 预留：谁跑的这版脚本，默认 yark';
COMMENT ON COLUMN pipeline.scripts.adopted_by IS 'R-26 预留：谁采纳的这版脚本，默认 yark';

-- pipeline.assets（021，分镜图/视频 + 投后 ad_metrics 回传锚点）
--   创建者 actor_id + 采纳者 adopted_by + 投后回传者 recorded_by（草案 3.3 ad_metrics 回传专名）
ALTER TABLE pipeline.assets
  ADD COLUMN IF NOT EXISTS actor_id    VARCHAR(64) DEFAULT 'yark';
ALTER TABLE pipeline.assets
  ADD COLUMN IF NOT EXISTS adopted_by  VARCHAR(64) DEFAULT 'yark';
ALTER TABLE pipeline.assets
  ADD COLUMN IF NOT EXISTS recorded_by VARCHAR(64) DEFAULT 'yark';
COMMENT ON COLUMN pipeline.assets.actor_id    IS 'R-26 预留：谁生成/创建这个素材，默认 yark';
COMMENT ON COLUMN pipeline.assets.adopted_by  IS 'R-26 预留：谁采纳/发布这个素材，默认 yark';
COMMENT ON COLUMN pipeline.assets.recorded_by IS 'R-26 预留：谁回传的投后 ad_metrics，默认 yark';


-- ════════════════════════════════════════════════════════════════
-- 回填（幂等）：DEFAULT 'yark' 已自动覆盖新增列的所有现有行（ADD COLUMN ... DEFAULT
-- 会把存量行一并填上默认值），无需额外 UPDATE。如需显式幂等回填可重跑：
--   UPDATE <t> SET actor_id='yark' WHERE actor_id IS NULL;   -- 只填 NULL，不覆盖已填
-- ════════════════════════════════════════════════════════════════


-- ═════════════════════════════════════════════════════════════════════════
-- ===== DOWN（手动回滚用）=====
-- 纯可逆：逐表 DROP COLUMN 即回到本 migration 之前状态（无代码/外键依赖这些列）。
-- 注意：回滚也要从 public.schema_migrations 删本行才能让 apply 脚本重跑：
--   DELETE FROM public.schema_migrations WHERE filename='036_actor_id.sql';
--
-- ALTER TABLE mcp.message_feedback     DROP COLUMN IF EXISTS actor_id;
-- ALTER TABLE mcp.tool_calls           DROP COLUMN IF EXISTS rated_by;
-- ALTER TABLE mcp.bug_memory           DROP COLUMN IF EXISTS actor_id;
-- ALTER TABLE mcp.client_logs          DROP COLUMN IF EXISTS actor_id;
-- ALTER TABLE mcp.decisions            DROP COLUMN IF EXISTS actor_id;
-- ALTER TABLE mcp.observations         DROP COLUMN IF EXISTS actor_id;
--
-- ALTER TABLE pipeline.matrix_runs     DROP COLUMN IF EXISTS actor_id, DROP COLUMN IF EXISTS adopted_by;
-- ALTER TABLE pipeline.audience_runs   DROP COLUMN IF EXISTS actor_id, DROP COLUMN IF EXISTS adopted_by;
-- ALTER TABLE pipeline.audience_records DROP COLUMN IF EXISTS actor_id, DROP COLUMN IF EXISTS adopted_by;
-- ALTER TABLE pipeline.audience_packs  DROP COLUMN IF EXISTS actor_id, DROP COLUMN IF EXISTS adopted_by;
-- ALTER TABLE pipeline.scripts         DROP COLUMN IF EXISTS actor_id, DROP COLUMN IF EXISTS adopted_by;
-- ALTER TABLE pipeline.assets          DROP COLUMN IF EXISTS actor_id, DROP COLUMN IF EXISTS adopted_by, DROP COLUMN IF EXISTS recorded_by;
-- ═════════════════════════════════════════════════════════════════════════
