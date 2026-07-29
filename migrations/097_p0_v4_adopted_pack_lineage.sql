-- P0 v4: bind every newly created production order to the explicit adopted
-- audience pack that calibrates its frozen portrait/bridge/vector evidence.
-- The column stays nullable so immutable v2/v3 audit rows remain readable;
-- the v4 service contract requires it before creating any new order.

ALTER TABLE pipeline.production_orders
    ADD COLUMN IF NOT EXISTS audience_pack_id UUID
    REFERENCES pipeline.audience_packs(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_production_orders_audience_pack_id
    ON pipeline.production_orders (audience_pack_id)
    WHERE audience_pack_id IS NOT NULL;
