-- P0 retries must retain a complete attempt history.  Migration 083 used a
-- permanent unique key on (order, approval_hash), which prevented a retry of
-- the exact approved payload after a provider-side failure.  Replace it with
-- a partial unique index: only one in-flight attempt is allowed for an
-- approval payload, while failed/succeeded rows remain immutable history.

ALTER TABLE pipeline.production_generation_attempts
    DROP CONSTRAINT IF EXISTS production_generation_attempts_active_unique;

CREATE UNIQUE INDEX IF NOT EXISTS uq_production_generation_attempt_active
    ON pipeline.production_generation_attempts (production_order_id, approval_hash)
    WHERE status IN ('created', 'running', 'recoverable');
