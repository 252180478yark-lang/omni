-- P0 migration-baseline gate: future migrations record their immutable source
-- checksum.  Existing rows are backfilled only by the explicit reconciliation
-- command after their canonical source is verified.

ALTER TABLE public.schema_migrations
    ADD COLUMN IF NOT EXISTS checksum TEXT;
