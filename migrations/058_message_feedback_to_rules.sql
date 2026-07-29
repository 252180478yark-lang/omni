-- ============================================================
-- Migration 058: 消息级差评接入 prompt 反馈飞轮（搭桥 A 半·2026-06-16）
--
-- 背景：omni 有两条反馈轨道，老板日常只走其中一条——
--   · 聊天气泡下方的 👎（消息级，常显好按）→ 落 mcp.message_feedback.note
--   · 工具 chip 上 hover 才出的 👎（工具级）       → 落 mcp.tool_calls.rating_note
-- 但提炼工具 list_unprocessed_complaints（migration 051）**只读 mcp.tool_calls**。
-- 实测：30 天里 sku-pipeline 261 次调用，工具级只评过 2 次；老板写的"为什么不合格"
-- 全在 message_feedback 里（如"挖卖点要场景强绑定""看不到心智了"），飞轮一条都看不见
-- → 老板"用了好多差评为什么找不到"。
--
-- 本 migration 补桥锚：prompt_rules 加 source_message_feedback_id，镜像 051 的
-- source_tool_call_id。用途：① 已提炼过的消息级差评不再被 list_unprocessed_complaints
-- 重复捞 ② 规则来源可回溯到具体那条消息差评。
--
-- 纯加法、幂等（ADD COLUMN IF NOT EXISTS）。无 FK：跨 schema 且 message_feedback
-- 可被会话级联清理（agent_sessions ON DELETE CASCADE），FK 会拖累，做成软引用。
-- ============================================================

ALTER TABLE knowledge.prompt_rules
    ADD COLUMN IF NOT EXISTS source_message_feedback_id UUID;

COMMENT ON COLUMN knowledge.prompt_rules.source_message_feedback_id IS
    '若规则源自 mcp.message_feedback 某条消息级差评（消息级反馈→规则的桥，migration 058），记该 message_feedback_id；工具级来源走 source_tool_call_id，手动建/老飞轮来源为 NULL。无 FK（跨 schema + 会话级联清理）。';

CREATE INDEX IF NOT EXISTS idx_prompt_rules_source_msg_fb
    ON knowledge.prompt_rules(source_message_feedback_id)
    WHERE source_message_feedback_id IS NOT NULL;
