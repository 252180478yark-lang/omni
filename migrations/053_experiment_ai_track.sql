-- ============================================================
-- Migration 053: AI 短视频链接入实验台账（Y 形融合）+ 投前视觉快环
--
-- 背景（2026-06-15）：编导 brief A/B 闭环（052）做完后，AI 出片链照搬同一条实验
-- 尾巴——不是新链，是让"臂"也能是 AI 视频。两条链共享 SKU→卖点→人群→画像 主干 +
-- 实验/投后/沉淀 尾巴，只在"生产模式"分叉（真人 brief / AI 提示词）。
--
--   ① experiments.track       这个实验跑哪条生产链（human_brief / ai_video / mixed=真人vsAI对比）
--   ② experiment_arms.production_mode  该臂由哪条链产出（单模式=继承 track；mixed 才逐臂不同）
--   ③ assets.visual_prescreen 投前视觉快环打分（保真/真人感/锁脸/品牌/可用）——代理指标，
--      独立于 ad_metrics（投后真值），不进北极星聚合，只做投前过滤
--
-- 设计稿 docs/design-director-brief-ab-loop.md「Y 形融合」+ CLAUDE.md 专节。纯加法幂等。
-- ============================================================

-- ① experiments.track
ALTER TABLE pipeline.experiments ADD COLUMN IF NOT EXISTS track TEXT NOT NULL DEFAULT 'human_brief';
ALTER TABLE pipeline.experiments DROP CONSTRAINT IF EXISTS experiments_track_check;
ALTER TABLE pipeline.experiments ADD CONSTRAINT experiments_track_check
    CHECK (track IN ('human_brief', 'ai_video', 'mixed'));
COMMENT ON COLUMN pipeline.experiments.track IS
    '生产链：human_brief(真人编导 brief→拍) / ai_video(AI 提示词→出片) / mixed(同实验 A/B 真人 vs AI)。决定 distill 写哪个 prompt 节点。';

-- ② experiment_arms.production_mode
ALTER TABLE pipeline.experiment_arms ADD COLUMN IF NOT EXISTS production_mode TEXT;
ALTER TABLE pipeline.experiment_arms DROP CONSTRAINT IF EXISTS experiment_arms_mode_check;
ALTER TABLE pipeline.experiment_arms ADD CONSTRAINT experiment_arms_mode_check
    CHECK (production_mode IS NULL OR production_mode IN ('human_brief', 'ai_video'));
COMMENT ON COLUMN pipeline.experiment_arms.production_mode IS
    '该臂产出链：单模式实验继承 experiment.track；mixed 实验（swept_variable=production_mode）逐臂不同。NULL=继承 track。';

-- ③ assets.visual_prescreen
ALTER TABLE pipeline.assets ADD COLUMN IF NOT EXISTS visual_prescreen JSONB NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN pipeline.assets.visual_prescreen IS
    '投前视觉快环多模态 judge 打分（保真/真人感/锁脸/品牌/可用 + gate + reason）。代理指标、非投放真值——不进北极星聚合，只做投前过滤收敛技术类提示词变量。';
