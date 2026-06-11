-- Migration 047: pipeline.audience_portraits（step 3.5 人群画像）+ scripts 支持 director_brief（step 3.6）
--
-- 链路：audience_record（step 3 老板选中）→ audience_portrait（step 3.5 生活状态画像+卖点重构）
--      → scripts kind='director_brief'（step 3.6 编导备忘录）
-- 设计 spec：docs/superpowers/specs/2026-06-11-audience-portrait-director-brief-design.md

-- 1. 画像表（列约定对齐 021 的 audience_runs：denorm sku_id / draft 两态 / 多版本 parent 串接）
CREATE TABLE IF NOT EXISTS pipeline.audience_portraits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_record_id UUID NOT NULL REFERENCES pipeline.audience_records(id) ON DELETE CASCADE,
    audience_run_id UUID,           -- denorm（从 audience_record 反查回填；record 链路断时允许 NULL，不设 FK 同 audience_packs 先例）
    matrix_run_id UUID,             -- denorm（同上）
    sku_id VARCHAR(64) NOT NULL,    -- denorm

    portrait_md TEXT NOT NULL,
    recall_meta JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {mode, routes:{...}, queries:[...], chunk_count}
    validation_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,  -- 标记配额闸检查结果

    -- 入参备份
    extra_context TEXT,
    kb_recall_override TEXT,

    -- LLM trace
    model_provider TEXT,
    model TEXT,
    prompt_hash TEXT,
    cost_estimate TEXT,

    -- 版本/状态
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    parent_portrait_id UUID REFERENCES pipeline.audience_portraits(id) ON DELETE SET NULL,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT audience_portraits_status_check
        CHECK (status IN ('draft', 'adopted', 'archived')),
    CONSTRAINT audience_portraits_version_pos
        CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_portraits_sku
    ON pipeline.audience_portraits (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_portraits_record
    ON pipeline.audience_portraits (audience_record_id);
CREATE INDEX IF NOT EXISTS idx_portraits_status
    ON pipeline.audience_portraits (status) WHERE status = 'adopted';

COMMENT ON TABLE pipeline.audience_portraits IS
    'step 3.5 人群生活状态画像（KB 锚+可信度分级标注+卖点重构+情绪触点矩阵）；多版本不覆盖';

-- 2. scripts：kind 枚举加 director_brief
ALTER TABLE pipeline.scripts DROP CONSTRAINT IF EXISTS scripts_kind_check;
ALTER TABLE pipeline.scripts ADD CONSTRAINT scripts_kind_check
    CHECK (kind IS NULL OR kind IN (
        'video_soft_ad',         -- 视频 · 软广（A2 触动 / 内容娱乐化软植入）
        'video_planting',        -- 视频 · 种草（A3 共鸣 / 讲产品力 + 我懂你）
        'video_harvest',         -- 视频 · 收割（A4 行动 / 限时 + 价格 + CTA）
        'graphic_harvest',       -- 图文 · 收割（小红书/抖店图文，转化导向）
        'product_main_image',    -- 商品视觉 · 主图（5-9 张冲击力 + 卖点叠加）
        'product_detail_page',   -- 商品视觉 · 详情页（叙事长图，卖点闭环）
        'director_brief'         -- 编导备忘录（step 3.6 真人拍+AI 映射两用）
    ));

-- 3. scripts：挂画像血缘
ALTER TABLE pipeline.scripts ADD COLUMN IF NOT EXISTS portrait_id UUID
    REFERENCES pipeline.audience_portraits(id) ON DELETE SET NULL;
COMMENT ON COLUMN pipeline.scripts.portrait_id IS
    '可选：挂 step 3.5 人群画像（director_brief 类必挂；其他 kind 为 NULL）';

-- 4. 触发器：audience_portraits 的 updated_at 自动刷新（照抄 021 的防御模式）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_pipeline_audience_portraits_touch ON pipeline.audience_portraits;
        CREATE TRIGGER trg_pipeline_audience_portraits_touch
            BEFORE UPDATE ON pipeline.audience_portraits
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;

-- 5. 更新 scripts.kind 注释（023 建表时 kind 为 NULL 历史行，现已扩到 7 类）
COMMENT ON COLUMN pipeline.scripts.kind IS
    '素材类型：7 类素材（video_soft_ad/planting/harvest, graphic_harvest, product_main_image, product_detail_page, director_brief）；NULL 表示历史行（14.3 phase A 时建表，未启用）';
