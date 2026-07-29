-- A ContentSpec is immutable within one P0 production order, but an owner may
-- open a new round with the same frozen truth and the same owner inputs.  The
-- original global hash key incorrectly made that valid retry collide with a
-- historical order.  Keep per-order immutability while allowing cross-order
-- reuse for both v1 history and the current v2 contract.

ALTER TABLE pipeline.production_content_specs
    DROP CONSTRAINT IF EXISTS production_content_specs_spec_hash_key;

ALTER TABLE pipeline.production_content_specs
    ADD CONSTRAINT production_content_specs_order_spec_hash_unique
    UNIQUE (production_order_id, spec_hash);

CREATE INDEX IF NOT EXISTS idx_production_content_specs_spec_hash
    ON pipeline.production_content_specs (spec_hash);
