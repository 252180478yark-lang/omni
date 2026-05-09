-- Migration 021: SKU 出片链路血缘（pipeline schema）
-- W4-B 切片 14.3 phase A
--
-- 目标：把 sku-pipeline 整条链路（卖点矩阵 → 人群报告 → 单人群 → 圈包 → 脚本 → 分镜图/视频）
--      落库，每张表 denorm sku_id，让"投后视频回传 → 反查 SKU/卖点/人群"一句 SQL 出。
--
-- 核心设计：
--   1. 每步多版本：重跑 = 新行（version 自增 + parent_*_id 串前后），不覆盖
--   2. 两态审批：跑完 status=draft；老板手动采纳后 status=adopted；只有 adopted 能挂下游
--   3. denorm sku_id 到每张表（就算 6 层链，最终复盘 SQL 不用 6 join）
--   4. step 3 audience_run 出整段 markdown + 同时拆 N 行 audience_record（每人群 1 行可独立挂下游）
--   5. assets 加 external_video_id + ad_metrics jsonb，投后回传锚点
--
-- 跟现有表的关系：
--   - 不动 content_studio.sku_orchestrations（17 步状态机塞 1 行 jsonb，跟"人群拆 N 行"模型不兼容；保留历史）
--   - 不动 ad_review.audience_packs（绑 campaign_id，是投后用；本表是投前链路）
--   - mvp_sku 是上游锚点（sku_id 全表外键）

CREATE SCHEMA IF NOT EXISTS pipeline;
COMMENT ON SCHEMA pipeline IS 'SKU 出片链路血缘：matrix → audience → record → pack → script → asset';


-- ════════════════════════════════════════════════════════════════
-- 1. pipeline.matrix_runs — step 2 卖点矩阵每次跑一行
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pipeline.matrix_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id VARCHAR(64) NOT NULL,
    matrix_md TEXT NOT NULL,

    -- 入参备份（重跑/复盘要看用了什么输入）
    user_initial_points TEXT,
    user_reviews TEXT,
    kb_context TEXT,
    extra_context TEXT,

    -- LLM trace 浓缩
    model_provider TEXT,
    model TEXT,
    prompt_hash TEXT,
    cost_estimate TEXT,

    -- 版本/状态
    status TEXT NOT NULL DEFAULT 'draft',  -- draft / adopted / archived
    version INTEGER NOT NULL DEFAULT 1,
    parent_run_id UUID REFERENCES pipeline.matrix_runs(id) ON DELETE SET NULL,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT matrix_runs_status_check
        CHECK (status IN ('draft', 'adopted', 'archived')),
    CONSTRAINT matrix_runs_version_pos
        CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_matrix_runs_sku
    ON pipeline.matrix_runs (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_matrix_runs_status
    ON pipeline.matrix_runs (status) WHERE status = 'adopted';
CREATE INDEX IF NOT EXISTS idx_matrix_runs_parent
    ON pipeline.matrix_runs (parent_run_id) WHERE parent_run_id IS NOT NULL;

COMMENT ON TABLE pipeline.matrix_runs IS 'step 2 卖点矩阵每次跑落一行，多版本支持重跑';


-- ════════════════════════════════════════════════════════════════
-- 2. pipeline.audience_runs — step 3 整段人群报告每次跑一行
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pipeline.audience_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    matrix_run_id UUID NOT NULL REFERENCES pipeline.matrix_runs(id) ON DELETE CASCADE,
    sku_id VARCHAR(64) NOT NULL,  -- denorm

    audience_md TEXT NOT NULL,
    recall_meta JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {mode, queries:[...], chunk_count, doc_count}
    record_count INTEGER NOT NULL DEFAULT 0,  -- 拆出多少个 audience_record

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
    parent_run_id UUID REFERENCES pipeline.audience_runs(id) ON DELETE SET NULL,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT audience_runs_status_check
        CHECK (status IN ('draft', 'adopted', 'archived')),
    CONSTRAINT audience_runs_version_pos
        CHECK (version >= 1),
    CONSTRAINT audience_runs_record_count_nonneg
        CHECK (record_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_audience_runs_sku
    ON pipeline.audience_runs (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audience_runs_matrix
    ON pipeline.audience_runs (matrix_run_id);
CREATE INDEX IF NOT EXISTS idx_audience_runs_status
    ON pipeline.audience_runs (status) WHERE status = 'adopted';

COMMENT ON TABLE pipeline.audience_runs IS 'step 3 人群匹配报告整段，挂 matrix_run；同时拆 N 行 audience_records';


-- ════════════════════════════════════════════════════════════════
-- 3. pipeline.audience_records — step 3 拆出来的每个人群一行
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pipeline.audience_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_run_id UUID NOT NULL REFERENCES pipeline.audience_runs(id) ON DELETE CASCADE,
    matrix_run_id UUID NOT NULL,  -- denorm 双跳
    sku_id VARCHAR(64) NOT NULL,  -- denorm

    ordinal SMALLINT NOT NULL,  -- 在 audience_run 里的序号（1..N）
    name TEXT NOT NULL,  -- 人群名（"理性主妇" / "银发当燃" 等）
    kb_doc TEXT,  -- KB 来源文档名（取自 [KB来源：xxx] 标签）
    kb_section TEXT,  -- 章节路径（取自 [文档:X|章节:Y>Z]）
    kb_chunk_text TEXT,  -- KB 原文段（1:1 粘贴，含 markdown）
    match_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ["卖点 1.1.2 [180天发酵] + 场景 2.1 → ...", ...]
    layer_tags JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ["食饮","母婴","银发"]
    raw_md_segment TEXT NOT NULL,  -- 整段从 #### 1.X 开始的原 markdown（前端可直接渲染）

    -- 状态
    status TEXT NOT NULL DEFAULT 'draft',  -- draft / adopted / archived
    selected_for_pack BOOLEAN NOT NULL DEFAULT FALSE,  -- 老板是否选了这个人群挂下游

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT audience_records_status_check
        CHECK (status IN ('draft', 'adopted', 'archived')),
    CONSTRAINT audience_records_ordinal_pos
        CHECK (ordinal >= 1)
);

CREATE INDEX IF NOT EXISTS idx_audience_records_run
    ON pipeline.audience_records (audience_run_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_audience_records_sku
    ON pipeline.audience_records (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audience_records_selected
    ON pipeline.audience_records (sku_id) WHERE selected_for_pack = TRUE;

COMMENT ON TABLE pipeline.audience_records IS 'step 3 拆出的每个人群一行，老板从中选 1 个挂 step 4 圈包';


-- ════════════════════════════════════════════════════════════════
-- 4. pipeline.audience_packs — step 4 圈包（针对单个人群）
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pipeline.audience_packs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_record_id UUID NOT NULL REFERENCES pipeline.audience_records(id) ON DELETE CASCADE,
    audience_run_id UUID NOT NULL,  -- denorm
    matrix_run_id UUID NOT NULL,  -- denorm
    sku_id VARCHAR(64) NOT NULL,  -- denorm

    pack_md TEXT NOT NULL,  -- step 4 LLM 输出的圈包 SOP markdown
    dmp_tags JSONB NOT NULL DEFAULT '[]'::jsonb,  -- 可勾选标签 [{"category":"行为兴趣","tag":"近30天搜过酱油","priority":"P0"}]
    budget_suggestion JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {"daily_budget":500,"split":...}

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
    parent_pack_id UUID REFERENCES pipeline.audience_packs(id) ON DELETE SET NULL,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT audience_packs_status_check
        CHECK (status IN ('draft', 'adopted', 'archived')),
    CONSTRAINT audience_packs_version_pos
        CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_audience_packs_record
    ON pipeline.audience_packs (audience_record_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audience_packs_sku
    ON pipeline.audience_packs (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audience_packs_status
    ON pipeline.audience_packs (status) WHERE status = 'adopted';

COMMENT ON TABLE pipeline.audience_packs IS 'step 4 圈包 SOP（绑单个 audience_record，不是 ad_review.audience_packs 那种投后）';


-- ════════════════════════════════════════════════════════════════
-- 5. pipeline.scripts — step 5/6 脚本
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pipeline.scripts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audience_pack_id UUID NOT NULL REFERENCES pipeline.audience_packs(id) ON DELETE CASCADE,
    audience_record_id UUID NOT NULL,  -- denorm
    matrix_run_id UUID NOT NULL,  -- denorm
    sku_id VARCHAR(64) NOT NULL,  -- denorm

    script_md TEXT NOT NULL,
    hooks JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{"hook_type":"开场","text":"..."}]
    scenes JSONB NOT NULL DEFAULT '[]'::jsonb,  -- 分镜清单 [{"scene_no":1,"prompt":"...","first_frame_hint":"..."}]
    target_purpose VARCHAR(16),  -- awareness / planting / conversion

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
    parent_script_id UUID REFERENCES pipeline.scripts(id) ON DELETE SET NULL,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT scripts_status_check
        CHECK (status IN ('draft', 'adopted', 'archived')),
    CONSTRAINT scripts_version_pos
        CHECK (version >= 1),
    CONSTRAINT scripts_target_purpose_check
        CHECK (target_purpose IS NULL OR target_purpose IN ('awareness', 'planting', 'conversion'))
);

CREATE INDEX IF NOT EXISTS idx_scripts_pack
    ON pipeline.scripts (audience_pack_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scripts_sku
    ON pipeline.scripts (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scripts_status
    ON pipeline.scripts (status) WHERE status = 'adopted';

COMMENT ON TABLE pipeline.scripts IS 'step 5/6 脚本 + 分镜，挂 audience_pack 双向可查链路';


-- ════════════════════════════════════════════════════════════════
-- 6. pipeline.assets — 分镜图/视频，投后数据回传锚点
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pipeline.assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- 链路（script_id 可空：直接调 generate_image 不经脚本也能记）
    script_id UUID REFERENCES pipeline.scripts(id) ON DELETE SET NULL,
    audience_pack_id UUID,  -- denorm 可空
    audience_record_id UUID,  -- denorm 可空
    matrix_run_id UUID,  -- denorm 可空
    sku_id VARCHAR(64) NOT NULL,  -- 必填，最终复盘 SQL 锚点

    -- 资产本体
    asset_type TEXT NOT NULL,  -- image / video
    file_url TEXT,
    thumbnail_url TEXT,
    prompt TEXT,
    duration_seconds NUMERIC(6,2),  -- video 才填
    scene_no SMALLINT,  -- 第几段分镜（关联 scripts.scenes[].scene_no）

    -- 投后绑定
    external_video_id TEXT,  -- 抖店/千川 上传后回传的 video_id
    external_creative_id TEXT,  -- 千川计划/创意 ID
    ad_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {"plays":xxx,"ctr":x,"cpm":x,"roi":x,"cost":x}
    last_metrics_at TIMESTAMPTZ,

    -- 状态
    status TEXT NOT NULL DEFAULT 'draft',  -- draft / adopted / published / discarded
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT assets_type_check
        CHECK (asset_type IN ('image', 'video')),
    CONSTRAINT assets_status_check
        CHECK (status IN ('draft', 'adopted', 'published', 'discarded')),
    CONSTRAINT assets_duration_nonneg
        CHECK (duration_seconds IS NULL OR duration_seconds >= 0)
);

CREATE INDEX IF NOT EXISTS idx_assets_sku
    ON pipeline.assets (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_script
    ON pipeline.assets (script_id) WHERE script_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_assets_external_video
    ON pipeline.assets (external_video_id) WHERE external_video_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_assets_external_creative
    ON pipeline.assets (external_creative_id) WHERE external_creative_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_assets_published
    ON pipeline.assets (sku_id) WHERE status = 'published';

COMMENT ON TABLE pipeline.assets IS '分镜图/视频，投后回传 ad_metrics → 一句 SELECT 反查 SKU/卖点/人群/圈包/脚本';


-- ════════════════════════════════════════════════════════════════
-- 触发器：updated_at 自动刷新（复用 content_studio.touch_updated_at）
-- ════════════════════════════════════════════════════════════════

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'content_studio' AND p.proname = 'touch_updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS trg_pipeline_matrix_runs_touch ON pipeline.matrix_runs;
        CREATE TRIGGER trg_pipeline_matrix_runs_touch
            BEFORE UPDATE ON pipeline.matrix_runs
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_pipeline_audience_runs_touch ON pipeline.audience_runs;
        CREATE TRIGGER trg_pipeline_audience_runs_touch
            BEFORE UPDATE ON pipeline.audience_runs
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_pipeline_audience_records_touch ON pipeline.audience_records;
        CREATE TRIGGER trg_pipeline_audience_records_touch
            BEFORE UPDATE ON pipeline.audience_records
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_pipeline_audience_packs_touch ON pipeline.audience_packs;
        CREATE TRIGGER trg_pipeline_audience_packs_touch
            BEFORE UPDATE ON pipeline.audience_packs
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_pipeline_scripts_touch ON pipeline.scripts;
        CREATE TRIGGER trg_pipeline_scripts_touch
            BEFORE UPDATE ON pipeline.scripts
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();

        DROP TRIGGER IF EXISTS trg_pipeline_assets_touch ON pipeline.assets;
        CREATE TRIGGER trg_pipeline_assets_touch
            BEFORE UPDATE ON pipeline.assets
            FOR EACH ROW EXECUTE FUNCTION content_studio.touch_updated_at();
    END IF;
END $$;


-- ════════════════════════════════════════════════════════════════
-- 链路反查视图（投后回传数据时一句 SELECT 拉全链路）
-- ════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW pipeline.v_asset_full_lineage AS
SELECT
    a.id AS asset_id,
    a.sku_id,
    a.asset_type,
    a.file_url,
    a.external_video_id,
    a.external_creative_id,
    a.ad_metrics,
    a.status AS asset_status,
    a.created_at AS asset_created_at,

    s.id AS script_id,
    s.script_md,
    s.target_purpose,

    p.id AS audience_pack_id,
    p.pack_md,
    p.dmp_tags,

    r.id AS audience_record_id,
    r.name AS audience_name,
    r.kb_doc AS audience_kb_doc,
    r.layer_tags AS audience_layer_tags,

    ar.id AS audience_run_id,
    ar.recall_meta AS audience_recall_meta,

    mr.id AS matrix_run_id,
    mr.matrix_md,

    sku.name AS sku_name,
    sku.category AS sku_category
FROM pipeline.assets a
LEFT JOIN pipeline.scripts s ON s.id = a.script_id
LEFT JOIN pipeline.audience_packs p ON p.id = a.audience_pack_id
LEFT JOIN pipeline.audience_records r ON r.id = a.audience_record_id
LEFT JOIN pipeline.audience_runs ar ON ar.id = r.audience_run_id
LEFT JOIN pipeline.matrix_runs mr ON mr.id = a.matrix_run_id
LEFT JOIN public.mvp_sku sku ON sku.id = a.sku_id;

COMMENT ON VIEW pipeline.v_asset_full_lineage IS '投后回传 ad_metrics 后，按 asset_id 一句 SELECT 拉 SKU/卖点/人群/圈包/脚本全链路';
