-- Path A MVP: 双轨动作日志合并器所需的列 + mvp_merge_run 表
-- 同时修正 mvp_daily_metric 允许店铺级指标（sku_id = '_SHOP_'）

-- ── mvp_daily_metric: 移除 FK（_SHOP_ 不在 mvp_sku 中），保留 NOT NULL ─────────
ALTER TABLE mvp_daily_metric DROP CONSTRAINT IF EXISTS mvp_daily_metric_sku_id_fkey;

-- ── mvp_change_event 扩展列 ───────────────────────────────────────────────────
-- action_type: 语义化动作类型（price_change / title_update / main_pic / sku_add / campaign / etc.）
ALTER TABLE mvp_change_event
    ADD COLUMN IF NOT EXISTS action_type    VARCHAR(64),
    ADD COLUMN IF NOT EXISTS merge_status   VARCHAR(32)  NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS merged_into    BIGINT       REFERENCES mvp_change_event(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_at     TIMESTAMPTZ  DEFAULT NOW();

-- source: 把 'user_manual' 默认值改成 'manual' 让 merger 更简洁
ALTER TABLE mvp_change_event
    ALTER COLUMN source SET DEFAULT 'manual';

-- 回填已有手动记录
UPDATE mvp_change_event
   SET source = 'manual'
 WHERE source = 'user_manual';

CREATE INDEX IF NOT EXISTS idx_mvp_event_merge_status ON mvp_change_event(merge_status, source, executed_at);

-- ── mvp_merge_run ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mvp_merge_run (
    id              VARCHAR(64)  PRIMARY KEY,
    started_at      TIMESTAMPTZ  NOT NULL,
    ended_at        TIMESTAMPTZ,
    scrape_total    INTEGER      DEFAULT 0,
    dedup_count     INTEGER      DEFAULT 0,
    promote_count   INTEGER      DEFAULT 0,
    confirm_count   INTEGER      DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);
