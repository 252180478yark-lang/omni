-- migration 035: tool_use_id 焊归因链（阶段0 块2 · STEP 1 列地基）2026-06-01
-- 设计草案：docs/plans/2026-06-01-阶段0-地基设计草案.md「块 2」
--
-- 背景：mcp.tool_calls.id 是 KE 端 gen_random_uuid() 自造（016 L6 + audit.py L64），
--      与 Claude 端 tool_use_id（toolu_xxxxx）毫无关联 → 归因链物理断点。
--      mcp.message_feedback.tool_use_ids[] 已存客户端侧的 Claude tool_use_id（031 L23），
--      链的「另一半」已在手，只差 tool_calls 这头没有可 join 的列。
--
-- 本 migration 范围：★只补「能 join 的列地基」★（expand-contract 的 STEP 1，纯加法 / 可逆）。
--   1. tool_use_id      —— Claude 侧 toolu_xxxxx，拿不到时留 NULL（向后兼容）
--   2. claude_session_id —— 关联 mcp.agent_sessions.claude_session_id 做会话链兜底
--   3. 部分索引（仅非 NULL 行）便于按 tool_use_id 反查
--
-- ★不在本 migration 范围（属后续代码切片 / wiring，非 schema）★：
--   - 「怎么把 Claude 的 tool_use_id 真填进这两列」是传递方案（草案 §2.3.2 方案 A/B/C），
--     涉及客户端 stream-json 解析 + 新 endpoint + audit.py 回填逻辑，全是 wiring，不在此处。
--   - 加 NOT NULL / 加 FK 约束 / 改任何现有列 —— 属 STEP 2，需老板二次确认，本文件不做。

ALTER TABLE mcp.tool_calls
  ADD COLUMN IF NOT EXISTS tool_use_id TEXT;

ALTER TABLE mcp.tool_calls
  ADD COLUMN IF NOT EXISTS claude_session_id TEXT;

COMMENT ON COLUMN mcp.tool_calls.tool_use_id IS
  'Claude 侧 tool_use_id（toolu_xxxxx）；与 mcp.message_feedback.tool_use_ids[] join 焊归因链。拿不到留 NULL，向后兼容。填充靠后续传递方案（草案块2 §2.3.2），不在本 migration。';

COMMENT ON COLUMN mcp.tool_calls.claude_session_id IS
  '关联 mcp.agent_sessions.claude_session_id，session 维兜底（tool_use_id 缺失时按会话+tool_name+时间窗对齐）。nullable，向后兼容。';

CREATE INDEX IF NOT EXISTS idx_toolcalls_tooluseid
  ON mcp.tool_calls(tool_use_id)
  WHERE tool_use_id IS NOT NULL;


-- ===== DOWN（手动回滚用）=====
-- 纯可逆：删索引 + 删两列即回到现状（现有任何代码都不依赖这两列，回填全是 NULL，无损）。
--
-- DROP INDEX IF EXISTS mcp.idx_toolcalls_tooluseid;
-- ALTER TABLE mcp.tool_calls DROP COLUMN IF EXISTS claude_session_id;
-- ALTER TABLE mcp.tool_calls DROP COLUMN IF EXISTS tool_use_id;
