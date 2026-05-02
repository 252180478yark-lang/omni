-- ============================================================
-- Migration 007: Prompt Feedback Flywheel
--
-- 为所有"用户能点到的 LLM 功能"提供统一的反馈/规则/日志机制：
--   • prompt_nodes     — 预设 19 个节点的元数据清单
--   • prompt_feedbacks — 每次生成的留痕 + 用户反馈 + LLM 提炼草稿
--   • prompt_rules    — 用户确认入库的"修正规则"，按节点分组
--
-- 关键设计：
--   1. 每节点独立规则集（review.stage_a 的规则不污染 content.copy）
--   2. rule 可按 scope (JSONB) 做细分（如只对 "style: grassplanting" 生效）
--   3. feedback 永久保留作日志，规则可随时禁用/删除不影响反馈历史
--   4. hit_count / last_hit_at 用于识别"哪些规则真在起作用"
-- ============================================================

CREATE SCHEMA IF NOT EXISTS knowledge;

-- ────────────────────────────────────────────────────────
-- 1. 预设节点清单
-- ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS knowledge.prompt_nodes (
    id          TEXT PRIMARY KEY,      -- 'review.stage_a' / 'content.copy' / 'chat.rag' …
    title       TEXT NOT NULL,         -- 人类可读名
    description TEXT,
    page        TEXT,                  -- 对应前端页面，如 '/ad-review/[id]'
    category    TEXT,                  -- 'ad_review' / 'content_studio' / 'chat' / 'analysis' / 'knowledge' / 'news'
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO knowledge.prompt_nodes (id, title, description, page, category) VALUES
    -- 投放复盘
    ('review.stage_a',              '投放复盘 · Stage A 诊断',        '结构化 JSON 诊断（三角匹配 + eCPM + 归因）',           '/ad-review/[id]',         'ad_review'),
    ('review.stage_b',              '投放复盘 · Stage B 渲染',        '将诊断 JSON 渲染为 Markdown 报告',                        '/ad-review/[id]',         'ad_review'),
    ('review.file_parser',          '投放复盘 · 人群/圈包文件摘要',  '上传文件（人群画像/圈包手法/通用）的 LLM 结构化摘要',     '/ad-review/[id]',         'ad_review'),
    -- 内容工坊
    ('content.copy',                '营销文案生成',                    '根据运营方案生成 150-300 字短视频文案',                    '/content-studio',         'content_studio'),
    ('content.script',              '分镜脚本生成',                    '将文案拆为结构化 JSON 脚本（场景/镜头/旁白）',             '/content-studio',         'content_studio'),
    ('content.script_analysis',     '脚本分析（抽角色/产品出现）',   '从脚本提取人物档案和产品出现场次',                          '/content-studio',         'content_studio'),
    ('content.character_face',      '角色人脸底图 prompt',            '生成保持一致性的角色头像 prompt（英文）',                  '/content-studio',         'content_studio'),
    ('content.scene_to_image',      '分镜→图像 prompt 翻译',          'LLM 把中文分镜描述转为英文图像生成 prompt',                '/content-studio',         'content_studio'),
    ('content.scene_to_video',      '分镜→Seedance 视频 prompt',      'LLM 把分镜转为 Seedance 2.0 视频生成 prompt（中文）',      '/content-studio',         'content_studio'),
    -- Brief / Avatar
    ('briefs.draft',                'Brief 草稿生成',                  '三 KB 召回 + 产品信息生成结构化 Brief',                    '/content-studio/briefs/new', 'content_studio'),
    ('digital_humans.angles',       '数字人多角度底图',                'front/45/side/half_body 四角度的数字人 prompt',             '/content-studio/avatars', 'content_studio'),
    -- 智能问答
    ('chat.rag',                    '智能问答（RAG）',                '带知识库 + persona 的对话生成',                            '/chat',                   'chat'),
    ('chat.persona',                '预设 Persona 身份',              '9 个预设角色（电商运营 / 新媒体 / 投放优化 / …）',         '/chat',                   'chat'),
    ('chat.roundtable_moderator',   '圆桌主持人总结',                  '多角色讨论后的结构化决策报告',                              '/chat',                   'chat'),
    -- 多模态分析
    ('video.analyze',               '短视频分析',                      'Gemini 多模态视频分析 + 9 维评分',                          '/video-analysis',         'analysis'),
    ('livestream.analyze',          '直播切片分析',                    'Gemini 直播分段 + 逐字稿 + 背景/贴片识别',                 '/livestream-analysis',    'analysis'),
    -- 知识采集
    ('harvester.image',             '知识库图片自动解读',              'VLM 描述爬取/上传图片内容',                                 '/knowledge',              'knowledge'),
    -- 资讯
    ('news.enrich',                 '资讯自动摘要/标签/打分',         '批量文章的 summary_zh + tags + relevance_score',           '/news',                   'news')
ON CONFLICT (id) DO NOTHING;


-- ────────────────────────────────────────────────────────
-- 2. 反馈日志（每次生成留痕 + 用户吐槽 + LLM 提炼草稿）
-- ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS knowledge.prompt_feedbacks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id       TEXT NOT NULL REFERENCES knowledge.prompt_nodes(id) ON DELETE CASCADE,
    input_ref     JSONB,                 -- 业务侧引用：{campaign_id, pipeline_id, chat_msg_id, ...}
    full_prompt   TEXT,                  -- 实际发给模型的完整 prompt（供调试/溯源）
    output        TEXT,                  -- 实际生成结果（截断到 20K 字符）
    rating        SMALLINT,              -- +1 满意 / 0 中性 / -1 不满意
    severity      TEXT,                  -- 'minor' / 'must_fix' / 'ignorable'（仅 rating=-1 时有效）
    complaint     TEXT,                  -- 用户输入的"哪里不对"
    distilled     TEXT,                  -- LLM 从 complaint 提炼出的规则草稿
    applied_as    UUID,                  -- 若已成规则，指向 prompt_rules.id
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prompt_feedbacks_node_created
    ON knowledge.prompt_feedbacks(node_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_prompt_feedbacks_rating
    ON knowledge.prompt_feedbacks(node_id, rating, created_at DESC)
    WHERE rating IS NOT NULL;


-- ────────────────────────────────────────────────────────
-- 3. 修正规则（生效中的补丁，按节点 + 可选 scope 分组）
-- ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS knowledge.prompt_rules (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id       TEXT NOT NULL REFERENCES knowledge.prompt_nodes(id) ON DELETE CASCADE,
    rule_text     TEXT NOT NULL,
    scope         JSONB,                 -- 可选细分，如 {"style": "grassplanting"} 只对种草文案生效
    created_from  UUID REFERENCES knowledge.prompt_feedbacks(id) ON DELETE SET NULL,
    hit_count     INT DEFAULT 0,         -- 被使用次数（render_rules_suffix 计数）
    enabled       BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_hit_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_prompt_rules_node_enabled
    ON knowledge.prompt_rules(node_id, enabled, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_prompt_rules_scope_gin
    ON knowledge.prompt_rules USING GIN(scope);


-- ────────────────────────────────────────────────────────
-- 4. updated_at 触发器（仅用于 prompt_nodes）
-- ────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION knowledge.touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS prompt_nodes_touch ON knowledge.prompt_nodes;
CREATE TRIGGER prompt_nodes_touch
    BEFORE UPDATE ON knowledge.prompt_nodes
    FOR EACH ROW EXECUTE FUNCTION knowledge.touch_updated_at();
