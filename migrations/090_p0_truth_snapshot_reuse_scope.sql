-- A P0 truth snapshot is immutable within its production order, but identical
-- frozen facts must remain reusable across separate owner-approved rounds.
-- The per-order unique key already enforces one snapshot per order; the old
-- global snapshot_hash unique constraint incorrectly rejected a new round
-- that selected the same SKU, audience and product reference.

ALTER TABLE pipeline.order_truth_snapshots
    DROP CONSTRAINT IF EXISTS order_truth_snapshots_snapshot_hash_key;

CREATE INDEX IF NOT EXISTS idx_order_truth_snapshots_snapshot_hash
    ON pipeline.order_truth_snapshots (snapshot_hash);
