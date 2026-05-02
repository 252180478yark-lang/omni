-- Top 素材反向分析 (Top Material Reverse-Analysis) — MVP
-- 目标：上传外部高 CTR 素材 → vision 反向分析结构化 → 聚类 → 产出 prompt 模板池
--
-- 编号 006；与 005 风格保持一致：
--   * 全部 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS，可重复执行
--   * 新表落在 content_studio schema（与 briefs / pipelines / digital_humans 同 schema）
--   * 嵌入字段使用 VECTOR(1536)（pgvector，已被 knowledge.knowledge_chunks 使用）
--
-- 表关系：
--   seed_materials 1 ── n material_reconstructions
--   template_analysis_tasks 1 ── n material_reconstructions
--   template_analysis_tasks 1 ── n prompt_templates
--   material_reconstructions n ── n prompt_templates  (通过 prompt_templates.source_reconstruction_ids 数组)

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ───────────────────────────────────────────────────────────────────────────
-- 1) seed_materials: 用户上传的种子素材（冷启动数据源）
--    目前没有真实回流数据，先用"上传 + 手填 CTR"的方式喂入。
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content_studio.seed_materials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    video_url TEXT,
    cover_url TEXT,
    material_type TEXT NOT NULL DEFAULT 'video',  -- video / image
    source TEXT NOT NULL DEFAULT 'manual',         -- manual / douyin / competitor / creative_center / internal
    source_url TEXT,
    product_category TEXT,                          -- 美妆 / 家居 / 3C / ...
    duration_seconds INT,
    aspect_ratio TEXT,                              -- 9:16 / 1:1 / 16:9
    -- 手工录入的指标（真数据回流后可对齐 ad_review.materials）
    ctr NUMERIC(10,6),
    cvr NUMERIC(10,6),
    play_3s_rate NUMERIC(10,6),
    completion_rate NUMERIC(10,6),
    gmv NUMERIC(14,2),
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT,
    uploaded_by TEXT,
    status TEXT NOT NULL DEFAULT 'active',          -- active / archived
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seed_materials_category
    ON content_studio.seed_materials (product_category);
CREATE INDEX IF NOT EXISTS idx_seed_materials_ctr
    ON content_studio.seed_materials (ctr DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_seed_materials_status
    ON content_studio.seed_materials (status);
CREATE INDEX IF NOT EXISTS idx_seed_materials_created
    ON content_studio.seed_materials (created_at DESC);


-- ───────────────────────────────────────────────────────────────────────────
-- 2) template_analysis_tasks: 异步分析任务（采集 → vision → 聚类）
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content_studio.template_analysis_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_type TEXT NOT NULL DEFAULT 'analyze_and_cluster',  -- analyze / cluster / analyze_and_cluster
    -- 输入选择
    input_seed_material_ids UUID[] NOT NULL DEFAULT '{}',
    product_category TEXT,
    top_n INT,                                              -- NULL 表示全部输入
    -- vision 参数
    vision_provider TEXT NOT NULL DEFAULT 'gemini',
    vision_model TEXT NOT NULL DEFAULT 'gemini-2.5-pro',
    -- 聚类参数
    cluster_algorithm TEXT NOT NULL DEFAULT 'kmeans',
    cluster_k INT,                                          -- NULL → 用 silhouette 自动选
    min_cluster_size INT NOT NULL DEFAULT 2,
    -- 状态
    status TEXT NOT NULL DEFAULT 'pending',                 -- pending / analyzing / clustering / done / failed / cancelled
    progress JSONB NOT NULL DEFAULT '{}'::jsonb,            -- {analyzed: 12, total: 50, current_step: "vision"}
    result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,      -- {reconstruction_count: N, template_count: M}
    output_template_ids UUID[] NOT NULL DEFAULT '{}',
    error TEXT,
    triggered_by TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_template_tasks_status
    ON content_studio.template_analysis_tasks (status);
CREATE INDEX IF NOT EXISTS idx_template_tasks_created
    ON content_studio.template_analysis_tasks (created_at DESC);


-- ───────────────────────────────────────────────────────────────────────────
-- 3) material_reconstructions: 单素材的 vision 反向分析结果
--    一个 seed_material 可被多次重新分析（换更强的 vision model），用 analysis_version 区分
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content_studio.material_reconstructions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    seed_material_id UUID NOT NULL,
    task_id UUID,                                       -- 来自哪个批量任务，可空（手动单条触发）
    -- vision provider
    vision_provider TEXT NOT NULL DEFAULT 'gemini',
    vision_model TEXT NOT NULL DEFAULT 'gemini-2.5-pro',
    analysis_version INT NOT NULL DEFAULT 1,
    -- 原始 + 结构化输出
    raw_analysis JSONB NOT NULL DEFAULT '{}'::jsonb,    -- vision 原文（含 token / latency）
    structured JSONB NOT NULL DEFAULT '{}'::jsonb,      -- {hook, scenes:[...], cta, character, product_focus, pace, style, tone}
    -- 摘要字段（structured 的常用维度提取出来便于聚类与 SQL 过滤）
    hook_text TEXT,
    scene_count INT,
    pace TEXT,                                           -- slow / medium / fast
    style TEXT,                                          -- 对齐 prompt_templates.STYLE_DESCRIPTIONS keys
    tone TEXT,
    visual_elements JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {camera_angles:[], colors:[], composition:""}
    detected_components JSONB NOT NULL DEFAULT '{}'::jsonb, -- {has_face:true, has_product_closeup:true, ...}
    -- 重建用 prompt 草稿
    prompt_blueprint TEXT,
    -- 用于聚类的向量
    embedding VECTOR(1536),
    -- 状态
    status TEXT NOT NULL DEFAULT 'pending',              -- pending / analyzing / done / failed
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recon_seed
    ON content_studio.material_reconstructions (seed_material_id);
CREATE INDEX IF NOT EXISTS idx_recon_task
    ON content_studio.material_reconstructions (task_id);
CREATE INDEX IF NOT EXISTS idx_recon_status
    ON content_studio.material_reconstructions (status);
CREATE INDEX IF NOT EXISTS idx_recon_style
    ON content_studio.material_reconstructions (style);
CREATE INDEX IF NOT EXISTS idx_recon_created
    ON content_studio.material_reconstructions (created_at DESC);

-- FK 约束（DO $$ 包裹，避免重复执行报错）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'content_studio'
          AND table_name = 'material_reconstructions'
          AND constraint_name = 'fk_recon_seed'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT fk_recon_seed
            FOREIGN KEY (seed_material_id)
            REFERENCES content_studio.seed_materials(id) ON DELETE CASCADE;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'content_studio'
          AND table_name = 'material_reconstructions'
          AND constraint_name = 'fk_recon_task'
    ) THEN
        ALTER TABLE content_studio.material_reconstructions
            ADD CONSTRAINT fk_recon_task
            FOREIGN KEY (task_id)
            REFERENCES content_studio.template_analysis_tasks(id) ON DELETE SET NULL;
    END IF;
END $$;


-- ───────────────────────────────────────────────────────────────────────────
-- 4) prompt_templates: 聚类后产出的 prompt 模板池（每个 cluster 一行）
--    支持版本树（parent_template_id），新增改版 = 新建一行 + 指向 parent
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content_studio.prompt_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version INT NOT NULL DEFAULT 1,
    parent_template_id UUID NULL,
    -- 元信息
    name TEXT NOT NULL,
    summary TEXT,
    problem_domain TEXT NOT NULL DEFAULT 'creative',   -- creative / script / scene / hook / ...
    product_category TEXT,
    style TEXT,                                          -- 对齐 STYLE_DESCRIPTIONS
    tone TEXT,
    pace TEXT,
    target_modality TEXT NOT NULL DEFAULT 'scene_to_video',  -- copy / script / scene_to_image / scene_to_video / image / video
    -- prompt 主体
    prompt_body TEXT NOT NULL,                           -- 含 {{placeholders}}
    placeholders JSONB NOT NULL DEFAULT '[]'::jsonb,     -- [{key,desc,required,example}]
    example_output TEXT,
    -- 聚类来源
    cluster_id INT,                                      -- k-means cluster label
    centroid_embedding VECTOR(1536),
    source_material_ids UUID[] NOT NULL DEFAULT '{}',
    source_reconstruction_ids UUID[] NOT NULL DEFAULT '{}',
    support_count INT NOT NULL DEFAULT 0,                -- cluster 内样本数
    -- 来自 source 素材的指标平均（冷启动期的"模板潜力分"代理）
    avg_ctr NUMERIC(10,6),
    avg_cvr NUMERIC(10,6),
    -- 来自下游真实使用的反馈（Phase 3 才会有数据）
    usage_count INT NOT NULL DEFAULT 0,
    ctr_observed NUMERIC(10,6),
    cvr_observed NUMERIC(10,6),
    confidence NUMERIC(6,3) NOT NULL DEFAULT 0,
    -- 生命周期
    status TEXT NOT NULL DEFAULT 'draft',                -- draft / active / archived / refuted
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    author TEXT,                                          -- system / human:<email>
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tpl_status
    ON content_studio.prompt_templates (status);
CREATE INDEX IF NOT EXISTS idx_tpl_modality
    ON content_studio.prompt_templates (target_modality);
CREATE INDEX IF NOT EXISTS idx_tpl_category
    ON content_studio.prompt_templates (product_category);
CREATE INDEX IF NOT EXISTS idx_tpl_style
    ON content_studio.prompt_templates (style);
CREATE INDEX IF NOT EXISTS idx_tpl_parent
    ON content_studio.prompt_templates (parent_template_id);
CREATE INDEX IF NOT EXISTS idx_tpl_avg_ctr
    ON content_studio.prompt_templates (avg_ctr DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tpl_created
    ON content_studio.prompt_templates (created_at DESC);

-- 数组成员检索（按 source 素材反查模板）
CREATE INDEX IF NOT EXISTS idx_tpl_source_materials
    ON content_studio.prompt_templates USING GIN (source_material_ids);
CREATE INDEX IF NOT EXISTS idx_tpl_source_recons
    ON content_studio.prompt_templates USING GIN (source_reconstruction_ids);

-- 父子版本链
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'content_studio'
          AND table_name = 'prompt_templates'
          AND constraint_name = 'fk_tpl_parent'
    ) THEN
        ALTER TABLE content_studio.prompt_templates
            ADD CONSTRAINT fk_tpl_parent
            FOREIGN KEY (parent_template_id)
            REFERENCES content_studio.prompt_templates(id) ON DELETE SET NULL;
    END IF;
END $$;


-- ───────────────────────────────────────────────────────────────────────────
-- 注释
-- ───────────────────────────────────────────────────────────────────────────
COMMENT ON TABLE content_studio.seed_materials IS
    '用户上传的种子素材（冷启动数据源）；CTR/CVR 由用户手填，后续可与 ad_review.materials 真数据对齐';
COMMENT ON TABLE content_studio.template_analysis_tasks IS
    '反向分析批量任务：采集 Top N → vision 分析 → k-means 聚类 → 产出 prompt 模板';
COMMENT ON TABLE content_studio.material_reconstructions IS
    '单素材 vision 反向分析的结构化结果；embedding 字段供聚类使用';
COMMENT ON TABLE content_studio.prompt_templates IS
    '聚类后的 prompt 模板池；status=draft 需人工审核才进入 active；usage_count / ctr_observed 由 Phase 3 回灌';
