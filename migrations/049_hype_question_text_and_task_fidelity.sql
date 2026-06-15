-- 049: HyPE 假设问题存原文 + 跨重建问题缓存 + tasks 恢复保真（2026-06-12）
--
-- 1) hype_embeddings.question_text：HyPE 之前只存向量不存问题原文（KB 管线发现 #3），
--    没法 debug "哪个假设问题召回了这个 chunk"，rebuild 必须重烧 LLM 重新生成。
-- 2) hype_question_cache：按 chunk 内容 hash 缓存已生成的假设问题——同内容重灌/重复上传
--    直接复用问题文本（embedding 又有 Redis 缓存），rebuild 不再重烧 LLM。
-- 3) tasks 补 chunk_size/chunk_overlap/skip_chunking/metadata：之前重启恢复
--    （recover_stuck_tasks）只回放 raw_text，自定义切块参数全丢——带 chunk_size=2000
--    的重灌任务重启后会被切回默认 768（隐藏 bug，本次补列 + 代码透传修复）。

ALTER TABLE knowledge.hype_embeddings
    ADD COLUMN IF NOT EXISTS question_text TEXT;

CREATE TABLE IF NOT EXISTS knowledge.hype_question_cache (
    content_hash TEXT PRIMARY KEY,          -- sha256("{n_questions}:{chunk前1500字}")
    questions    JSONB NOT NULL,            -- list[str] 假设问题原文
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE knowledge.tasks
    ADD COLUMN IF NOT EXISTS chunk_size    INTEGER,
    ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER,
    ADD COLUMN IF NOT EXISTS skip_chunking BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS metadata      JSONB;
