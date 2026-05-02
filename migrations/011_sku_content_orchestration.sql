-- Migration 011: SKU 内容编排
-- 目标：把 17 步链路（SKU → 卖点 → 人群 → 画像 → 圈包 → 偏好 → 目的 → 脚本 → Brief → 分镜 → 视频）落数据
-- 适用：路径 A v1.5 + 内容工坊 v2

-- ═══ 1. mvp_sku 加老板视角字段 ═══
ALTER TABLE IF EXISTS public.mvp_sku
    ADD COLUMN IF NOT EXISTS owner_selling_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS owner_notes TEXT,
    ADD COLUMN IF NOT EXISTS price_min NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS price_max NUMERIC(12,2);

COMMENT ON COLUMN public.mvp_sku.owner_selling_points IS '老板手填的产品卖点列表 [{text, category, priority}]';
COMMENT ON COLUMN public.mvp_sku.owner_notes IS '老板备注（场景/原料/工艺等任意文字）';

-- ═══ 2. briefs 三类 USP + 目的分流 + 偏好内容 + SKU 关联 ═══
ALTER TABLE IF EXISTS content_studio.briefs
    ADD COLUMN IF NOT EXISTS usp_explicit JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS usp_implicit JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS usp_unique JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS target_purpose VARCHAR(16),
    ADD COLUMN IF NOT EXISTS audience_content_preference JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS sku_id VARCHAR(64);

COMMENT ON COLUMN content_studio.briefs.usp_explicit IS '显性卖点 [{point, evidence, priority}] 客户一眼看到的';
COMMENT ON COLUMN content_studio.briefs.usp_implicit IS '隐性卖点 [{point, evidence, priority}] 需引导才感知';
COMMENT ON COLUMN content_studio.briefs.usp_unique IS '独特卖点 [{point, evidence, priority}] 区别同类竞品的';
COMMENT ON COLUMN content_studio.briefs.target_purpose IS 'awareness 曝光 / planting 种草 / conversion 收割';
COMMENT ON COLUMN content_studio.briefs.audience_content_preference IS '{topics, formats, styles, hooks} 该人群喜欢看的内容画像';
COMMENT ON COLUMN content_studio.briefs.sku_id IS '路径 A mvp_sku.id 直连（不经 product_id 中转）';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'briefs_target_purpose_check'
          AND table_schema = 'content_studio'
    ) THEN
        ALTER TABLE content_studio.briefs
            ADD CONSTRAINT briefs_target_purpose_check
            CHECK (target_purpose IS NULL OR target_purpose IN ('awareness', 'planting', 'conversion'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_briefs_sku_id ON content_studio.briefs (sku_id) WHERE sku_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_briefs_target_purpose ON content_studio.briefs (target_purpose) WHERE target_purpose IS NOT NULL;

-- ═══ 3. pipelines 加跳过合成开关 ═══
ALTER TABLE IF EXISTS content_studio.pipelines
    ADD COLUMN IF NOT EXISTS skip_final_concat BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS sku_id VARCHAR(64);

COMMENT ON COLUMN content_studio.pipelines.skip_final_concat IS '跳过 ffmpeg 合成 final.mp4，仅打包 10 段独立视频供人工剪辑';
COMMENT ON COLUMN content_studio.pipelines.sku_id IS '回溯 SKU 来源（路径 A mvp_sku.id）';

CREATE INDEX IF NOT EXISTS idx_pipelines_sku_id ON content_studio.pipelines (sku_id) WHERE sku_id IS NOT NULL;

-- ═══ 4. SKU 内容编排状态机表 ═══
CREATE TABLE IF NOT EXISTS content_studio.sku_orchestrations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id VARCHAR(64) NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress',           -- in_progress / paused / completed / failed
    current_step TEXT NOT NULL DEFAULT 'selling_points',  -- 见 17 步状态机说明
    target_purpose VARCHAR(16),                            -- 老板提前选；NULL 时由 LLM 推荐

    -- 各步产物（按步骤名）
    selling_points_result JSONB,                           -- 三类 USP 分析结果
    matched_audience_result JSONB,                         -- 人群匹配结果
    audience_profile_result JSONB,                         -- 人群画像分析
    dmp_sop_result TEXT,                                   -- 圈包策略
    audience_content_pref_result JSONB,                    -- 人群偏好内容
    script_result JSONB,                                   -- 短视频脚本

    -- 链接产物
    linked_brief_id UUID NULL,                             -- → content_studio.briefs.id
    linked_pipeline_id UUID NULL,                          -- → content_studio.pipelines.id

    -- 步骤产物的 LLM 调用元信息（每步调了什么模型、消耗多少 token）
    step_meta JSONB NOT NULL DEFAULT '{}'::jsonb,

    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT sku_orchestrations_status_check
        CHECK (status IN ('in_progress', 'paused', 'completed', 'failed')),
    CONSTRAINT sku_orchestrations_target_purpose_check
        CHECK (target_purpose IS NULL OR target_purpose IN ('awareness', 'planting', 'conversion'))
);

CREATE INDEX IF NOT EXISTS idx_sku_orch_sku_status ON content_studio.sku_orchestrations (sku_id, status);
CREATE INDEX IF NOT EXISTS idx_sku_orch_created ON content_studio.sku_orchestrations (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sku_orch_brief ON content_studio.sku_orchestrations (linked_brief_id) WHERE linked_brief_id IS NOT NULL;

COMMENT ON TABLE content_studio.sku_orchestrations IS 'SKU 内容编排：从 SKU 起步 → 自动跑卖点/人群/画像/圈包/偏好/脚本 6 步 → 落地 Brief 与 Pipeline';
COMMENT ON COLUMN content_studio.sku_orchestrations.current_step IS '17 步状态机：selling_points → audience_match → audience_profile → dmp_sop → content_preference → purpose_routing → script → brief_built → pipeline_linked → completed';

-- ═══ 5. updated_at 自动更新触发器 ═══
CREATE OR REPLACE FUNCTION content_studio.touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sku_orch_touch ON content_studio.sku_orchestrations;
CREATE TRIGGER trg_sku_orch_touch
    BEFORE UPDATE ON content_studio.sku_orchestrations
    FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
