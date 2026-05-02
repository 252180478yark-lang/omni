-- ============================================================
-- Migration 008: Chat Sessions (知识问答历史会话持久化)
--
-- 目标：
--   1. 会话元信息：chat_sessions（每次点"新建对话"或第一次发言即写入）
--   2. 消息流水：   chat_messages（user / assistant，含引用、检索元数据）
--
-- 设计要点：
--   - session_id 由前端生成（sessionUid），保持与 Redis session_store 同一 key，
--     Redis 作热路径 LLM 上下文（TTL 24h，最多 20 轮），PG 作冷路径列表/恢复。
--   - soft-delete（deleted_at）保留数据以便后续分析；列表默认过滤已删除。
--   - title 初始为空，首次用户消息后由前端/后端截前 30 字作为自动标题。
--   - kb_ids / provider / model / persona_id 存会话级默认值，便于"切回继续聊"。
-- ============================================================

CREATE SCHEMA IF NOT EXISTS knowledge;

-- ────────────────────────────────────────────────────────
-- 1. 会话表
-- ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS knowledge.chat_sessions (
    id               TEXT PRIMARY KEY,         -- 前端 sessionUid，如 "session-<ts>-<rand>"
    title            TEXT NOT NULL DEFAULT '', -- 空串表示尚未命名（前端按首条 user 消息回填）
    kb_ids           JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider         TEXT,
    model            TEXT,
    persona_id       TEXT,
    message_count    INTEGER NOT NULL DEFAULT 0,
    last_message_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_active_recent
    ON knowledge.chat_sessions (last_message_at DESC NULLS LAST, created_at DESC)
    WHERE deleted_at IS NULL;

-- ────────────────────────────────────────────────────────
-- 2. 消息表
-- ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS knowledge.chat_messages (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES knowledge.chat_sessions(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content      TEXT NOT NULL DEFAULT '',
    output_mode  TEXT,                          -- 'text' / 'image' / 'video' / 'analyze'
    sources      JSONB,                         -- SourceRef[]，仅 assistant
    retrieval    JSONB,                         -- RetrievalMeta，仅 assistant
    images       JSONB,                         -- ImageResult[]，output_mode=image
    video        JSONB,                         -- VideoResult，output_mode=video
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_time
    ON knowledge.chat_messages (session_id, created_at, id);

-- ────────────────────────────────────────────────────────
-- 3. 自动维护 session.updated_at / last_message_at / message_count
-- ────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION knowledge.trg_chat_messages_touch_session()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE knowledge.chat_sessions
       SET message_count   = message_count + 1,
           last_message_at = NEW.created_at,
           updated_at      = NEW.created_at
     WHERE id = NEW.session_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS chat_messages_touch_session ON knowledge.chat_messages;
CREATE TRIGGER chat_messages_touch_session
AFTER INSERT ON knowledge.chat_messages
FOR EACH ROW EXECUTE FUNCTION knowledge.trg_chat_messages_touch_session();
