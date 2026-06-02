-- Migration 022: SKU 关键词扩展包（W4-B 切片 14.3 phase B+）
--
-- 目标：把"输入种子词 → 输出 500 词（一行一词无标点）"的能力沉淀，可下载、可挂链路。
-- 用途：粘贴进巨量千川/巨量云图后台的关键词定向（要求纯文本格式）。
--
-- 设计：
--   - 可选挂 audience_record_id / audience_pack_id（关联人群/圈包）
--   - sku_id 必填（最终复盘锚点）
--   - keyword_text 是清洗后的纯文本（每行 1 词，无标点）
--   - keyword_count denorm 实际词数（target 500，不够也存）
--   - 多版本 + 状态 + parent_id 串前后

CREATE TABLE IF NOT EXISTS pipeline.keyword_packs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- 链路（都可空，至少 sku_id 必填）
    audience_record_id UUID REFERENCES pipeline.audience_records(id) ON DELETE SET NULL,
    audience_pack_id UUID REFERENCES pipeline.audience_packs(id) ON DELETE SET NULL,
    sku_id VARCHAR(64) NOT NULL,

    -- 输入
    seed_keywords TEXT NOT NULL,     -- 老板输入的种子词（'\n' 分隔，原样保留）

    -- 输出
    keyword_text TEXT NOT NULL,      -- 清洗后纯文本，每行 1 词无标点
    keyword_count INTEGER NOT NULL DEFAULT 0,
    target_count INTEGER NOT NULL DEFAULT 500,

    -- 入参备份
    extra_context TEXT,

    -- LLM trace
    model_provider TEXT,
    model TEXT,
    prompt_hash TEXT,
    cost_estimate TEXT,

    -- 版本/状态
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    parent_pack_id UUID REFERENCES pipeline.keyword_packs(id) ON DELETE SET NULL,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT keyword_packs_status_check
        CHECK (status IN ('draft', 'adopted', 'archived')),
    CONSTRAINT keyword_packs_version_pos
        CHECK (version >= 1),
    CONSTRAINT keyword_packs_count_nonneg
        CHECK (keyword_count >= 0 AND target_count > 0)
);

CREATE INDEX IF NOT EXISTS idx_keyword_packs_sku
    ON pipeline.keyword_packs (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_keyword_packs_record
    ON pipeline.keyword_packs (audience_record_id) WHERE audience_record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_keyword_packs_pack
    ON pipeline.keyword_packs (audience_pack_id) WHERE audience_pack_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_keyword_packs_status
    ON pipeline.keyword_packs (status) WHERE status = 'adopted';

COMMENT ON TABLE pipeline.keyword_packs IS '500 词关键词扩展包，可下载粘贴进巨量千川/云图关键词定向后台';
COMMENT ON COLUMN pipeline.keyword_packs.keyword_text IS '清洗后的纯文本：每行 1 个关键词、无标点、去重、长度 2-15 字';

-- 触发器
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_pipeline_keyword_packs_touch ON pipeline.keyword_packs;
        CREATE TRIGGER trg_pipeline_keyword_packs_touch
            BEFORE UPDATE ON pipeline.keyword_packs
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;
