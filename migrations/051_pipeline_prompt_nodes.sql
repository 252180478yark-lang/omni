-- ============================================================
-- Migration 051: sku-pipeline 接入 prompt 反馈飞轮
--
-- 背景（2026-06-15 loop engineering 第一件事·搭桥）：
-- prompt_rules 飞轮（migration 007）的注入机制 render_rules_suffix 已在 19 个老
-- 节点（briefs/content/review/chat/harvester）跑通，但 sku-pipeline 的 5 个核心
-- 生成工具从未接入——既没注入口、连 node_id 都没建。本 migration：
--   1. 给 5 个 sku-pipeline 生成工具补 prompt_nodes 行
--      （否则 prompt_rules.node_id 外键无处可挂，规则写不进去）
--   2. 给 prompt_rules 加 source_tool_call_id：记一条规则源自 mcp.tool_calls 的
--      哪条差评——这是【新世界 mcp.* 反馈 → 旧世界 knowledge.prompt_rules 规则】
--      的单向桥锚点，用于：① 已提炼过的差评不再被 list_unprocessed_complaints 重复捞
--      ② 后续规则效果回溯（规则生效前后该工具 bad 率对照）。
--
-- 纯加法、幂等（ON CONFLICT DO NOTHING / ADD COLUMN IF NOT EXISTS）。
-- ============================================================

-- ────────────────────────────────────────────────────────
-- 1. 5 个 sku-pipeline 生成节点（category='sku_pipeline'）
-- ────────────────────────────────────────────────────────
INSERT INTO knowledge.prompt_nodes (id, title, description, page, category) VALUES
    ('pipeline.selling_points_matrix', 'sku-pipeline · 卖点矩阵 (step 2)',  '7 要素微剧本 × N 卖点 + 5 心智 + 标签矩阵',                       '/sku-pipeline', 'sku_pipeline'),
    ('pipeline.audience_match',        'sku-pipeline · 人群匹配 (step 3)',   'KB 反向推理 ≥15 人群 + 结构化标签汇总',                          '/sku-pipeline', 'sku_pipeline'),
    ('pipeline.audience_portrait',     'sku-pipeline · 人群画像 (step 3.5)', '人群生活状态画像，KB 锚 + 可信度分级标注（[KB:]/🧠/⚠️）',        '/sku-pipeline', 'sku_pipeline'),
    ('pipeline.director_brief',        'sku-pipeline · 编导 brief (step 3.6)', '编导备忘录 + 算法信号三向量 + 一大段 AI 出片提示词',             '/sku-pipeline', 'sku_pipeline'),
    ('pipeline.creative_pack',         'sku-pipeline · 创意素材 (step 5)',   '6 类素材脚本（视频软广/种草/收割 + 图文收割 + 主图 + 详情页）',  '/sku-pipeline', 'sku_pipeline')
ON CONFLICT (id) DO NOTHING;


-- ────────────────────────────────────────────────────────
-- 2. prompt_rules 加 source_tool_call_id（新世界差评 → 规则的桥锚）
--    无 FK：mcp.tool_calls 跨 schema 且可能被清理，FK 会拖累；做成软引用。
-- ────────────────────────────────────────────────────────
ALTER TABLE knowledge.prompt_rules
    ADD COLUMN IF NOT EXISTS source_tool_call_id UUID;

COMMENT ON COLUMN knowledge.prompt_rules.source_tool_call_id IS
    '若规则源自 mcp.tool_calls 某条差评（新世界反馈→规则的桥），记该 tool_call_id；手动建/老飞轮 prompt_feedbacks 来源时为 NULL。无 FK（跨 schema + tool_calls 可被清理）。';

CREATE INDEX IF NOT EXISTS idx_prompt_rules_source_tool_call
    ON knowledge.prompt_rules(source_tool_call_id)
    WHERE source_tool_call_id IS NOT NULL;
